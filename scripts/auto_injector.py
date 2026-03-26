#!/usr/bin/env python3
"""
auto_injector.py — Stylometry Test Injector (Ultimate Version)
=============================================================
Automatically authenticates, discovers a valid chat target, and injects
"good" and/or "impostor" messages into the stylometry system via WebSocket.

Optimized for testing PIN/Freeze security:
- Can register a 6-digit PIN before connecting.
- Automatically responds to auth_challenge (PIN) and require_confirmation frames.
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
# Paths to bundled message corpora
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_GOOD_MSG_FILE = os.path.join(_SCRIPT_DIR, "data", "good_messages.txt")
_GOOD_MSG_FILE2 = os.path.join(_SCRIPT_DIR, "data", "good_messages2.txt")
_IMPOSTOR_FILE = os.path.join(_SCRIPT_DIR, "data", "impostor_messages.txt")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        print(f"  [WARN] File not found, skipping: {path}")
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip()]

def _build_message_queue(mode: str, count: int) -> list[dict]:
    good_lines: list[str] = []
    for path in (_GOOD_MSG_FILE, _GOOD_MSG_FILE2):
        good_lines.extend(_load_lines(path))
    impostor_lines = _load_lines(_IMPOSTOR_FILE)

    if mode == "good":
        pool = [{"text": t, "label": "good"} for t in good_lines]
    elif mode == "impostor":
        pool = [{"text": t, "label": "impostor"} for t in impostor_lines]
    else:  # "both" — interleave 3 good, 1 impostor
        good_tagged = [{"text": t, "label": "good"} for t in good_lines]
        imp_tagged = [{"text": t, "label": "impostor"} for t in impostor_lines]
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
        print("[ERROR] No messages available to inject.")
        sys.exit(1)
    if count and count > 0:
        pool = pool[:count]
    return pool

async def _fetch_security_status(api_base: str, token: str) -> bool:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{api_base}/auth/me", headers=headers, timeout=5.0)
            if resp.status_code == 200:
                return resp.json().get("security_enabled", False)
        except Exception:
             pass
    return False

async def _enable_security_rest(api_base: str, token: str, pin: str):
    url = f"{api_base}/auth/security/enable"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        print(f"[SECURITY] Registering step-up PIN at {url} …")
        resp = await client.post(url, json={"pin": pin}, headers=headers, timeout=10.0)
        if resp.ok:
            print(f"[SECURITY] ✅ Security Mode enabled.")
        else:
            print(f"[SECURITY] ❌ Failed to enable: {resp.text}")
            sys.exit(1)

async def _discover_chat(api_base: str, token: str, preferred_id: Optional[int]) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{api_base}/chats/me", headers=headers, timeout=10.0)
    
    if resp.status_code != 200:
        print(f"[ERROR] Chat discovery failed: {resp.status_code}")
        sys.exit(1)
    
    chats = resp.json()
    if not chats:
        print("[ERROR] No chats found.")
        sys.exit(1)
    
    if preferred_id is not None:
        match = next((c for c in chats if c["id"] == preferred_id), None)
        if match: return match
        print(f"[ERROR] Chat {preferred_id} not found.")
        sys.exit(1)
    
    groups = [c for c in chats if c.get("is_group")]
    return groups[0] if groups else chats[0]

# ---------------------------------------------------------------------------
# WebSocket Injection Core
# ---------------------------------------------------------------------------

async def run_injector(
    token: str,
    api_base: str,
    chat_id: Optional[int],
    mode: str,
    count: int,
    pin: Optional[str],
    delay_range: tuple[float, float],
) -> None:
    # 1. Setup
    chat = await _discover_chat(api_base, token, chat_id)
    resolved_id = chat["id"]
    
    # Check/Enable Security
    security_on = await _fetch_security_status(api_base, token)
    if pin:
        await _enable_security_rest(api_base, token, pin)
        security_on = True

    print("=" * 60)
    print(f'  Target Chat : #{resolved_id}  "{chat.get("name", "Unnamed")}"')
    print(f"  Security    : {'ENABLED (will respond to PIN challenges)' if pin else 'DISABLED (hard-kick on trust drop)'}")
    print("=" * 60)

    queue = _build_message_queue(mode, count)
    
    ws_url = api_base.replace("http", "ws") + f"/ws/chat/{resolved_id}?token={token}"
    print(f"  Connecting to {ws_url} …")

    try:
        async with websockets.connect(ws_url) as ws:
            print("  ✓ Connected.\n")

            async def listener():
                try:
                    while True:
                        raw = await ws.recv()
                        data = json.loads(raw)
                        kind = data.get("type")

                        if kind == "trust_update":
                            trust = data.get("trust_score", 0)
                            st = data.get("status", "active")
                            bar = ("█" * (int(trust) // 5)).ljust(20)
                            color = "\033[92m" if trust > 80 else "\033[93m" if trust > 40 else "\033[91m"
                            print(f"  → [TRUST] {color}[{bar}]\033[0m {trust:>6.1f} | {st} {data.get('message','')}")
                        
                        elif kind == "auth_challenge":
                            print(f"  → [CHALLENGE] PIN Required.")
                            if pin:
                                await ws.send(json.dumps({"type": "verify_pin", "pin": pin}))
                                print(f"    [AUTO-REPLY] verify_pin sent.")
                            else:
                                print("    [WARN] No PIN provided to auto-injector.")

                        elif kind == "require_confirmation":
                            print(f"  → [CONFIRMATION] Required for: {data.get('pending_message')}")
                            await ws.send(json.dumps({"type": "confirm_message", "is_owner": True}))
                            print(f"    [AUTO-REPLY] confirm_message (True) sent.")

                        elif kind == "chat" or (data.get("sender") and data.get("message")):
                            sender = data.get("sender", "System")
                            text = data.get("message") or data.get("text", "")
                            print(f"  ← [{sender}] {text}")

                except ConnectionClosed as e:
                    print(f"\n  ✗ Disconnected. Code={e.code}")
                except Exception as e:
                    print(f"  [Error] Listener: {e}")

            listener_task = asyncio.create_task(listener())

            for i, item in enumerate(queue):
                payload = {
                    "message": item["text"],
                    "enforce_security": True if pin else False
                }
                print(f"  [{i+1}/{len(queue)}] Sending ({item['label']}): {item['text'][:60]}...")
                await ws.send(json.dumps(payload))
                await asyncio.sleep(random.uniform(*delay_range))

            await asyncio.sleep(5)
            listener_task.cancel()

    except Exception as e:
        print(f"  [Error] Injector: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--chat_id", type=int)
    parser.add_argument("--mode", choices=["good", "impostor", "both"], default="both")
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--pin", help="6-digit PIN for auto-responding to challenges")
    parser.add_argument("--api_base", default="http://localhost:8000")
    args = parser.parse_args()

    asyncio.run(run_injector(
        token=args.token,
        api_base=args.api_base.rstrip("/"),
        chat_id=args.chat_id,
        mode=args.mode,
        count=args.count,
        pin=args.pin,
        delay_range=(1.5, 3.5),
    ))

if __name__ == "__main__":
    main()
