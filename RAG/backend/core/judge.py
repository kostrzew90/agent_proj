"""
RAG System — LLM-as-Judge for response quality validation.
Evaluates groundedness, completeness, and relevance of RAG answers.
"""

import json
import logging
import re
from dataclasses import dataclass

from config import settings
from core.llm import AsyncLLMClient

logger = logging.getLogger("rag.core.judge")

_SYSTEM_PROMPT = """\
You are a strict RAG quality evaluator. Your task is to evaluate a generated answer \
against the provided context chunks and the user's question.

Score the answer on three dimensions (each 0.0 to 1.0):
- groundedness: Is every claim in the answer directly supported by the context chunks? \
  (1.0 = fully grounded, 0.0 = contradicts or ignores context)
- completeness: Does the answer cover all relevant information present in the context? \
  (1.0 = covers everything relevant, 0.0 = misses most relevant info)
- relevance: Does the answer actually address the user's question? \
  (1.0 = directly on-topic, 0.0 = completely off-topic)

Respond with ONLY a JSON object, no explanation, no markdown, no extra text:
{"groundedness": <float>, "completeness": <float>, "relevance": <float>}"""


@dataclass
class JudgeResult:
    groundedness: float
    completeness: float
    relevance: float
    duration_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _parse_scores(text: str) -> dict:
    """Extract JSON scores from LLM output, handling markdown and extra text."""
    # Strip <think>...</think> blocks (qwen3 chain-of-thought)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object from surrounding text / markdown code blocks
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


_DEFAULT_SCORES = {"groundedness": 0.5, "completeness": 0.5, "relevance": 0.5}


def would_flag_retry(groundedness: float | None, threshold: float) -> bool:
    """Shadow-mode signal: would a self-correction retry fire for this score?
    Faza 0 — logging/telemetry only, no retry is actually executed yet."""
    return groundedness is not None and groundedness < threshold


class ResponseJudge:
    """Async LLM-as-judge that scores RAG responses on three quality dimensions."""

    def __init__(self):
        self.provider = "openrouter" if settings.ai.openrouter_api_key else "ollama"
        self.model = settings.ai.openrouter_judge_model if settings.ai.openrouter_api_key else settings.ai.judge_model
        if settings.ai.openrouter_api_key:
            from core.openrouter import OpenRouterClient
            self._client = OpenRouterClient(
                api_key=settings.ai.openrouter_api_key,
                model=settings.ai.openrouter_judge_model,
                base_url=settings.ai.openrouter_base_url or None,
                fallback_api_key=settings.ai.openrouter_fallback_api_key or None,
                fallback_model=settings.ai.openrouter_fallback_model or None,
                fallback_base_url=settings.ai.openrouter_fallback_base_url or None,
            )
        else:
            self._client = AsyncLLMClient(
                base_url=settings.ai.ollama_url,
                model=settings.ai.judge_model,
            )

    async def evaluate(
        self,
        query: str,
        answer: str,
        context_chunks: list[str],
    ) -> JudgeResult:
        """Evaluate a RAG answer and return quality scores."""
        chunks_text = "\n".join(
            f"[{i + 1}] {chunk}" for i, chunk in enumerate(context_chunks)
        )

        prompt = (
            f"QUESTION:\n{query}\n\n"
            f"CONTEXT CHUNKS:\n{chunks_text}\n\n"
            f"GENERATED ANSWER:\n{answer}"
        )

        try:
            result = await self._client.generate(
                prompt=prompt,
                system=_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=256,
                think=True,
            )
            scores = _parse_scores(result.text)
        except Exception as exc:
            logger.warning("Judge LLM call failed: %s — using default scores", exc)
            scores = {}
            result = type("_Dummy", (), {"total_duration_ms": 0.0})()

        def _clamp(val, default: float) -> float:
            try:
                return max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                return default

        return JudgeResult(
            groundedness=_clamp(
                scores.get("groundedness"), _DEFAULT_SCORES["groundedness"]
            ),
            completeness=_clamp(
                scores.get("completeness"), _DEFAULT_SCORES["completeness"]
            ),
            relevance=_clamp(
                scores.get("relevance"), _DEFAULT_SCORES["relevance"]
            ),
            duration_ms=getattr(result, "total_duration_ms", 0.0),
            prompt_tokens=getattr(result, "prompt_tokens", 0),
            completion_tokens=getattr(result, "completion_tokens", 0),
        )

    async def close(self):
        await self._client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
