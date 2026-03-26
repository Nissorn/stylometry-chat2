from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from sqlalchemy.orm import Session

from . import auth, models
from .auth import router as auth_router
from .chat import router as chat_router
from .crypto import decrypt, encrypt
from .database import engine, get_db
from .ws_manager import manager  # shared singleton — also used by chat.py

# ---------------------------------------------------------------------------
# DB Bootstrap
# ---------------------------------------------------------------------------
models.Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------
app = FastAPI(title="Thai-Stylometry Auth API")

# ---------------------------------------------------------------------------
# CORS — configurable via environment variable for production deployments.
#
# Set ALLOWED_ORIGINS to a comma-separated list of origins, e.g.:
#   ALLOWED_ORIGINS=http://your-droplet-ip:5173,https://yourdomain.com
#
# Falls back to "*" (allow all) when the variable is absent so that local
# development stays zero-config.  In production you SHOULD set this to the
# exact frontend origin(s) and also set allow_credentials=True.
# ---------------------------------------------------------------------------
_raw_origins: str = os.getenv("ALLOWED_ORIGINS", "*").strip()

if _raw_origins == "*":
    _allow_origins: list[str] = ["*"]
    _allow_credentials: bool = False  # credentials not allowed with wildcard
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
app.include_router(chat_router, prefix="/chats")


@app.get("/")
def read_root():
    return {"message": "Welcome to Thai-Stylometry API"}


ML_SERVICE_URL = "http://stylometry-ml-service:8001/predict"


# ---------------------------------------------------------------------------
# WebSocket Chat Endpoint
# ---------------------------------------------------------------------------
# Phase 5: Train on Demand & Predict Per User
# - [x] Analyze ML Workspace & Data Pipelines
# - [x] Redesign Architecture for "Train on Demand" (Approved)
# - [x] Mount ML Workspace via `docker-compose.yml`
# - [x] Implement `POST /train/{username}` endpoint (Dummy Orchestration)
# - [x] Implement `POST /predict` endpoint (Cold Start Logic)
# - [x] Update Backend socket hooks to respect `cold_start` and `active` status
#
# Phase 6: Real Model Integration & Auto-Data Collection
# - [x] Backend: Write messages securely to `/ml_workspace/data/{username}_baseline.txt`
# - [x] Svelte: Add "Security Enforcement" Toggle to Navbar and transmit states
# - [x] ML Service: Implement Stylometric Meta Features `StylometricFeatureExtractor`
# - [x] ML Logic: Upgrade to `XGBClassifier`, refine Trust Score Penalty
#
# Phase 7: Multi-User Chat + Encryption at Rest
# - [x] ConnectionManager: broadcast authenticated messages to all users
# - [x] Fernet AES-128: encrypt baseline messages on disk, decrypt in buffer pre-fill
# - [x] Architect safeguards: finally-block disconnect, plaintext-first predict
#
# Phase 8: Production Hardening
# - [x] ConnectionManager extracted to ws_manager.py (no circular imports)
# - [x] CORS origins from ALLOWED_ORIGINS env var
# - [x] JWT_SECRET_KEY / ENCRYPTION_KEY fail-fast on startup
# - [x] group_updated broadcast from chat.py REST endpoints
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
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            print("[WS] Connection closed — JWT missing 'sub' claim")
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return
    except Exception as exc:
        print(f"[WS] Token validation failed: {exc}")
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        print(f"[WS] Connection closed — user '{username}' not found in DB")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
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
        print(
            f"[WS] Connection closed — user '{username}' is not a member of chat {chat_id}"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── Session State ────────────────────────────────────────────────────────
    trust_score = manager.get_user_trust_score(username)

    # INITIAL SYNC: Send the current trust score to the client immediately
    # to avoid UI desync on room switch or hard refresh.
    await websocket.send_json(
        {
            "type": "trust_update",
            "trust_score": float(round(trust_score, 2)),
            "confidence": 1.0, # default until first message
            "status": "active",
            "message": f"Global session restored: {trust_score:.1f}%",
        }
    )

    # msg_buffer starts empty for every new WebSocket connection to ensure
    # individual message evaluation is not camouflaged by past messages.
    msg_buffer: deque[str] = deque(maxlen=5)
    print(
        f"[WS] Session started for '{username}' in chat {chat_id} — "
        f"buffer initialized empty."
    )

    # Register with the shared connection manager.
    # The finally block guarantees cleanup even on unhandled exceptions or
    # forced client disconnects.
    await manager.connect(chat_id, username, websocket)

    try:
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    payload_txt = await websocket.receive_text()
                    print(f"[WS] Raw received from '{username}': {payload_txt}")

                    try:
                        data = json.loads(payload_txt)
                        if not isinstance(data, dict):
                            data = {
                                "message": str(payload_txt),
                                "enforce_security": False,
                            }
                    except Exception:
                        data = {"message": str(payload_txt), "enforce_security": False}

                    text: str = str(data.get("message", ""))
                    enforce_security: bool = bool(data.get("enforce_security", False))
                    clean_text = text.strip()

                    # ── Persist message to DB & update stylometry buffer ─────
                    if len(clean_text) > 0:
                        msg_buffer.append(clean_text)

                        new_msg = models.Message(
                            chat_id=chat_id,
                            sender_id=user.id,
                            text=clean_text,
                        )
                        db.add(new_msg)
                        db.commit()

                        # ── Baseline Auto-Collection (THE SACRED RULE) ───────
                        # Every message from this user is appended to their
                        # baseline file regardless of chat type (DM or Group).
                        # The trust_score > 90 gate ensures only high-confidence
                        # authentic messages are used for ML training, preserving
                        # dataset quality while honoring the "all chat types" rule.
                        if trust_score > 90.0:
                            data_dir = "/ml_workspace/data"
                            try:
                                os.makedirs(data_dir, exist_ok=True)
                                baseline_path = os.path.join(
                                    data_dir, f"{username}_baseline.txt"
                                )

                                # Encrypt AFTER predict, BEFORE writing to disk
                                ciphertext_line = encrypt(clean_text)
                                with open(baseline_path, "a", encoding="utf-8") as f:
                                    f.write(ciphertext_line + "\n")

                                with open(baseline_path, "r", encoding="utf-8") as f:
                                    line_count = sum(1 for ln in f if ln.strip())

                                if line_count == 20 or (
                                    line_count > 20 and line_count % 10 == 0
                                ):
                                    print(
                                        f"[WS] Auto-triggering /train for '{username}' "
                                        f"at {line_count} baseline lines."
                                    )
                                    asyncio.create_task(
                                        client.post(
                                            f"http://stylometry-ml-service:8001/train/{username}",
                                            timeout=30.0,
                                        )
                                    )

                            except Exception as exc:
                                print(
                                    f"[WS] Failed to write baseline or trigger training "
                                    f"for '{username}': {exc}"
                                )

                    # ── ML Evaluation ────────────────────────────────────────
                    if len(msg_buffer) >= 1:
                        if not enforce_security:
                            # Security OFF — bypass ML, keep collecting data
                            trust_score = 100.0
                            await websocket.send_json(
                                {
                                    "type": "trust_update",
                                    "trust_score": 100.0,
                                    "confidence": 1.0,
                                    "status": "inactive",
                                    "message": "Status: Monitoring Disabled (Data Collection Mode)",
                                }
                            )
                            await manager.broadcast(
                                chat_id,
                                {
                                    "type": "chat",
                                    "sender": username,
                                    "message": text,
                                    "trust_score": round(trust_score, 2),
                                    "is_broadcast": True,
                                },
                            )
                            continue

                        try:
                            ml_payload = {
                                "username": username,
                                "messages": list(msg_buffer),  # always plaintext
                            }
                            response = await client.post(
                                ML_SERVICE_URL, json=ml_payload, timeout=5.0
                            )

                            if response.status_code == 200:
                                ml_data = response.json()
                                average_score = float(ml_data.get("average_score", 1.0))
                                latest_score = float(ml_data.get("latest_score", 1.0))
                                status_msg = ml_data.get("status", "active")
                                print(
                                    f"[WS] ML → status={status_msg}, "
                                    f"average={average_score:.4f}, "
                                    f"latest={latest_score:.4f}"
                                )

                                if status_msg == "cold_start":
                                    await websocket.send_json(
                                        {
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(latest_score, 4)),
                                            "average_score": float(round(average_score, 4)),
                                            "status": "cold_start",
                                            "message": "Collecting baseline data...",
                                        }
                                    )
                                    await manager.broadcast(
                                        chat_id,
                                        {
                                            "type": "chat",
                                            "sender": username,
                                            "message": text,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        },
                                    )

                                else:
                                    # ── ACTIVE — 3-Zone Trust Logic ──────────
                                    # !! DO NOT ALTER THESE THRESHOLDS !!
                                    baseline_path = os.path.join(
                                        "/ml_workspace/data",
                                        f"{username}_baseline.txt",
                                    )
                                    try:
                                        with open(
                                            baseline_path, "r", encoding="utf-8"
                                        ) as f:
                                            baseline_count = sum(
                                                1 for ln in f if ln.strip()
                                            )
                                    except FileNotFoundError:
                                        baseline_count = 0

                                    score = latest_score

                                    # RED ZONE — clear anomaly, apply penalty
                                    if score < 0.50:
                                        penalty = 10.0 if baseline_count < 100 else 25.0
                                        trust_score = max(0.0, trust_score - penalty)
                                        print(
                                            f"[WS] Red Zone — penalty -{penalty} | "
                                            f"score={score:.3f} | trust={trust_score}"
                                        )

                                    # GRAY ZONE — uncertainty / novel vocabulary
                                    elif score <= 0.85:
                                        print(
                                            f"[WS] Gray Zone — no change | "
                                            f"score={score:.3f} | trust={trust_score}"
                                        )

                                    # GREEN ZONE — clear stylometric match, reward
                                    else:
                                        trust_score = min(100.0, trust_score + 5.0)
                                        print(
                                            f"[WS] Green Zone — reward +5.0 | "
                                            f"score={score:.3f} | trust={trust_score}"
                                        )

                                    # Update global trust score in manager
                                    manager.update_user_trust_score(username, trust_score)

                                    # Send trust update to the sender only
                                    await websocket.send_json(
                                        {
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(latest_score, 4)),
                                            "average_score": float(round(average_score, 4)),
                                            "status": "active",
                                        }
                                    )

                                    # Session freeze check (before broadcast)
                                    if enforce_security and trust_score < 40.0:
                                        await websocket.close(
                                            code=4001,
                                            reason="Session locked due to unusual typing behavior",
                                        )
                                        break

                                    # Broadcast to ALL room members only if not kicked
                                    await manager.broadcast(
                                        chat_id,
                                        {
                                            "type": "chat",
                                            "sender": username,
                                            "message": text,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        },
                                    )

                        except httpx.RequestError as exc:
                            print(f"[WS] ML Service unreachable: {exc}")

                except WebSocketDisconnect:
                    raise
                except Exception as exc:
                    import traceback

                    traceback.print_exc()
                    print(f"[WS] Inner-loop exception for '{username}': {exc}")
                    # Keep alive — do not crash the session on transient errors.

    except WebSocketDisconnect:
        print(f"[WS] '{username}' disconnected (WebSocketDisconnect).")
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(f"[WS] Outer-loop exception for '{username}': {exc}")
    finally:
        # SAFEGUARD: guaranteed cleanup regardless of disconnect cause.
        manager.disconnect(chat_id, username)
