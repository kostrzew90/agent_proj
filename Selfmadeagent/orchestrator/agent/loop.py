import json
import os
from langfuse.decorators import observe
from agent.providers import call_llm, get_provider_chain
from agent.sessions import Session, Message, add_episode, get_pool
from agent.context_manager import compose_context
from agent.facts import load_facts
from agent.validator import OutputValidator
from agent.retry_budget import RetryBudget
from agent.evaluator import heuristic_evaluate
from memory.working import WorkingMemory
from memory.episodic import EpisodicMemory
from memory.embeddings import EmbeddingClient
from memory.pipeline import MemoryPipeline
from tools.registry import get_tools
from tools.claw_bridge import execute_tool, WORKSPACE

MAX_TOOL_ROUNDS = 10

# Module-level singletons (initialized on first use)
_embedder: EmbeddingClient | None = None
_episodic: EpisodicMemory | None = None
_working_memories: dict[str, WorkingMemory] = {}


async def _get_episodic() -> EpisodicMemory:
    global _embedder, _episodic
    if _episodic is None:
        _embedder = EmbeddingClient()
        pool = await get_pool()
        _episodic = EpisodicMemory(pool=pool, embedder=_embedder)
    return _episodic


def _get_working(session_id: str, goal: str | None = None) -> WorkingMemory:
    if session_id not in _working_memories:
        _working_memories[session_id] = WorkingMemory(session_id=session_id, goal=goal)
    return _working_memories[session_id]


@observe(name="agent_step")
async def agent_step(session: Session, user_message: str) -> str:
    """Run one full agent step with memory + validation."""
    session.messages.append(Message(role="user", content=user_message))
    await add_episode(session.id, "user_message", user_message)

    workspace = str(WORKSPACE)
    facts = load_facts(workspace)
    validator = OutputValidator(facts=facts)
    retry_budget = RetryBudget()

    # Memory
    episodic = await _get_episodic()
    working = _get_working(session.id, goal=session.goal)
    pipeline = MemoryPipeline(working=working, episodic=episodic)

    # Retrieve relevant memory
    memory_text = await pipeline.retrieve(user_message, session.id, budget_tokens=2000)
    facts_prompt = facts.to_prompt() if facts else None

    history = [{"role": m.role, "content": m.content} for m in session.messages
               if m.role in ("user", "assistant") and m.content]

    provider_chain = get_provider_chain()
    tools = get_tools()

    for round_num in range(MAX_TOOL_ROUNDS):
        ctx = compose_context(history, memory_text=memory_text, facts_text=facts_prompt)
        response = await call_llm(
            messages=ctx.messages, tools=tools, provider_chain=provider_chain,
        )

        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            content = message.content or ""
            session.messages.append(Message(role="assistant", content=content))
            await add_episode(session.id, "response", content, outcome="success")
            return content

        assistant_msg = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ],
        }
        history.append(assistant_msg)

        for tc in message.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            # Validate
            validation = validator.validate_tool_call(tool_name, args, workspace)
            if not validation.valid:
                block_msg = f"Blocked: {validation.reason}"
                await add_episode(session.id, "validation_block", block_msg, outcome="blocked")
                history.append({"role": "tool", "tool_call_id": tc.id, "content": f"ERROR: {block_msg}"})
                continue

            if validation.warnings:
                for w in validation.warnings:
                    await add_episode(session.id, "validation_warning", w, outcome="warned")

            # Execute
            retry_budget.reset_action()
            result = await execute_tool(tool_name, args)

            # Evaluate
            score = heuristic_evaluate(tool_name, args, result)
            working.add_step(
                action=f"{tool_name}({json.dumps(args, ensure_ascii=False)[:100]})",
                result_summary=result[:200],
                score=score,
            )

            # Track active files
            if tool_name in ("read_file", "write_file", "edit_file"):
                working.add_active_file(args.get("path", ""))

            await add_episode(
                session.id, "tool_call",
                f"{tool_name}({json.dumps(args, ensure_ascii=False)[:200]})",
                outcome="success" if score >= 0.7 else "error",
            )

            history.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    fallback = "I've reached the maximum number of tool call rounds."
    session.messages.append(Message(role="assistant", content=fallback))
    return fallback
