"""The wrist buzzers' connection to this computer: a WebSocket on the local network. See CLUADE.md "Protocol".

  buzzer -> us : {"type":"hello","buzzer_id":"buzzer-maria","battery":0.82}   {"type":"ack","buzzer_id":...,"alert_id":...}   {"type":"ping"}
  us -> buzzer : {"type":"buzz","alert_id":"a_1042","severity":"high"}   {"type":"stop","alert_id":...,"owner":"Maria"}   {"type":"ping"}
Works with no internet: the buzzer only ever talks to this computer.
"""
import asyncio
import logging
import time
from typing import Callable

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("nestwatch.buzzers")
PING_EVERY_S = 5.0


class BuzzerHub:
    def __init__(self, on_ack: Callable[[str, str], None] | None = None):
        self.on_ack = on_ack
        self._sockets: dict[str, WebSocket] = {}
        self.info: dict[str, dict] = {}                     # buzzer_id -> {"battery": float, "last_seen": monotonic}
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- called from the web server's event loop --------------------------------------------------------
    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        self._loop = asyncio.get_running_loop()
        buzzer_id = None
        pinger = None
        try:
            hello = await ws.receive_json()
            if hello.get("type") != "hello" or not str(hello.get("buzzer_id", "")).strip():
                await ws.close(code=1008)                  # the first message must introduce the buzzer
                return
            buzzer_id = str(hello["buzzer_id"])[:64]
            old = self._sockets.get(buzzer_id)
            self._sockets[buzzer_id] = ws
            self.info[buzzer_id] = {"battery": hello.get("battery"), "last_seen": time.monotonic()}
            log.info("buzzer %s connected (battery %s)", buzzer_id, hello.get("battery"))
            if old is not None:                            # a reconnect replaces the stale connection
                try:
                    await old.close()
                except Exception:
                    pass
            pinger = asyncio.create_task(self._ping_loop(ws))
            while True:
                msg = await ws.receive_json()
                self.info[buzzer_id]["last_seen"] = time.monotonic()
                kind = msg.get("type")
                if kind == "ack" and self.on_ack:
                    # trust the connection's own identity, not whatever the message claims
                    await asyncio.get_running_loop().run_in_executor(None, self.on_ack, buzzer_id, str(msg.get("alert_id", "")))
                elif kind == "ping":
                    await ws.send_json({"type": "pong"})
                elif kind == "hello":
                    self.info[buzzer_id]["battery"] = msg.get("battery")
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("buzzer connection error")
        finally:
            if pinger:
                pinger.cancel()
            if buzzer_id and self._sockets.get(buzzer_id) is ws:
                del self._sockets[buzzer_id]
                log.warning("buzzer %s disconnected", buzzer_id)

    async def _ping_loop(self, ws: WebSocket) -> None:
        while True:
            await asyncio.sleep(PING_EVERY_S)
            await ws.send_json({"type": "ping"})

    # ---- called from any thread -----------------------------------------------------------------------
    def connected(self) -> list[str]:
        return sorted(self._sockets)

    def send(self, buzzer_id: str, message: dict) -> bool:
        ws, loop = self._sockets.get(buzzer_id), self._loop
        if ws is None or loop is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json(message), loop).result(timeout=2.0)
            return True
        except Exception:
            log.warning("could not reach buzzer %s", buzzer_id)
            return False

    def broadcast(self, message: dict) -> int:
        return sum(self.send(b, message) for b in list(self._sockets))
