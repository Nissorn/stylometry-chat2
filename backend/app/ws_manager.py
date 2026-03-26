"""
ws_manager.py — Shared WebSocket Connection Manager
=====================================================
Extracted from main.py into its own module so that both main.py (which
registers the /ws endpoint) and chat.py (which needs to broadcast REST-triggered
events) can import the singleton without creating a circular import.

Usage:
    from .ws_manager import manager
    await manager.broadcast(chat_id, {"type": "group_updated", ...})
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    """
    Tracks all active WebSocket connections keyed by (chat_id → username → socket).

    Thread-safety note: FastAPI runs on a single-threaded asyncio event loop,
    so plain dict operations here are safe without locks.
    """

    def __init__(self) -> None:
        # { chat_id: { username: WebSocket } }
        self.active_rooms: Dict[int, Dict[str, WebSocket]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, chat_id: int, username: str, websocket: WebSocket) -> None:
        """Register a new WebSocket for *username* in *chat_id*."""
        if chat_id not in self.active_rooms:
            self.active_rooms[chat_id] = {}
        self.active_rooms[chat_id][username] = websocket
        print(
            f"[WS] {username} connected → room {chat_id}  "
            f"(room size: {len(self.active_rooms[chat_id])})"
        )

    def disconnect(self, chat_id: int, username: str) -> None:
        """Remove *username* from *chat_id*.  Cleans up empty rooms."""
        room = self.active_rooms.get(chat_id)
        if room is not None:
            room.pop(username, None)
            if not room:
                del self.active_rooms[chat_id]
        print(f"[WS] {username} disconnected ← room {chat_id}")

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, chat_id: int, payload: dict) -> None:
        """
        Send *payload* as JSON to every connected socket in *chat_id*.

        Dead sockets are silently pruned so a single bad connection can never
        block the broadcast loop for other recipients.
        """
        room = self.active_rooms.get(chat_id)
        if not room:
            return

        dead: List[str] = []
        for username, ws in list(room.items()):
            try:
                await ws.send_json(payload)
            except Exception as exc:
                print(f"[WS] Broadcast to {username} in room {chat_id} failed: {exc}")
                dead.append(username)

        for username in dead:
            room.pop(username, None)
        if chat_id in self.active_rooms and not self.active_rooms[chat_id]:
            del self.active_rooms[chat_id]

    async def broadcast_except(
        self, chat_id: int, exclude_username: str, payload: dict
    ) -> None:
        """Like :meth:`broadcast` but skips *exclude_username* (e.g. the sender)."""
        room = self.active_rooms.get(chat_id)
        if not room:
            return

        dead: List[str] = []
        for username, ws in list(room.items()):
            if username == exclude_username:
                continue
            try:
                await ws.send_json(payload)
            except Exception as exc:
                print(f"[WS] Broadcast to {username} in room {chat_id} failed: {exc}")
                dead.append(username)

        for username in dead:
            room.pop(username, None)

    # ------------------------------------------------------------------
    # Introspection helpers (useful for debugging / admin endpoints)
    # ------------------------------------------------------------------

    def room_members(self, chat_id: int) -> List[str]:
        """Return the list of usernames currently connected to *chat_id*."""
        return list(self.active_rooms.get(chat_id, {}).keys())

    def total_connections(self) -> int:
        """Return the total number of active WebSocket connections across all rooms."""
        return sum(len(room) for room in self.active_rooms.values())

    def __repr__(self) -> str:  # pragma: no cover
        summary = {cid: list(users) for cid, users in self.active_rooms.items()}
        return f"<ConnectionManager rooms={summary}>"


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere you need WS access
# ---------------------------------------------------------------------------
manager = ConnectionManager()
