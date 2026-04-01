import os
from typing import Optional

import google.generativeai as genai
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("llm-proxy")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_gemini(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    max_tokens: int,
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "ERROR: GEMINI_API_KEY not set"
    try:
        genai.configure(api_key=api_key)
        generation_config = genai.GenerationConfig(max_output_tokens=max_tokens)
        if system_prompt:
            m = genai.GenerativeModel(model, system_instruction=system_prompt)
        else:
            m = genai.GenerativeModel(model)
        response = m.generate_content(
            prompt,
            generation_config=generation_config,
            request_options={"timeout": 60},
        )
        return response.text
    except Exception as e:
        return f"ERROR: {e}"


def _call_openrouter(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    max_tokens: int,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "ERROR: OPENROUTER_API_KEY not set"
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def ask_gemini(
    prompt: str,
    model: str = "gemini-2.0-flash",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Ask Gemini. Free via Google AI Studio/Google One. Good for research, analysis, text."""
    return _call_gemini(prompt, model, system_prompt, max_tokens)


@mcp.tool()
def ask_openrouter(
    prompt: str,
    model: str = "meta-llama/llama-4-maverick:free",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Ask via OpenRouter free models to save Claude rate limits.
    Free models: meta-llama/llama-4-maverick:free, qwen/qwen3-235b-a22b:free, google/gemma-3-27b-it:free"""
    return _call_openrouter(prompt, model, system_prompt, max_tokens)


if __name__ == "__main__":
    mcp.run()
