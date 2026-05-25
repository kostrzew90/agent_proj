import json
import logging
import time
from typing import AsyncIterator

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from core.database import ChatSession, ChatMessage, ChatContext
from core.llm import AsyncLLMClient
from core.retriever import get_retriever
from core.rewriter import QueryRewriter
from core.judge import ResponseJudge
from core.llm_reranker import LLMReranker
from services.profile_service import ProfileService

logger = logging.getLogger(__name__)


class ChatService:

    def __init__(self):
        self.retriever = get_retriever()
        self.reranker = LLMReranker()
        self.rewriter = QueryRewriter()
        self.profile_service = ProfileService()
        if settings.ai.openrouter_api_key:
            from core.openrouter import OpenRouterClient
            self.llm = OpenRouterClient(
                api_key=settings.ai.openrouter_api_key,
                model=settings.ai.openrouter_model,
            )
            logger.info("LLM: OpenRouter (%s)", settings.ai.openrouter_model)
        else:
            self.llm = AsyncLLMClient()
            logger.info("LLM: Ollama (%s)", settings.ai.llm_model)

    async def create_session(
        self,
        db: AsyncSession,
        user_id: int,
        title: str | None,
        folder_ids: list[int] | None = None,
        tag_ids: list[int] | None = None,
        document_ids: list[int] | None = None,
    ) -> ChatSession:
        session = ChatSession(
            user_id=user_id,
            title=title or "New chat",
        )
        db.add(session)
        await db.flush()

        for folder_id in (folder_ids or []):
            db.add(ChatContext(chat_id=session.id, folder_id=folder_id))
        for tag_id in (tag_ids or []):
            db.add(ChatContext(chat_id=session.id, tag_id=tag_id))
        for doc_id in (document_ids or []):
            db.add(ChatContext(chat_id=session.id, document_id=doc_id))

        await db.commit()
        await db.refresh(session)
        return session

    async def get_session_history(
        self,
        db: AsyncSession,
        chat_id: int,
    ) -> list[dict]:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_id == chat_id)
            .order_by(ChatMessage.created_at)
        )
        messages = result.scalars().all()
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    async def query_stream(
        self,
        db: AsyncSession,
        chat_id: int,
        user_id: int,
        query: str,
    ) -> AsyncIterator[str]:
        start_time = time.time()
        full_response = ""
        sources_list = []
        judge_scores: dict = {}

        # LangFuse trace
        from core.langfuse_client import get_langfuse
        lf = get_langfuse()
        trace = None
        if lf:
            try:
                trace = lf.trace(
                    name="chat-query",
                    user_id=str(user_id),
                    session_id=str(chat_id),
                    input=query,
                )
            except Exception:
                trace = None

        try:
            # a. Save user message to DB
            user_msg = ChatMessage(
                chat_id=chat_id,
                role="user",
                content=query,
            )
            db.add(user_msg)
            await db.commit()

            # b. Get chat history
            history = await self.get_session_history(db, chat_id)
            # Exclude the message we just added (last in history)
            prior_history = history[:-1] if history else []

            # c. Rewrite query if this is a follow-up
            rewritten_query = query
            if prior_history:
                try:
                    rewritten_query = await self.rewriter.rewrite(query, prior_history)
                    logger.debug("Rewritten query: %s", rewritten_query)
                except Exception as exc:
                    logger.warning("Query rewriting failed, using original: %s", exc)

            if trace:
                try:
                    trace.span(
                        name="query-rewrite",
                        input={"query": query, "history_turns": len(prior_history)},
                        output={"rewritten": rewritten_query},
                    )
                except Exception:
                    pass

            # d. Get folder/tag filters from ChatContext
            ctx_result = await db.execute(
                select(ChatContext).where(ChatContext.chat_id == chat_id)
            )
            contexts = ctx_result.scalars().all()
            folder_ids = [c.folder_id for c in contexts if c.folder_id is not None]
            tag_ids = [c.tag_id for c in contexts if c.tag_id is not None]
            document_ids = [c.document_id for c in contexts if c.document_id is not None]

            # e. Retrieve relevant chunks
            try:
                retrieval_results = await self.retriever.search(
                    rewritten_query,
                    db,
                    top_k=settings.retrieval.top_k,
                    folder_ids=folder_ids or None,
                    tag_ids=tag_ids or None,
                    document_ids=document_ids or None,
                )
            except Exception as exc:
                logger.error("Retrieval failed: %s", exc)
                retrieval_results = []

            # Rerank: 3-dim LLM scoring → hybrid merge → diversity cap → top-K
            if retrieval_results:
                try:
                    retrieval_results = await self.reranker.rerank(
                        rewritten_query,
                        retrieval_results,
                        top_k=settings.retrieval.reranker_top_k,
                    )
                except Exception as exc:
                    logger.warning("Reranker failed: %s — using RRF results", exc)

            if trace:
                try:
                    trace.span(
                        name="retrieval",
                        input={"query": rewritten_query, "top_k": settings.retrieval.top_k},
                        output={
                            "chunks_found": len(retrieval_results),
                            "reranker_enabled": settings.retrieval.reranker_enabled,
                            "reranker_top_k": settings.retrieval.reranker_top_k,
                            "top_scores": [round(r.score, 3) for r in retrieval_results[:3]] if retrieval_results else [],
                        },
                    )
                except Exception:
                    pass

            # f. Detect query language for explicit instruction
            polish_chars = set("ąęóśźżćńłĄĘÓŚŹŻĆŃŁ")
            is_polish = any(c in polish_chars for c in query) or any(
                w in query.lower() for w in ["jak", "czy", "co ", "ile", "gdzie", "kiedy", "dlaczego", "który", "która"]
            )
            lang_instruction = "Odpowiedź napisz PO POLSKU." if is_polish else "Answer in English."

            system_prompt = (
                f"{lang_instruction} "
                "Odpowiadaj WYŁĄCZNIE na podstawie dostarczonego kontekstu. "
                "Jeśli informacji nie ma w kontekście, powiedz że nie wiesz. "
                "Cytuj źródła jako [1], [2] itp. przy odwoływaniu się do konkretnych treści."
            )

            # g. Build user prompt with numbered context chunks + query
            if retrieval_results:
                context_parts = []
                for idx, r in enumerate(retrieval_results, start=1):
                    header = f"[{idx}] {r.document_name}"
                    if r.page_number:
                        header += f" (page {r.page_number})"
                    if r.section_title:
                        header += f" — {r.section_title}"
                    context_parts.append(f"{header}\n{r.content}")
                context_block = "\n\n".join(context_parts)
                user_prompt = f"Kontekst:\n{context_block}\n\nPytanie: {query}" if is_polish else f"Context:\n{context_block}\n\nQuestion: {query}"
            else:
                user_prompt = f"Kontekst: (brak pasujących dokumentów)\n\nPytanie: {query}" if is_polish else f"Context: (no relevant documents found)\n\nQuestion: {query}"

            # h. Stream LLM response
            try:
                async for token in self.llm.generate_stream(
                    prompt=user_prompt,
                    system=system_prompt,
                ):
                    full_response += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            except Exception as exc:
                logger.error("LLM streaming error: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'content': f'LLM error: {exc}'})}\n\n"
                return

            if trace:
                try:
                    trace.generation(
                        name="llm-generate",
                        model=settings.ai.openrouter_model if settings.ai.openrouter_api_key else settings.ai.llm_model,
                        input=user_prompt,
                        output=full_response,
                    )
                except Exception:
                    pass

            # Build sources list
            sources_list = [
                {
                    "document": r.document_name,
                    "page": r.page_number,
                    "section": r.section_title,
                    "chunk_id": r.chunk_id,
                }
                for r in retrieval_results
            ]
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources_list})}\n\n"

            # Run judge (non-blocking best-effort)
            context_chunks = [r.content for r in retrieval_results]
            try:
                async with ResponseJudge() as judge:
                    judge_result = await judge.evaluate(query, full_response, context_chunks)
                judge_scores = {
                    "groundedness": judge_result.groundedness,
                    "completeness": judge_result.completeness,
                    "relevance": judge_result.relevance,
                }
                yield f"data: {json.dumps({'type': 'judge', **judge_scores})}\n\n"
            except Exception as exc:
                logger.warning("Judge evaluation failed: %s", exc)
                judge_scores = {}

            if trace and judge_scores:
                try:
                    trace.span(
                        name="judge",
                        input={"query": query, "response_len": len(full_response)},
                        output=judge_scores,
                    )
                except Exception:
                    pass

            # Update user profile (topics + language)
            try:
                context_texts = [r.content for r in retrieval_results]
                await self.profile_service.update_topics(db, user_id, query, context_texts)
                await self.profile_service.detect_language(db, user_id, query)
            except Exception as exc:
                logger.warning("Profile update failed: %s", exc)

            # Final done event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as exc:
            logger.exception("Unexpected error in query_stream: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
            return

        finally:
            # i. Save assistant message to DB with sources and judge scores
            if full_response:
                latency_ms = int((time.time() - start_time) * 1000)
                assistant_msg = ChatMessage(
                    chat_id=chat_id,
                    role="assistant",
                    content=full_response,
                    sources=sources_list or None,
                    groundedness_score=judge_scores.get("groundedness"),
                    completeness_score=judge_scores.get("completeness"),
                    relevance_score=judge_scores.get("relevance"),
                    latency_ms=latency_ms,
                )
                db.add(assistant_msg)
                try:
                    await db.commit()
                except Exception as exc:
                    logger.error("Failed to save assistant message: %s", exc)

            if trace:
                try:
                    trace.update(
                        output=full_response,
                        metadata={
                            "latency_ms": int((time.time() - start_time) * 1000),
                            "chunks_retrieved": len(sources_list),
                            **judge_scores,
                        },
                    )
                    lf.flush()
                except Exception:
                    pass

    async def delete_session(self, db: AsyncSession, chat_id: int) -> None:
        await db.execute(delete(ChatSession).where(ChatSession.id == chat_id))
        await db.commit()
