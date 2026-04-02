import json
from langfuse.decorators import observe
from agent.providers import call_llm, get_provider_chain
from agent.sessions import Session, Message, add_episode
from agent.context_manager import compose_context
from tools.registry import get_tools
from tools.claw_bridge import execute_tool

MAX_TOOL_ROUNDS = 10


@observe(name="agent_step")
async def agent_step(session: Session, user_message: str) -> str:
    """Run one full agent step: user message → LLM → tool calls → final response.

    Handles multi-turn tool calling (up to MAX_TOOL_ROUNDS).
    """
    # Add user message to session history
    session.messages.append(Message(role="user", content=user_message))

    # Log episode
    await add_episode(session.id, "user_message", user_message)

    # Build message history for LLM
    history = [{"role": m.role, "content": m.content} for m in session.messages
               if m.role in ("user", "assistant") and m.content]

    provider_chain = get_provider_chain()
    tools = get_tools()

    for round_num in range(MAX_TOOL_ROUNDS):
        # Compose context with token budget
        ctx = compose_context(history)

        # Call LLM
        response = await call_llm(
            messages=ctx.messages,
            tools=tools,
            provider_chain=provider_chain,
        )

        choice = response.choices[0]
        message = choice.message

        # No tool calls — return final text response
        if not message.tool_calls:
            content = message.content or ""
            session.messages.append(Message(role="assistant", content=content))
            await add_episode(session.id, "response", content, outcome="success")
            return content

        # Process tool calls
        assistant_msg = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
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

            # Execute tool
            result = await execute_tool(tool_name, args)

            await add_episode(
                session.id, "tool_call",
                f"{tool_name}({json.dumps(args, ensure_ascii=False)[:200]})",
                outcome="success" if "error" not in result.lower()[:50] else "error",
            )

            # Add tool result to history
            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Max rounds reached
    fallback = "I've reached the maximum number of tool call rounds. Here's what I've done so far — please let me know how to proceed."
    session.messages.append(Message(role="assistant", content=fallback))
    return fallback
