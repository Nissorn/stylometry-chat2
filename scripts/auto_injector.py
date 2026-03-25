import argparse
import asyncio
import json
import random
import urllib.error
import urllib.request

import websockets
from typing import Optional

# ---------------------------------------------------------------------------
# REST helper — enable step-up security before opening the WebSocket
# ---------------------------------------------------------------------------


def enable_security_rest(token: str, pin: str) -> None:
    """Call POST /auth/security/enable synchronously.

    Registers the 6-digit PIN with the backend so the WebSocket engine will
    issue a step-up challenge instead of a hard kick when trust drops below
    the lockout threshold.

    Raises SystemExit(1) on any failure so the injector never starts a
    session that cannot respond to an auth_challenge correctly.
    """
    url = "http://localhost:8000/auth/security/enable"
    body = json.dumps({"pin": pin}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    print(f"[SECURITY] Registering step-up PIN at {url} …")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            print(f"[SECURITY] ✅ Security Mode enabled — server replied: {raw}")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(
            f"[SECURITY] ❌ Failed to enable Security Mode: "
            f"HTTP {exc.code} — {body_text}"
        )
        raise SystemExit(1)
    except Exception as exc:
        print(f"[SECURITY] ❌ Could not reach backend: {exc}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Main injector coroutine
# ---------------------------------------------------------------------------


async def run_injector(
    token: str,
    file_path: str,
    count: int,
    security_on: bool,
    pin: Optional[str],
) -> None:
    uri = f"ws://localhost:8000/ws/chat?token={token}"

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    messages_to_send = lines[:count] if count > 0 else lines

    if not messages_to_send:
        print(f"No messages found in {file_path}. Exiting.")
        return

    print(f"Loaded {len(messages_to_send)} messages from {file_path}.")

    # ── Step-Up Auth pre-flight ────────────────────────────────────────────
    # If security enforcement is on AND a PIN was provided, register it with
    # the REST API *before* opening the WebSocket.  This mirrors the real
    # user flow (click "Enable Security Mode" → then chat).
    if security_on:
        if not pin:
            print(
                "[SECURITY] ❌ --security_on requires --pin. "
                "Provide a 6-digit PIN so the injector can respond to auth_challenge."
            )
            raise SystemExit(1)
        enable_security_rest(token, pin)

    # ── WebSocket session ──────────────────────────────────────────────────
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Successfully connected to {uri}")

            # ── Background listener ────────────────────────────────────────
            async def listener() -> None:
                try:
                    while True:
                        raw = await websocket.recv()
                        data = json.loads(raw)
                        msg_type = data.get("type", "")

                        if msg_type == "trust_update":
                            status_val = data.get("status", "unknown")
                            trust = data.get("trust_score", "N/A")
                            conf = data.get("confidence", "N/A")
                            server_msg = data.get("message", "")
                            print(
                                f"--> [TRUST] score={trust} | conf={conf} | "
                                f"status={status_val} | {server_msg}"
                            )

                        elif msg_type == "chat":
                            sender = data.get("sender", "?")
                            text = data.get("message") or data.get("text", "")
                            print(f"    [CHAT from {sender}] {text}")

                        elif msg_type == "auth_challenge":
                            # ── Auto step-up response ──────────────────────
                            challenge_msg = data.get("message", "")
                            print(f"--> [AUTH_CHALLENGE] {challenge_msg}")

                            if pin:
                                reply = json.dumps({"type": "verify_pin", "pin": pin})
                                print(f"    [AUTO-REPLY] Sending verify_pin …")
                                await websocket.send(reply)
                            else:
                                print(
                                    "    [AUTO-REPLY] ⚠️  No --pin supplied; "
                                    "cannot respond to auth_challenge. Session will remain frozen."
                                )

                        elif msg_type == "auth_success":
                            print(f"--> [AUTH_SUCCESS] {data.get('message', '')}")

                        elif msg_type == "system_alert":
                            clear = data.get("clear", False)
                            alert_msg = data.get("message", "")
                            if clear:
                                print(f"--> [SYSTEM_ALERT CLEARED] {alert_msg}")
                            else:
                                print(f"--> [SYSTEM_ALERT] {alert_msg}")

                        else:
                            # Unknown / legacy frame — print raw for debugging
                            if (
                                data.get("type") == "error"
                                or data.get("status") == "locked"
                            ):
                                print(f"--> [SERVER] Session locked / error: {data}")
                            else:
                                print(f"--> [SERVER] {data}")

                except websockets.exceptions.ConnectionClosed as exc:
                    print(
                        f"\nConnection closed — code: {exc.code}, reason: {exc.reason}"
                    )
                except Exception as exc:
                    print(f"Listener error: {exc}")

            listener_task = asyncio.create_task(listener())

            # ── Send messages ──────────────────────────────────────────────
            for i, text in enumerate(messages_to_send):
                payload = {
                    "message": text,
                    "enforce_security": security_on,
                }
                print(f"\n[{i + 1}/{len(messages_to_send)}] Sending: {text}")
                await websocket.send(json.dumps(payload))

                delay = random.uniform(1.5, 3.5)
                await asyncio.sleep(delay)

            print(
                "\nFinished sending messages. "
                "Keeping connection open for 10 s to catch final replies…"
            )
            await asyncio.sleep(10)
            listener_task.cancel()

    except ConnectionRefusedError:
        print(f"Failed to connect to {uri}. Is the backend running?")
    except Exception as exc:
        print(f"Injector error: {exc}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stylometry Auto-Injector — sends messages over WebSocket and "
        "optionally enables Step-Up Auth (Secondary PIN) before connecting.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--token",
        required=True,
        help="JWT Bearer token for WebSocket authentication.",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to a text file whose lines are injected as chat messages.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of messages to inject (0 = all lines in the file).",
    )
    parser.add_argument(
        "--security_on",
        action="store_true",
        help=(
            "Set enforce_security=True in each payload AND call "
            "POST /auth/security/enable before connecting. "
            "Requires --pin."
        ),
    )
    parser.add_argument(
        "--pin",
        default=None,
        help=(
            "6-digit numeric PIN used for step-up authentication. "
            "Required when --security_on is set. "
            "Also used to auto-reply to auth_challenge frames."
        ),
    )

    args = parser.parse_args()

    # Validate PIN format early — fail loudly before any network call
    if args.pin is not None:
        if not args.pin.isdigit() or len(args.pin) != 6:
            parser.error("--pin must be exactly 6 numeric digits (e.g. 123456).")

    asyncio.run(
        run_injector(
            token=args.token,
            file_path=args.file,
            count=args.count,
            security_on=args.security_on,
            pin=args.pin,
        )
    )
