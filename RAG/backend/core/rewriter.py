"""
RAG System — Query Rewriter for conversational context.
Rewrites follow-up questions into standalone queries using LLM.
"""

from core.llm import AsyncLLMClient
from config import settings


class QueryRewriter:
    def __init__(self, llm_client: AsyncLLMClient | None = None):
        self.last_usage = None  # GenerationResult of the most recent rewrite() call, or None if it short-circuited
        self.provider = "openrouter" if settings.ai.openrouter_api_key else "ollama"
        self.model = settings.ai.openrouter_model if settings.ai.openrouter_api_key else settings.ai.llm_model
        if llm_client:
            self.llm = llm_client
        elif settings.ai.openrouter_api_key:
            from core.openrouter import OpenRouterClient
            self.llm = OpenRouterClient(
                api_key=settings.ai.openrouter_api_key,
                model=settings.ai.openrouter_model,
                base_url=settings.ai.openrouter_base_url or None,
                fallback_api_key=settings.ai.openrouter_fallback_api_key or None,
                fallback_model=settings.ai.openrouter_fallback_model or None,
                fallback_base_url=settings.ai.openrouter_fallback_base_url or None,
            )
        else:
            self.llm = AsyncLLMClient(
                base_url=settings.ai.ollama_url,
                model=settings.ai.llm_model,
            )

    async def rewrite(self, query: str, chat_history: list[dict]) -> str:
        self.last_usage = None
        if not chat_history or len(chat_history) <= 1:
            return query

        context_messages = chat_history[-5:]

        system = (
            "Rewrite the follow-up question as a standalone question. "
            "Keep the same language. "
            "Output ONLY the rewritten question, nothing else."
        )

        # The system prompt must travel inside `messages` — neither AsyncLLMClient.chat
        # nor OpenRouterClient.chat accepts a `system` argument, so passing it separately
        # silently dropped it and the LLM just answered the follow-up instead of
        # rewriting it. That answer then became the retrieval query.
        messages = [
            {"role": "system", "content": system},
            *context_messages,
            {"role": "user", "content": query},
        ]

        result = await self.llm.chat(
            messages=messages,
            temperature=0.1,
        )
        self.last_usage = result

        rewritten = result.text.strip()
        return rewritten if rewritten else query

    def detect_language(self, text: str) -> str:
        polish_chars = set("ąęóśźżćńł")
        if any(ch in polish_chars for ch in text.lower()):
            return "pl"
        return "en"
