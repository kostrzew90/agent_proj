import asyncio
import json
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import structlog

logger = structlog.get_logger()

router = APIRouter()


class WebSocketManager:
    """Zarządza połączeniami WebSocket per skan."""

    def __init__(self):
        # scan_id -> lista WebSocket
        self._connections: dict[str, list[WebSocket]] = {}
        # scan_id -> plugin_name -> asyncio.Event (czekanie na CAPTCHA)
        self._captcha_events: dict[str, dict[str, asyncio.Event]] = {}
        # scan_id -> plugin_name -> odpowiedź CAPTCHA
        self._captcha_answers: dict[str, dict[str, str]] = {}

    async def connect(self, scan_id: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(scan_id, []).append(ws)
        logger.info("ws.connected", scan_id=scan_id)

    def disconnect(self, scan_id: str, ws: WebSocket):
        if scan_id in self._connections:
            self._connections[scan_id].discard(ws) if hasattr(self._connections[scan_id], 'discard') else None
            try:
                self._connections[scan_id].remove(ws)
            except ValueError:
                pass
        logger.info("ws.disconnected", scan_id=scan_id)

    async def broadcast(self, scan_id: str, message: dict):
        conns = self._connections.get(scan_id, [])
        dead = []
        payload = json.dumps(message, default=str)
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(scan_id, ws)

    async def wait_for_captcha(self, scan_id: str, plugin_name: str, timeout: int = 120) -> Optional[str]:
        """Czekaj na odpowiedź CAPTCHA z frontendu. Zwraca None po timeout."""
        event = asyncio.Event()
        self._captcha_events.setdefault(scan_id, {})[plugin_name] = event
        self._captcha_answers.setdefault(scan_id, {})

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._captcha_answers[scan_id].get(plugin_name)
        except asyncio.TimeoutError:
            return None
        finally:
            self._captcha_events.get(scan_id, {}).pop(plugin_name, None)
            self._captcha_answers.get(scan_id, {}).pop(plugin_name, None)

    def submit_captcha(self, scan_id: str, plugin_name: str, answer: str):
        """Przyjmij odpowiedź CAPTCHA od frontendu."""
        self._captcha_answers.setdefault(scan_id, {})[plugin_name] = answer
        event = self._captcha_events.get(scan_id, {}).get(plugin_name)
        if event:
            event.set()


ws_manager = WebSocketManager()


@router.websocket("/ws/scan/{scan_id}")
async def websocket_endpoint(websocket: WebSocket, scan_id: str):
    await ws_manager.connect(scan_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "captcha_response":
                    ws_manager.submit_captcha(
                        scan_id,
                        msg["source"],
                        msg["answer"]
                    )
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(scan_id, websocket)
