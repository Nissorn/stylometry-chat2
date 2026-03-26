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
        # Global state: { username: trust_score }
        self.user_trust_scores: Dict[str, float] = {}

        # Session state machine: "ACTIVE" | "LOCKED"
        self.user_states: Dict[str, str] = {}

        # Holds pending suspicious messages for post-freeze review.
        self.pending_messages: Dict[str, List[str]] = {}

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

    # ------------------------------------------------------------------
    # Global Trust State
    # ------------------------------------------------------------------

    def get_user_trust_score(self, username: str) -> float:
        """Return the global trust score for *username*, defaulting to 100.0."""
        return self.user_trust_scores.get(username, 100.0)

    def update_user_trust_score(self, username: str, score: float) -> None:
        """Update the global trust score for *username*."""
        self.user_trust_scores[username] = score
        print(f"[WS] Global trust update for {username} → {score:.2f}")

    def reset_user_trust_score(self, username: str) -> None:
        """Reset the global trust score for *username* to 100.0."""
        self.user_trust_scores[username] = 100.0
        print(f"[WS] Global trust RESET for {username} → 100.00")

    def lock(self, username: str) -> None:
        """Freeze the session in-memory."""
        self.user_states[username] = "LOCKED"
        print(f"DEBUG: Session LOCKED — {username}")

    def unlock(self, username: str) -> None:
        """Restore the session in-memory."""
        self.user_states[username] = "ACTIVE"
        self.pending_messages.pop(username, None)
        print(f"DEBUG: Session UNLOCKED — {username}")

    def set_pending_messages(self, username: str, messages: List[str]) -> None:
        """Persist the latest suspicious messages for explicit user confirmation."""
        self.pending_messages[username] = [m for m in messages if str(m).strip()]

    def get_pending_messages(self, username: str) -> List[str]:
        """Return pending suspicious messages captured before session freeze."""
        return list(self.pending_messages.get(username, []))

    def clear_pending_messages(self, username: str) -> None:
        """Clear any pending suspicious messages once review is complete."""
        self.pending_messages.pop(username, None)

    def __repr__(self) -> str:  # pragma: no cover
        summary = {cid: list(users) for cid, users in self.active_rooms.items()}
        return f"<ConnectionManager rooms={summary}>"


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere you need WS access
# ---------------------------------------------------------------------------
manager = ConnectionManager()
