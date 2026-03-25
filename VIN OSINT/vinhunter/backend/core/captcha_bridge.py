"""
CaptchaBridge — pomocnicze funkcje dla pluginów obsługujących CAPTCHA.

Plugin który wymaga CAPTCHA:
1. Pobiera obrazek CAPTCHA
2. Zwraca PluginResult ze status=CAPTCHA_REQUIRED i data["captcha_image_base64"]
3. ScanEngine przesyła go do frontendu przez WebSocket
4. Gdy użytkownik odpowie — ScanEngine wywołuje plugin.submit_captcha(vin, answer)
"""

import base64
import httpx
from typing import Optional


async def fetch_captcha_as_base64(url: str, session: Optional[httpx.AsyncClient] = None) -> str:
    """Pobierz obrazek CAPTCHA i zakoduj jako base64 data URI."""
    if session:
        response = await session.get(url)
    else:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)

    content_type = response.headers.get("content-type", "image/png").split(";")[0]
    encoded = base64.b64encode(response.content).decode()
    return f"data:{content_type};base64,{encoded}"
