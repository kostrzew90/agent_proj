"""
OpenWebUI Functions for YouTube MCP Server

Import this file as Functions in OpenWebUI Admin Panel:
1. Go to Admin Panel > Functions
2. Click "+" to create new function
3. Paste code below

Prerequisites:
- youtube-mcp container running (docker-compose up -d)
- Ollama with qwen3-embedding:0.6b model
"""

import requests
from typing import Optional
from pydantic import BaseModel, Field

# Configuration - adjust if your container is on different host/port
YOUTUBE_MCP_URL = "http://youtube-mcp:8765"  # Inside Docker network
# YOUTUBE_MCP_URL = "http://localhost:8765"  # From host machine


class Tools:
    """YouTube semantic search tools for OpenWebUI."""

    class Valves(BaseModel):
        """Configuration for YouTube tools."""
        youtube_mcp_url: str = Field(
            default="http://youtube-mcp:8765",
            description="URL of YouTube MCP server"
        )

    def __init__(self):
        self.valves = self.Valves()

    def youtube_embed(self, url: str) -> str:
        """
        Indeksuje film YouTube - pobiera transkrypcję, generuje embeddingi
        i zapisuje do bazy wektorowej do późniejszego wyszukiwania.

        :param url: URL filmu YouTube (np. https://youtube.com/watch?v=...)
        :return: Informacje o zaindeksowanym filmie
        """
        try:
            response = requests.post(
                f"{self.valves.youtube_mcp_url}/youtube/embed",
                json={"url": url},
                timeout=300  # Video processing can take time
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                return f"Błąd: {data['error']}"

            return (
                f"✅ Film zaindeksowany!\n\n"
                f"**Tytuł:** {data['title']}\n"
                f"**Kanał:** {data['channel']}\n"
                f"**Data:** {data['upload_date']}\n"
                f"**Chunków:** {data['chunks_count']}\n"
                f"**Język napisów:** {data['subtitle_language']}"
            )
        except requests.exceptions.RequestException as e:
            return f"Błąd połączenia z YouTube MCP: {e}"
        except Exception as e:
            return f"Błąd: {e}"

    def youtube_search(
        self,
        query: str,
        year: Optional[int] = None,
        title_filter: Optional[str] = None,
        limit: int = 8
    ) -> str:
        """
        Wyszukuje semantycznie w transkrypcjach zaindeksowanych filmów YouTube.
        Zwraca fragmenty tekstu z timestampami.

        :param query: Zapytanie w języku naturalnym (np. "co mówił o inflacji")
        :param year: Filtruj po roku publikacji (opcjonalne)
        :param title_filter: Filtruj po fragmencie tytułu (opcjonalne)
        :param limit: Maksymalna liczba wyników (domyślnie 8)
        :return: Lista fragmentów z timestampami i similarity score
        """
        try:
            payload = {"query": query, "limit": limit}
            if year:
                payload["year"] = year
            if title_filter:
                payload["title_filter"] = title_filter

            response = requests.post(
                f"{self.valves.youtube_mcp_url}/youtube/search",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            results = response.json()

            if isinstance(results, dict) and "error" in results:
                return f"Błąd: {results['error']}"

            if not results:
                return "Brak wyników dla tego zapytania."

            output = f"🔍 Znaleziono {len(results)} wyników:\n\n"
            current_title = None

            for r in results:
                if r['title'] != current_title:
                    current_title = r['title']
                    output += f"### {r['title']}\n"
                    output += f"*{r['channel']} | {r['date']}*\n\n"

                output += f"**[{r['timestamp']}]** (podobieństwo: {r['similarity']}%)\n"
                text = r['text'][:400] + "..." if len(r['text']) > 400 else r['text']
                output += f"> {text}\n\n"

            return output

        except requests.exceptions.RequestException as e:
            return f"Błąd połączenia z YouTube MCP: {e}"
        except Exception as e:
            return f"Błąd: {e}"

    def youtube_list(self) -> str:
        """
        Wyświetla listę wszystkich zaindeksowanych filmów YouTube.

        :return: Lista filmów z metadanymi
        """
        try:
            response = requests.get(
                f"{self.valves.youtube_mcp_url}/youtube/list",
                timeout=30
            )
            response.raise_for_status()
            videos = response.json()

            if isinstance(videos, dict) and "error" in videos:
                return f"Błąd: {videos['error']}"

            if not videos:
                return "Brak zaindeksowanych filmów. Użyj youtube_embed aby dodać film."

            output = f"📺 **{len(videos)} zaindeksowanych filmów:**\n\n"

            for v in videos:
                title = v['title'][:55] + "..." if len(v['title']) > 55 else v['title']
                output += f"- **{title}**\n"
                output += f"  {v['channel']} | {v['date']} | {v['chunks']} chunków\n\n"

            return output

        except requests.exceptions.RequestException as e:
            return f"Błąd połączenia z YouTube MCP: {e}"
        except Exception as e:
            return f"Błąd: {e}"
