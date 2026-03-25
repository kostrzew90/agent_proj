"""Chainlit chat application — RAG pipeline with streaming + force-graph."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote

import chainlit as cl

from ai_repo.core.database import Database
from ai_repo.core.embeddings import EmbeddingClient
from ai_repo.core.llm import LLMClient
from ai_repo.core.memory import MemoryManager
from ai_repo.core.prompt_composer import PromptComposer
from ai_repo.core.retriever import Retriever

logger = logging.getLogger(__name__)


def _generate_sync(llm: "LLMClient", prompt: str, system: str) -> str:
    """Synchronous LLM generation via Ollama HTTP — avoids async event loop issues."""
    import httpx as _httpx
    import json as _json

    payload = {
        "model": llm.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": llm.temperature,
            "num_predict": llm.max_tokens,
        },
    }
    if system:
        payload["system"] = system

    try:
        with _httpx.Client(timeout=llm.ollama_timeout) as client:
            resp = client.post(f"{llm.ollama_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
    except Exception as e:
        logger.error(f"Sync LLM generation failed: {e}")
        return f"[LLM Error: {e}]"


def _build_graph_data(results: list[dict]) -> dict:
    """Extract graph nodes/links from retrieval results for force-graph."""
    nodes: list[dict] = []
    links: list[dict] = []
    seen_ids: set[str] = set()

    for r in results:
        neighbors = r.get("graph_neighbors", [])
        if not neighbors:
            continue

        # Add source node (from the chunk's file)
        src_name = r.get("path", "").rsplit("/", 1)[-1].replace(".py", "")
        if src_name and src_name not in seen_ids:
            nodes.append({
                "id": src_name,
                "name": src_name,
                "kind": "module",
                "file_path": r.get("path", ""),
                "start_line": r.get("start_line"),
            })
            seen_ids.add(src_name)

        for n in neighbors:
            nid = n["name"]
            if nid not in seen_ids:
                nodes.append({
                    "id": nid,
                    "name": n["name"],
                    "kind": n["kind"],
                    "file_path": n.get("file_path", ""),
                    "start_line": None,
                })
                seen_ids.add(nid)

            link_key = f"{src_name}->{nid}"
            if link_key not in seen_ids:
                links.append({
                    "source": src_name,
                    "target": nid,
                    "edge_type": n.get("edge_type", "related"),
                })
                seen_ids.add(link_key)

    return {"nodes": nodes, "links": links}


@cl.on_chat_start
async def on_start():
    """Welcome message + sidebar with project memory facts."""
    try:
        db = Database()
        memory = MemoryManager(db=db)
        facts = memory.get_all_facts()

        # Sidebar with memory facts
        if facts:
            elements = []
            for f in facts[:20]:
                elements.append(
                    cl.Text(
                        name=f["key"],
                        content=f"{f['value']}\n\nConfidence: {f['confidence']:.0%}",
                    )
                )
            await cl.ElementSidebar.set_title("Project Memory")
            await cl.ElementSidebar.set_elements(elements)

    except Exception as e:
        logger.warning(f"Failed to load memory sidebar: {e}")

    await cl.Message(
        content=(
            "Welcome to **kontekst.ai**! Ask me anything about the codebase.\n\n"
            "I'll search through indexed code, project memory, and the symbol graph "
            "to give you accurate, sourced answers.\n\n"
            "You can also explore the code graph: "
            "[Open Graph Explorer](/static/graph.html)"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """RAG pipeline: retrieve → compose → stream → sources + mini-graph."""
    import asyncio
    import functools

    try:
        logger.info(f"Chat message received: {message.content[:100]}")

        db = Database()
        retriever = Retriever(db=db, embedding_client=EmbeddingClient())
        composer = PromptComposer(db=db)
        llm = LLMClient(db=db, purpose="chat")
        memory = MemoryManager(db=db)

        # 1. Retrieve relevant chunks (SYNC in thread — async httpx conflicts with mount_chainlit)
        logger.info("Starting retrieval (sync)...")
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, functools.partial(retriever.retrieve_sync, message.content)
        )
        logger.info(f"Retrieved {len(results)} chunks")

        # 2. Get memory facts
        facts = memory.search_facts(message.content)
        logger.info(f"Found {len(facts)} memory facts")

        # 3. Compose prompts
        system_prompt, user_prompt = composer.compose(message.content, results, facts)

        # 4. Stream LLM response (sync HTTP streaming in thread, push tokens via queue)
        logger.info("Starting LLM generation...")
        msg = cl.Message(content="")
        await msg.send()

        try:
            # Use sync Ollama streaming to avoid event loop conflicts
            full_response = await loop.run_in_executor(
                None, functools.partial(
                    _generate_sync, llm, user_prompt, system_prompt
                )
            )
            await msg.stream_token(full_response)
            await msg.update()
            logger.info("LLM generation completed")
        except Exception as e:
            logger.error(f"LLM generation error: {e}", exc_info=True)
            await msg.stream_token(f"\n\n[Error during generation: {str(e)}]")
            await msg.update()

        # 5. Sources as side elements
        logger.debug(f"Adding {len(results[:5])} source elements...")
        elements: list[cl.Text] = []
        for r in results[:5]:
            path = r.get("path", "unknown")
            start = r.get("start_line", "")
            score = r.get("rrf_score", r.get("score", 0))
            content_preview = r.get("content", "")[:200]

            elements.append(
                cl.Text(
                    name=f"{path}:{start}",
                    content=f"**Score:** {score:.4f}\n\n```\n{content_preview}\n```",
                    display="side",
                )
            )

        if elements:
            msg.elements = elements
            await msg.update()
            logger.debug("Sources updated")

        # 6. Mini-graph visualization (if graph data available)
        logger.debug("Building graph visualization...")
        graph_data = _build_graph_data(results)
        if graph_data["nodes"]:
            encoded = quote(json.dumps(graph_data, ensure_ascii=False))
            graph_url = f"/static/graph.html?data={encoded}"

            await cl.Message(
                content=f"**Symbol Graph** ({len(graph_data['nodes'])} nodes, "
                        f"{len(graph_data['links'])} edges): "
                        f"[Open in Graph Explorer]({graph_url})",
            ).send()

        logger.info("Chat message processing completed")

    except Exception as e:
        logger.error(f"Error in on_message: {e}", exc_info=True)
        await cl.Message(
            content=f"Sorry, an error occurred: {str(e)}\n\nPlease check the server logs for details."
        ).send()
