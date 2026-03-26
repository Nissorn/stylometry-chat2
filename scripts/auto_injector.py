#!/usr/bin/env python3
"""
auto_injector.py — Stylometry Test Injector
============================================
Automatically authenticates, discovers a valid chat target, and injects
"good" and/or "gibberish" messages into the stylometry system via WebSocket.

Usage examples
--------------
# Inject both good + gibberish into the first available chat (security ON):
  python auto_injector.py --token <JWT>

# Inject only good messages, 20 of them, with security OFF:
  python auto_injector.py --token <JWT> --mode good --count 20

# Target a specific chat room:
  python auto_injector.py --token <JWT> --chat_id 3 --mode impostor

# Point at a remote Droplet:
  python auto_injector.py --token <JWT> --api_base http://your-droplet-ip:8000
"""

import argparse
import asyncio
import json
import os
import random
import sys
from typing import Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

# ---------------------------------------------------------------------------
# Paths to bundled message corpora (relative to this script's directory)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_GOOD_MSG_FILE = os.path.join(_SCRIPT_DIR, "data", "good_messages.txt")
_GOOD_MSG_FILE2 = os.path.join(_SCRIPT_DIR, "data", "good_messages2.txt")
_IMPOSTOR_FILE = os.path.join(_SCRIPT_DIR, "data", "impostor_messages.txt")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_lines(path: str) -> list[str]:
    """Load non-empty lines from *path*.  Returns [] if the file is missing."""
    if not os.path.exists(path):
        print(f"  [WARN] File not found, skipping: {path}")
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def _build_message_queue(mode: str, count: int) -> list[dict]:
    """
    Build a list of ``{"text": ..., "label": ...}`` dicts to inject.

    mode
        "good"     — only authentic-looking messages
        "impostor" — only gibberish / impostor messages
        "both"     — interleaved good then impostor (default)
    count
        Total number of messages to inject (0 = use all available).
    """
    good_lines: list[str] = []
    for path in (_GOOD_MSG_FILE, _GOOD_MSG_FILE2):
        good_lines.extend(_load_lines(path))

    impostor_lines = _load_lines(_IMPOSTOR_FILE)

    if mode == "good":
        pool = [{"text": t, "label": "good"} for t in good_lines]
    elif mode == "impostor":
        pool = [{"text": t, "label": "impostor"} for t in impostor_lines]
    else:  # "both" — interleave
        good_tagged = [{"text": t, "label": "good"} for t in good_lines]
        imp_tagged = [{"text": t, "label": "impostor"} for t in impostor_lines]
        # Interleave: 3 good, 1 impostor (mimics realistic drift testing)
        pool = []
        gi, ii = 0, 0
        while gi < len(good_tagged) or ii < len(imp_tagged):
            for _ in range(3):
                if gi < len(good_tagged):
                    pool.append(good_tagged[gi])
                    gi += 1
            if ii < len(imp_tagged):
                pool.append(imp_tagged[ii])
                ii += 1

    if not pool:
        print("[ERROR] No messages available to inject.  Check the data/ directory.")
        sys.exit(1)

    if count and count > 0:
        pool = pool[:count]

    return pool


def _ws_url(api_base: str, chat_id: int, token: str) -> str:
    """Convert an HTTP base URL to a WebSocket chat URL."""
    ws_base = api_base.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_base}/ws/chat/{chat_id}?token={token}"


# ---------------------------------------------------------------------------
# REST helpers (sync-over-async via httpx)
# ---------------------------------------------------------------------------


async def _discover_chat(
    api_base: str, token: str, preferred_id: Optional[int]
) -> dict:
    """
    Fetch the user's chat list and return a suitable target.

    If *preferred_id* is given, verify that chat exists and the user is a member.
    Otherwise, pick the first available chat (group preferred over DM).
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{api_base}/chats/me", headers=headers, timeout=10.0)

    if resp.status_code == 401:
        print("[ERROR] Token is invalid or expired.  Please log in again.")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"[ERROR] GET /chats/me returned {resp.status_code}: {resp.text}")
        sys.exit(1)

    chats: list[dict] = resp.json()
    if not chats:
        print(
            "[ERROR] No chats found for this user.\n"
            "        Create a Direct Message or Group Chat via the frontend first."
        )
        sys.exit(1)

    if preferred_id is not None:
        match = next((c for c in chats if c["id"] == preferred_id), None)
        if match is None:
            print(
                f"[ERROR] Chat ID {preferred_id} not found or you are not a member.\n"
                f"        Available IDs: {[c['id'] for c in chats]}"
            )
            sys.exit(1)
        return match

    # Prefer group chats (more interesting for multi-user testing)
    groups = [c for c in chats if c.get("is_group")]
    target = groups[0] if groups else chats[0]
    return target


async def _fetch_security_status(api_base: str, token: str) -> bool:
    """
    Fetch the user's current security_enabled status from the backend.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{api_base}/auth/me", headers=headers, timeout=10.0)

    if resp.status_code != 200:
        print(f"  [WARN] Failed to fetch security status (HTTP {resp.status_code}). Defaulting to OFF.")
        return False

    data = resp.json()
    return data.get("security_enabled", False)


# ---------------------------------------------------------------------------
# WebSocket injection core
# ---------------------------------------------------------------------------


async def run_injector(
    token: str,
    api_base: str,
    chat_id: Optional[int],
    mode: str,
    count: int,
    delay_min: float,
    delay_max: float,
) -> None:
    # ── 1. Discover target chat & Security status ──────────────────────────
    chat = await _discover_chat(api_base, token, chat_id)
    resolved_id = chat["id"]
    chat_type = "Group" if chat.get("is_group") else "DM"
    member_names = [m["username"] for m in chat.get("members", [])]

    # Fetch real security status from DB
    security_on = await _fetch_security_status(api_base, token)

    print("=" * 60)
    chat_name = chat.get("name", "(unnamed)")
    print(f'  Target Chat : #{resolved_id}  [{chat_type}]  "{chat_name}"')
    print(f"  Members     : {', '.join(member_names)}")
    print(f"  Mode        : {mode.upper()}")
    print(
        f"  Security    : {f'ON  ← Active Protection' if security_on else 'OFF ← data collection mode'}"
    )
    print(f"  Delay range : {delay_min}s – {delay_max}s per message")
    print("=" * 60)

    # ── 2. Build message queue ───────────────────────────────────────────────
    queue = _build_message_queue(mode, count)
    print(f"  Loaded {len(queue)} messages to inject.\n")

    # ── 3. Connect to WebSocket ──────────────────────────────────────────────
    uri = _ws_url(api_base, resolved_id, token)
    print(f"  Connecting to {uri} …")

    try:
        async with websockets.connect(uri) as ws:
            print("  ✓ WebSocket connected.\n")

            # ── Background listener task ─────────────────────────────────────
            async def _listener() -> None:
                try:
                    while True:
                        raw = await ws.recv()
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            print(f"  [RAW] {raw}")
                            continue

                        kind = data.get("type", "")
                        if kind == "trust_update":
                            trust = data.get("trust_score", "N/A")
                            conf = data.get("confidence", "N/A")
                            st = data.get("status", "?")
                            srv_msg = data.get("message", "")
                            bar_val = (
                                int(float(trust))
                                if isinstance(trust, (int, float))
                                else 0
                            )
                            bar = ("█" * (bar_val // 5)).ljust(20)
                            color = (
                                "\033[92m"
                                if bar_val > 80  # green
                                else "\033[93m"
                                if bar_val > 40  # yellow
                                else "\033[91m"  # red
                            )
                            print(
                                f"  → [TRUST] {color}[{bar}]\033[0m "
                                f"{trust:>6} | conf={conf} | {st} {srv_msg}"
                            )
                            if st == "locked" or data.get("type") == "error":
                                print("  ⚠  Session locked by server.")

                        elif kind == "chat":
                            sender = data.get("sender", "?")
                            text = data.get("message") or data.get("text", "")
                            echo_marker = " ← (echo)" if sender == "_self_" else ""
                            print(f"  ← [CHAT from {sender}] {text}{echo_marker}")

                        elif kind == "group_updated":
                            members = [m["username"] for m in data.get("members", [])]
                            print(f"  ← [GROUP_UPDATED] Members: {', '.join(members)}")

                        else:
                            print(f"  ← [MSG] {data}")

                except ConnectionClosed as exc:
                    print(
                        f"\n  ✗ Connection closed. Code={exc.code}  Reason={exc.reason}"
                    )
                except Exception as exc:
                    print(f"  [LISTENER ERROR] {exc}")

            listener_task = asyncio.create_task(_listener())

            # ── Inject messages ──────────────────────────────────────────────
            for i, item in enumerate(queue, start=1):
                text = item["text"]
                label = item["label"]

                payload = {
                    "message": text,
                    "enforce_security": security_on,
                }

                label_badge = (
                    "\033[92m[GOOD]\033[0m    "
                    if label == "good"
                    else "\033[91m[IMPOSTOR]\033[0m"
                )
                print(
                    f"  [{i:>3}/{len(queue)}] {label_badge} {text[:72]}{'…' if len(text) > 72 else ''}"
                )

                await ws.send(json.dumps(payload))

                delay = random.uniform(delay_min, delay_max)
                await asyncio.sleep(delay)

            # Give the server and listener time to flush final trust updates
            print("\n  ✓ All messages sent.  Waiting 8 s for final server replies…")
            await asyncio.sleep(8)
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass

    except ConnectionRefusedError:
        print(f"  [ERROR] Could not connect to {uri}.\n  Is the backend running?")
        sys.exit(1)
    except Exception as exc:
        print(f"  [ERROR] Injector failed: {exc}")
        raise


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stylometry Auto-Injector — inject test messages via WebSocket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Authentication
    parser.add_argument(
        "--token",
        required=True,
        help="JWT access token obtained from POST /auth/login",
    )

    # Target selection
    parser.add_argument(
        "--chat_id",
        type=int,
        default=None,
        help="Target chat room ID.  Auto-discovered if omitted (first group, then DM).",
    )

    # Message selection
    parser.add_argument(
        "--mode",
        choices=["good", "impostor", "both"],
        default="both",
        help=(
            "Which messages to inject: 'good' (authentic-style), "
            "'impostor' (gibberish), or 'both' (interleaved 3:1).  Default: both."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of messages to inject (0 = all available).  Default: 0.",
    )

    # Timing
    parser.add_argument(
        "--delay_min",
        type=float,
        default=1.5,
        help="Minimum seconds between messages.  Default: 1.5",
    )
    parser.add_argument(
        "--delay_max",
        type=float,
        default=3.5,
        help="Maximum seconds between messages.  Default: 3.5",
    )


    # Backend address
    parser.add_argument(
        "--api_base",
        default=os.getenv("VITE_API_BASE", "http://localhost:8000")
        .replace("ws://", "http://")
        .replace("wss://", "https://"),
        help="HTTP base URL of the backend.  Default: http://localhost:8000",
    )

    args = parser.parse_args()

    asyncio.run(
        run_injector(
            token=args.token,
            api_base=args.api_base.rstrip("/"),
            chat_id=args.chat_id,
            mode=args.mode,
            count=args.count, # Ensured 'count' is passed correctly
            delay_min=args.delay_min,
            delay_max=args.delay_max,
        )
    )


if __name__ == "__main__":
    main()
