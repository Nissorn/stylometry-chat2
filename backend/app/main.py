from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from typing import Optional, Dict

import httpx
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .auth import router as auth_router
from .chat import router as chat_router
from .crypto import decrypt, encrypt
from .database import engine, get_db
from .routers.auth_webauthn import router as webauthn_router
from .ws_manager import manager

# ---------------------------------------------------------------------------
# Schema + lightweight migration
# ---------------------------------------------------------------------------
models.Base.metadata.create_all(bind=engine)


def _run_migrations() -> None:
    """Add new columns to the users table when they don't exist yet."""
    new_columns = [
        ("security_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("is_frozen", "BOOLEAN NOT NULL DEFAULT 0"),
    ]
    with engine.connect() as conn:
        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(users)"))
        }
        for col_name, col_def in new_columns:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                print(f"[MIGRATION] Added column users.{col_name}")

        # Best-effort cleanup for legacy PIN column.
        if "unlock_pin_hash" in existing_cols:
            try:
                conn.execute(text("ALTER TABLE users DROP COLUMN unlock_pin_hash"))
                print("[MIGRATION] Removed legacy users.unlock_pin_hash")
            except Exception:
                pass
        conn.commit()


_run_migrations()

# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------
app = FastAPI(title="Thai-Stylometry Ultimate App")

_raw_origins: str = (
    os.getenv("ALLOW_ORIGINS")
    or os.getenv("ALLOWED_ORIGINS")
    or "https://stylometry.nissorn.codes,http://localhost:5173,https://localhost:5173"
).strip()

if _raw_origins == "*":
    _allow_origins: list[str] = ["*"]
    _allow_credentials: bool = False
else:
    _allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    _allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(webauthn_router, prefix="/auth/webauthn")
app.include_router(chat_router, prefix="/chats")


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


@app.get("/")
def read_root():
    return {"message": "Welcome to Thai-Stylometry Ultimate API"}


ML_SERVICE_URL = "http://stylometry-ml-service:8001/predict"
WS_MAX_MSGS_PER_SECOND = 5
WS_MAX_MESSAGE_LENGTH = 500


# ---------------------------------------------------------------------------
# WebSocket Chat Endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat/{chat_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: int,
    token: Optional[str] = None,
    db: Session = Depends(get_db),
):
    await websocket.accept()

    if not token:
        print("[WS] Connection closed — missing token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── JWT Validation ──────────────────────────────────────────────────────
    try:
        jwt_payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = jwt_payload.get("sub")
        if username is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── Frozen Check ────────────────────────────────────────────────────────
    if user.is_frozen:
        print(f"[WS] Rejecting connection — user '{username}' is frozen")
        await websocket.close(code=4001)
        return

    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == user.id,
        )
        .first()
    )
    if not member:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── Session State ────────────────────────────────────────────────────────
    trust_score = manager.get_user_trust_score(username)

    # INITIAL SYNC: Send the current trust score to the client immediately
    await websocket.send_json(
        {
            "type": "trust_update",
            "trust_score": float(round(trust_score, 2)),
            "confidence": 1.0,
            "status": "active",
            "message": f"Global session restored: {trust_score:.1f}%",
        }
    )

    # msg_buffer starts empty for every new WebSocket connection
    msg_buffer: deque[str] = deque(maxlen=5)
    inbound_timestamps: deque[float] = deque()
    print(
        f"[WS] Session started for '{username}' in chat {chat_id} — "
        f"buffer initialized empty."
    )

    # Register with the shared connection manager
    await manager.connect(chat_id, username, websocket)

    try:
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    payload_txt = await websocket.receive_text()
                    now = asyncio.get_running_loop().time()
                    while inbound_timestamps and (now - inbound_timestamps[0]) > 1.0:
                        inbound_timestamps.popleft()
                    if len(inbound_timestamps) >= WS_MAX_MSGS_PER_SECOND:
                        await websocket.send_json(
                            {
                                "type": "rate_limit",
                                "message": "Rate limit exceeded: max 5 messages per second.",
                            }
                        )
                        continue
                    inbound_timestamps.append(now)

                    data = json.loads(payload_txt)
                    payload = schemas.WebSocketChatPayload.model_validate(data)

                    clean_text = payload.message
                    if len(clean_text) > WS_MAX_MESSAGE_LENGTH:
                        await websocket.send_json(
                            {
                                "type": "validation_error",
                                "message": "Message too long (max 500 characters).",
                            }
                        )
                        continue

                    enforce_security: bool = payload.enforce_security
                    message_timestamp: Optional[str] = None

                    if len(clean_text) > 0:
                        msg_buffer.append(clean_text)

                        new_msg = models.Message(
                            chat_id=chat_id,
                            sender_id=user.id,
                            text=clean_text,
                        )
                        db.add(new_msg)
                        db.commit()
                        message_timestamp = (
                            new_msg.timestamp.isoformat() if new_msg.timestamp else None
                        )

                        # ── Baseline Auto-Collection ─────────────────────────
                        if trust_score > 90.0:
                            data_dir = "/ml_workspace/data"
                            try:
                                os.makedirs(data_dir, exist_ok=True)
                                baseline_path = os.path.join(
                                    data_dir, f"{username}_baseline.txt"
                                )
                                ciphertext_line = encrypt(clean_text)
                                with open(baseline_path, "a", encoding="utf-8") as f:
                                    f.write(ciphertext_line + "\n")

                                with open(baseline_path, "r", encoding="utf-8") as f:
                                    line_count = sum(1 for ln in f if ln.strip())

                                if line_count == 50 or (
                                    line_count > 50 and line_count % 10 == 0
                                ):
                                    asyncio.create_task(
                                        client.post(
                                            f"http://stylometry-ml-service:8001/train/{username}",
                                            timeout=30.0,
                                        )
                                    )
                            except Exception as exc:
                                print(f"[WS] Baseline write failed: {exc}")

                    # ── ML Evaluation ────────────────────────────────────────
                    if len(msg_buffer) >= 1:
                        if not enforce_security:
                            trust_score = 100.0
                            await websocket.send_json(
                                {
                                    "type": "trust_update",
                                    "trust_score": 100.0,
                                    "confidence": 1.0,
                                    "status": "inactive",
                                    "message": "Status: Monitoring Disabled",
                                }
                            )
                            await manager.broadcast(
                                chat_id,
                                {
                                    "type": "chat",
                                    "chat_id": chat_id,
                                    "sender": username,
                                    "message": clean_text,
                                    "text": clean_text,
                                    "timestamp": message_timestamp,
                                    "trust_score": round(trust_score, 2),
                                    "is_broadcast": True,
                                },
                            )
                            continue

                        try:
                            ml_payload = {
                                "username": username,
                                "messages": list(msg_buffer),
                            }
                            response = await client.post(
                                ML_SERVICE_URL, json=ml_payload, timeout=5.0
                            )

                            if response.status_code == 200:
                                ml_data = response.json()
                                latest_score = float(ml_data.get("latest_score", ml_data.get("confidence_score", 1.0)))
                                average_score = float(ml_data.get("average_score", 1.0))
                                status_msg = ml_data.get("status", "active")

                                if status_msg == "cold_start":
                                    await websocket.send_json(
                                        {
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(latest_score, 4)),
                                            "status": "cold_start",
                                            "message": "Collecting baseline data...",
                                        }
                                    )
                                    await manager.broadcast(
                                        chat_id,
                                        {
                                            "type": "chat",
                                            "chat_id": chat_id,
                                            "sender": username,
                                            "message": clean_text,
                                            "text": clean_text,
                                            "timestamp": message_timestamp,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        },
                                    )
                                else:
                                    # ── ACTIVE — 3-Zone Trust Logic ──────────
                                    score = latest_score
                                    if score < 0.55:
                                        penalty = 25.0
                                        trust_score = max(0.0, trust_score - penalty)
                                    elif score <= 0.85:
                                        pass  # Neutral zone
                                    else:
                                        trust_score = min(100.0, trust_score + 5.0)

                                    manager.update_user_trust_score(username, trust_score)

                                    await websocket.send_json(
                                        {
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(latest_score, 4)),
                                            "average_score": float(round(average_score, 4)),
                                            "status": "active",
                                        }
                                    )

                                    # Session freeze check
                                    if trust_score < 40.0:
                                        db.refresh(user)
                                        user.is_frozen = True
                                        db.commit()
                                        manager.set_pending_messages(username, list(msg_buffer)[-5:])
                                        manager.lock(username)
                                        print(f"[WS] Session locked for '{username}' (trust={trust_score})")
                                        await websocket.close(code=4001)
                                        break

                                    await manager.broadcast(
                                        chat_id,
                                        {
                                            "type": "chat",
                                            "chat_id": chat_id,
                                            "sender": username,
                                            "message": clean_text,
                                            "text": clean_text,
                                            "timestamp": message_timestamp,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        },
                                    )
                        except Exception as exc:
                            print(f"[WS] ML evaluation failed: {exc}")
                            # Fallback broadcast
                            await manager.broadcast(
                                chat_id,
                                {
                                    "type": "chat",
                                    "chat_id": chat_id,
                                    "sender": username,
                                    "message": clean_text,
                                    "text": clean_text,
                                    "timestamp": message_timestamp,
                                    "trust_score": round(trust_score, 2),
                                    "is_broadcast": True,
                                },
                            )

                except WebSocketDisconnect:
                    break
                except ValidationError as exc:
                    await websocket.send_json(
                        {
                            "type": "validation_error",
                            "message": "Invalid message payload.",
                            "detail": str(exc),
                        }
                    )
                    continue
                except Exception as e:
                    print(f"[WS] Loop error: {e}")
                    break
    finally:
        manager.disconnect(chat_id, username)
