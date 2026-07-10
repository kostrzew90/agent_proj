"""
RAG System — Query Rewriter for conversational context.
Rewrites follow-up questions into standalone queries using LLM.
"""

from core.llm import AsyncLLMClient
from config import settings


class QueryRewriter:
    def __init__(self, llm_client: AsyncLLMClient | None = None):
        if llm_client:
            self.llm = llm_client
        elif settings.ai.openrouter_api_key:
            from core.openrouter import OpenRouterClient
            self.llm = OpenRouterClient(
                api_key=settings.ai.openrouter_api_key,
                model=settings.ai.openrouter_model,
                base_url=settings.ai.openrouter_base_url or None,
            )
        else:
            self.llm = AsyncLLMClient(
                base_url=settings.ai.ollama_url,
                model=settings.ai.llm_model,
            )

    async def rewrite(self, query: str, chat_history: list[dict]) -> str:
        if not chat_history or len(chat_history) <= 1:
            return query

        context_messages = chat_history[-5:]

        messages = [
            *context_messages,
            {"role": "user", "content": query},
        ]

        system = (
            "Rewrite the follow-up question as a standalone question. "
            "Keep the same language. "
            "Output ONLY the rewritten question, nothing else."
        )

        result = await self.llm.chat(
            messages=messages,
            temperature=0.1,
        )

        rewritten = result.text.strip()
        return rewritten if rewritten else query

    def detect_language(self, text: str) -> str:
        polish_chars = set("ąęóśźżćńł")
        if any(ch in polish_chars for ch in text.lower()):
            return "pl"
        return "en"
