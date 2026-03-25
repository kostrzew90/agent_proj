"""
Ollama LLM Client

Obsługuje generowanie tekstu i embeddings przez Ollama API.
Z fallback na Claude API gdy Ollama niedostępny.
"""
import json
from typing import List, Optional, Dict, Any

import requests
import httpx

from config import config


class OllamaError(Exception):
    """Ollama API Error"""
    pass


class OllamaClient:
    """Ollama API Client with Claude fallback"""

    def __init__(self):
        self.cfg = config.ollama
        self.claude_cfg = config.claude
        self.base_url = self.cfg.base_url
        self.timeout = self.cfg.timeout

    def _ollama_request(self, endpoint: str, data: Dict) -> Dict:
        """Make request to Ollama API"""
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.post(
                url,
                json=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise OllamaError(f"Ollama timeout after {self.timeout}s")
        except requests.RequestException as e:
            raise OllamaError(f"Ollama request failed: {e}")

    def _ollama_stream(self, endpoint: str, data: Dict) -> str:
        """Make streaming request to Ollama API"""
        url = f"{self.base_url}{endpoint}"
        data["stream"] = True

        try:
            response = requests.post(
                url,
                json=data,
                timeout=self.timeout,
                stream=True
            )
            response.raise_for_status()

            result = ""
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        result += chunk["response"]
                    if chunk.get("done"):
                        break

            return result

        except requests.Timeout:
            raise OllamaError(f"Ollama timeout after {self.timeout}s")
        except requests.RequestException as e:
            raise OllamaError(f"Ollama request failed: {e}")

    def _claude_request(self, prompt: str, system: str = None) -> str:
        """Fallback to Claude API"""
        if not self.claude_cfg.api_key:
            raise OllamaError("Claude API key not configured")

        messages = [{"role": "user", "content": prompt}]

        data = {
            "model": self.claude_cfg.model,
            "max_tokens": 1024,
            "messages": messages
        }

        if system:
            data["system"] = system

        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.claude_cfg.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=data,
                timeout=30
            )
            response.raise_for_status()

            result = response.json()
            return result["content"][0]["text"]

        except httpx.RequestError as e:
            raise OllamaError(f"Claude request failed: {e}")

    def generate(self, prompt: str, model: str = None,
                 system: str = None, use_claude_fallback: bool = True) -> str:
        """
        Generate text response

        Args:
            prompt: User prompt
            model: Model name (defaults to config)
            system: System prompt
            use_claude_fallback: Use Claude if Ollama fails

        Returns:
            Generated text
        """
        model = model or self.cfg.model_chat

        try:
            data = {
                "model": model,
                "prompt": prompt,
                "stream": False
            }

            if system:
                data["system"] = system

            response = self._ollama_request("/api/generate", data)
            return response.get("response", "")

        except OllamaError as e:
            if use_claude_fallback and self.claude_cfg.enabled:
                return self._claude_request(prompt, system)
            raise e

    def chat(self, messages: List[Dict[str, str]], model: str = None,
             system: str = None) -> str:
        """
        Chat completion

        Args:
            messages: List of {"role": "user/assistant", "content": "..."}
            model: Model name
            system: System prompt

        Returns:
            Assistant response
        """
        model = model or self.cfg.model_chat

        try:
            data = {
                "model": model,
                "messages": messages,
                "stream": False
            }

            if system:
                data["system"] = system

            response = self._ollama_request("/api/chat", data)
            return response.get("message", {}).get("content", "")

        except OllamaError:
            # Fallback to Claude
            if self.claude_cfg.enabled:
                # Convert to single prompt
                prompt = "\n".join([
                    f"{m['role']}: {m['content']}"
                    for m in messages
                ])
                return self._claude_request(prompt, system)
            raise

    def embed(self, text: str, model: str = None) -> List[float]:
        """
        Generate embedding for text

        Args:
            text: Text to embed
            model: Embedding model

        Returns:
            Embedding vector (1024 dimensions for qwen3-embedding)
        """
        model = model or self.cfg.model_embedding

        data = {
            "model": model,
            "prompt": text
        }

        response = self._ollama_request("/api/embeddings", data)
        return response.get("embedding", [])

    def embed_batch(self, texts: List[str], model: str = None) -> List[List[float]]:
        """
        Generate embeddings for multiple texts

        Args:
            texts: List of texts
            model: Embedding model

        Returns:
            List of embedding vectors
        """
        return [self.embed(text, model) for text in texts]

    def analyze_signal(self, signal_data: Dict, market_context: Dict,
                       knowledge: List[str] = None) -> Dict:
        """
        Analyze trading signal using LLM

        Args:
            signal_data: Signal information
            market_context: Current market indicators
            knowledge: Relevant knowledge from embeddings

        Returns:
            {"score": 1-10, "reasoning": "...", "recommendation": "..."}
        """
        knowledge_text = "\n".join(knowledge) if knowledge else "No relevant knowledge found."

        prompt = f"""Analyze this trading signal:

Signal:
- Type: {signal_data.get('type', 'unknown')}
- Symbol: {signal_data.get('symbol', 'unknown')}
- Score: {signal_data.get('score', 0)}
- Reasons: {', '.join(signal_data.get('reasons', []))}

Market Context:
- RSI: {market_context.get('rsi_14', 'N/A')}
- MACD Histogram: {market_context.get('macd_histogram', 'N/A')}
- Trend (EMA200): {'ABOVE' if market_context.get('close', 0) > market_context.get('ema_200', 0) else 'BELOW'}
- Funding Rate: {market_context.get('funding_rate', 'N/A')}

Relevant Knowledge:
{knowledge_text}

Evaluate the signal quality on a scale of 1-10 and provide brief reasoning.
Respond in JSON format:
{{"score": <1-10>, "reasoning": "<brief explanation>", "recommendation": "<execute/wait/reject>"}}
"""

        system = """You are a professional crypto futures trader assistant.
Analyze signals objectively based on technical indicators and market context.
Be conservative - only recommend execution for high-quality setups."""

        try:
            response = self.generate(prompt, system=system)

            # Try to parse JSON from response
            import re
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                return json.loads(json_match.group())

            return {
                "score": 5,
                "reasoning": response,
                "recommendation": "wait"
            }

        except Exception as e:
            return {
                "score": 0,
                "reasoning": f"Analysis failed: {e}",
                "recommendation": "wait"
            }

    def is_available(self) -> bool:
        """Check if Ollama is available"""
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """List available models"""
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
