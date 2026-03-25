import asyncio
import json
import os
from collections import deque
from typing import Dict

import httpx
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import auth, models
from .auth import router as auth_router
from .crypto import decrypt, encrypt
from .database import engine, get_db

# ---------------------------------------------------------------------------
# Schema + lightweight migration (idempotent — safe to run on every startup)
# ---------------------------------------------------------------------------
models.Base.metadata.create_all(bind=engine)


def _run_migrations() -> None:
    """Add new columns to the users table when they don't exist yet.

    SQLAlchemy's create_all only creates *missing* tables; it never alters
    existing ones.  This helper patches the gap for the two Step-Up Auth
    columns added in Phase 8 without requiring Alembic on a dev branch.
    """
    new_columns = [
        ("security_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("unlock_pin_hash", "VARCHAR"),
    ]
    with engine.connect() as conn:
        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(users)"))
        }
        for col_name, col_def in new_columns:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                print(f"[MIGRATION] Added column users.{col_name}")
        conn.commit()


_run_migrations()

# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------
app = FastAPI(title="Thai-Stylometry Auth API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")


@app.get("/")
def read_root():
    return {"message": "Welcome to Thai-Stylometry API"}


ML_SERVICE_URL = "http://stylometry-ml-service:8001/predict"


# ---------------------------------------------------------------------------
# Multi-User Connection Manager
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        # Maps username -> active WebSocket
        self.active_connections: Dict[str, WebSocket] = {}

        # Session state machine: "ACTIVE" | "LOCKED"
        # Default is "ACTIVE"; set to "LOCKED" on step-up challenge.
        self.user_states: Dict[str, str] = {}

        # Holds the raw plaintext of the message that triggered the lock so it
        # can be encrypted, persisted, and broadcast after a successful PIN
        # verification — no message is silently dropped.
        self.pending_messages: Dict[str, str] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self, username: str, websocket: WebSocket):
        self.active_connections[username] = websocket
        self.user_states[username] = "ACTIVE"
        print(
            f"DEBUG: ConnectionManager — {username} connected. "
            f"Active: {list(self.active_connections.keys())}"
        )

    def disconnect(self, username: str):
        self.active_connections.pop(username, None)
        self.user_states.pop(username, None)
        self.pending_messages.pop(username, None)
        print(
            f"DEBUG: ConnectionManager — {username} disconnected. "
            f"Active: {list(self.active_connections.keys())}"
        )

    # ── State helpers ────────────────────────────────────────────────────────

    def lock(self, username: str) -> None:
        """Freeze the session — user must pass step-up auth to resume."""
        self.user_states[username] = "LOCKED"
        print(f"DEBUG: Session LOCKED — {username}")

    def unlock(self, username: str) -> None:
        """Restore the session after successful PIN verification."""
        self.user_states[username] = "ACTIVE"
        self.pending_messages.pop(username, None)
        print(f"DEBUG: Session UNLOCKED — {username}")

    # ── Broadcast helpers ────────────────────────────────────────────────────

    async def broadcast(self, payload: dict):
        """Send *payload* to ALL currently connected users.

        Per-socket errors are swallowed so one dead socket never crashes others.
        """
        dead: list[str] = []
        for uname, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(payload)
            except Exception as e:
                print(f"DEBUG: Broadcast failed for {uname}: {e} — marking for removal")
                dead.append(uname)
        for uname in dead:
            self.active_connections.pop(uname, None)

    async def broadcast_except(self, exclude_username: str, payload: dict):
        """Send *payload* to every connected user **except** *exclude_username*.

        Used for system_alert messages so the frozen user doesn't receive their
        own alert (they already received auth_challenge).
        """
        dead: list[str] = []
        for uname, ws in list(self.active_connections.items()):
            if uname == exclude_username:
                continue
            try:
                await ws.send_json(payload)
            except Exception as e:
                print(
                    f"DEBUG: broadcast_except failed for {uname}: {e} — marking for removal"
                )
                dead.append(uname)
        for uname in dead:
            self.active_connections.pop(uname, None)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# WebSocket Chat Endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat")
# Phase 5: Train on Demand & Predict Per User
# - [x] Analyze ML Workspace & Data Pipelines
# - [x] Redesign Architecture for "Train on Demand" (Approved)
# - [x] Mount ML Workspace via `docker-compose.yml`
# - [x] Implement `POST /train/{username}` endpoint (Dummy Orchestration)
# - [x] Implement `POST /predict` endpoint (Cold Start Logic)
# - [x] Update Backend socket hooks to respect `cold_start` and `active` status

# Phase 6: Real Model Integration & Auto-Data Collection
# - [x] Backend: Write messages securely to `/ml_workspace/data/{username}_baseline.txt` when Trust>90
# - [x] Svelte: Add "Security Enforcement" Toggle to Navbar and transmit states
# - [x] ML Service: Implement Stylometric Meta Features `StylometricFeatureExtractor`
# - [x] ML Logic: Upgrade to `XGBClassifier`, refine Trust Score Penalty to 150x

# Phase 7: Multi-User Chat + Encryption at Rest
# - [x] ConnectionManager: broadcast authenticated messages to all users
# - [x] Fernet AES-128: encrypt baseline messages on disk, decrypt in buffer pre-fill
# - [x] Architect safeguards: finally-block disconnect, plaintext-first predict

# Phase 8: Session Freeze + Secondary PIN (Step-Up Auth) + System Alert
# - [x] ConnectionManager: user_states, pending_messages, lock/unlock, broadcast_except
# - [x] WebSocket: step-up challenge when trust < 40 and security_enabled
# - [x] WebSocket: verify_pin handler — PIN check, unlock, emit pending message
# - [x] REST: POST /auth/security/enable (JWT-protected, bcrypt PIN hash)
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = None,
    db: Session = Depends(get_db),
):
    await websocket.accept()
    if not token:
        print("DEBUG: Connection closed due to missing token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── JWT Validation ──────────────────────────────────────────────────────
    try:
        jwt_payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = jwt_payload.get("sub")
        if username is None:
            print("DEBUG: Connection closed - JWT missing sub")
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return
    except Exception as e:
        print(f"DEBUG: Token validation failed: {e}")
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        print(f"DEBUG: Connection closed - User {username} not found in DB")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── Session State ────────────────────────────────────────────────────────
    trust_score = 100.0

    # Pre-fill buffer with last 4 baseline messages.
    # Each line may be Fernet ciphertext (new) or legacy plaintext (old).
    _baseline_prefill_path = os.path.join(
        "/ml_workspace/data", f"{username}_baseline.txt"
    )
    try:
        with open(_baseline_prefill_path, "r", encoding="utf-8") as _f:
            _all_lines = [l.strip() for l in _f if l.strip()]
        _seed_msgs = []
        for _line in _all_lines[-4:] if len(_all_lines) >= 4 else _all_lines:
            _plain = decrypt(_line)
            _seed_msgs.append(_plain if _plain is not None else _line)
    except FileNotFoundError:
        _seed_msgs = []
    msg_buffer = deque(_seed_msgs, maxlen=5)
    score_buffer = deque(maxlen=5)  # Tracks raw per-message confidence scores
    print(
        f"DEBUG: Session started for {username} — "
        f"buffer pre-filled with {len(_seed_msgs)} baseline messages"
    )

    # Register with the connection manager.
    # The finally block guarantees disconnect even on exceptions or forced closes.
    await manager.connect(username, websocket)

    try:
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    payload_txt = await websocket.receive_text()
                    print(f"DEBUG: Raw received from {username}: {payload_txt}")

                    try:
                        data = json.loads(payload_txt)
                        if not isinstance(data, dict):
                            data = {
                                "message": str(payload_txt),
                                "enforce_security": False,
                            }
                    except Exception:
                        data = {"message": str(payload_txt), "enforce_security": False}

                    msg_type = data.get("type", "")

                    # ── Step-Up Auth: verify_pin ─────────────────────────────
                    if msg_type == "verify_pin":
                        if manager.user_states.get(username) == "LOCKED":
                            provided_pin = str(data.get("pin", ""))
                            # Always query fresh — never trust a stale ORM identity
                            fresh_user = (
                                db.query(models.User)
                                .filter(models.User.username == username)
                                .first()
                            )
                            pin_ok = (
                                fresh_user is not None
                                and fresh_user.unlock_pin_hash is not None
                                and auth.pwd_context.verify(
                                    provided_pin, fresh_user.unlock_pin_hash
                                )
                            )

                            if pin_ok:
                                manager.unlock(username)

                                # Explicit local-scope reset — trust_score is a
                                # plain float; re-assign to guarantee the updated
                                # value is used by every subsequent expression in
                                # this coroutine's local frame.
                                trust_score = 100.0

                                # 1. Notify sender first
                                await websocket.send_json(
                                    {
                                        "type": "auth_success",
                                        "message": "✅ Identity verified. Session fully restored.",
                                    }
                                )

                                # 2. Deliver the pending message that triggered
                                #    the lock — encrypt, persist, then broadcast.
                                pending_text = manager.pending_messages.pop(
                                    username, None
                                )
                                if pending_text:
                                    # Encrypt and persist to baseline on-disk
                                    try:
                                        data_dir = "/ml_workspace/data"
                                        os.makedirs(data_dir, exist_ok=True)
                                        baseline_path = os.path.join(
                                            data_dir, f"{username}_baseline.txt"
                                        )
                                        ciphertext_line = encrypt(pending_text)
                                        with open(
                                            baseline_path, "a", encoding="utf-8"
                                        ) as fh:
                                            fh.write(ciphertext_line + "\n")
                                    except Exception as exc:
                                        print(
                                            f"DEBUG: Failed to persist pending message "
                                            f"for {username}: {exc}"
                                        )

                                    # Broadcast the recovered message to everyone
                                    await manager.broadcast(
                                        {
                                            "type": "chat",
                                            "sender": username,
                                            "message": pending_text,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        }
                                    )

                                # 3. Clear the system alert on all other clients
                                await manager.broadcast_except(
                                    username,
                                    {
                                        "type": "system_alert",
                                        "message": (
                                            f"✅ {username}'s identity has been verified. "
                                            "Session fully restored."
                                        ),
                                        "clear": True,
                                    },
                                )

                            else:
                                # Wrong PIN — re-challenge, do NOT unlock
                                await websocket.send_json(
                                    {
                                        "type": "auth_challenge",
                                        "message": "❌ Incorrect PIN. Please try again.",
                                    }
                                )
                        # Consume the frame regardless of lock state; do not
                        # fall through to normal message processing.
                        continue

                    # ── While LOCKED: silently discard non-PIN frames ────────
                    if manager.user_states.get(username) == "LOCKED":
                        # User must pass PIN verification before chatting again.
                        continue

                    # ── Normal message processing ────────────────────────────
                    text = str(data.get("message", ""))
                    enforce_security = bool(data.get("enforce_security", False))

                    # Stylometry buffering — plaintext goes into buffer for /predict
                    clean_text = text.strip()
                    if len(clean_text) > 0:
                        msg_buffer.append(clean_text)

                        # Auto-Collection (Baseline formulation)
                        # IMPORTANT: encrypt AFTER predict, but BEFORE writing to disk
                        if trust_score > 90.0:
                            data_dir = "/ml_workspace/data"
                            try:
                                os.makedirs(data_dir, exist_ok=True)
                                baseline_path = os.path.join(
                                    data_dir, f"{username}_baseline.txt"
                                )

                                # Encrypt the plaintext before persisting
                                ciphertext_line = encrypt(clean_text)
                                with open(baseline_path, "a", encoding="utf-8") as f:
                                    f.write(ciphertext_line + "\n")

                                # Count lines (each ciphertext is one line — no internal newlines)
                                with open(baseline_path, "r", encoding="utf-8") as f:
                                    line_count = sum(1 for line in f if line.strip())

                                if line_count == 20 or (
                                    line_count > 20 and line_count % 10 == 0
                                ):
                                    print(
                                        f"DEBUG: Auto-Triggering /train for {username} "
                                        f"at {line_count} lines"
                                    )
                                    asyncio.create_task(
                                        client.post(
                                            f"http://stylometry-ml-service:8001/train/{username}",
                                            timeout=30.0,
                                        )
                                    )

                            except Exception as e:
                                print(
                                    f"DEBUG: Failed to write baseline data or trigger training: {e}"
                                )

                    # Evaluate from message 1 (deque maxlen=5 handles sliding window)
                    if len(msg_buffer) >= 1:
                        if not enforce_security:
                            # Bypass ML service completely
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
                            # Still broadcast the message to all users when security is OFF
                            await manager.broadcast(
                                {
                                    "type": "chat",
                                    "sender": username,
                                    "message": text,
                                    "trust_score": round(trust_score, 2),
                                    "is_broadcast": True,
                                }
                            )
                            continue

                        try:
                            # SAFEGUARD: msg_buffer contains raw plaintext — /predict receives plaintext
                            ml_payload = {
                                "username": username,
                                "messages": list(msg_buffer),  # plaintext
                            }
                            response = await client.post(
                                ML_SERVICE_URL, json=ml_payload, timeout=5.0
                            )
                            if response.status_code == 200:
                                ml_data = response.json()
                                confidence = float(ml_data.get("confidence_score", 1.0))
                                latest_message_confidence = float(
                                    ml_data.get("latest_message_confidence", 1.0)
                                )
                                status_msg = ml_data.get("status", "active")
                                print(
                                    f"DEBUG: Received from ML Service -> "
                                    f"Status: {status_msg}, Score: {confidence}"
                                )

                                if status_msg == "cold_start":
                                    await websocket.send_json(
                                        {
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(confidence, 4)),
                                            "status": "cold_start",
                                            "message": "Collecting baseline data...",
                                        }
                                    )
                                    # Broadcast in cold_start so the sender's message
                                    # appears for all users
                                    await manager.broadcast(
                                        {
                                            "type": "chat",
                                            "sender": username,
                                            "message": text,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        }
                                    )
                                else:
                                    # ACTIVE STATUS — 3-Zone Gray Zone Trust Logic
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
                                                1 for line in f if line.strip()
                                            )
                                    except FileNotFoundError:
                                        baseline_count = 0

                                    score = latest_message_confidence

                                    # RED ZONE — Clear anomaly, apply penalty
                                    if score < 0.50:
                                        if baseline_count < 100:
                                            penalty = 10.0
                                        else:
                                            penalty = 25.0
                                        trust_score = max(0.0, trust_score - penalty)
                                        print(
                                            f"DEBUG: Red Zone — penalty -{penalty} | "
                                            f"score={score:.3f} | trust={trust_score}"
                                        )

                                    # GRAY ZONE — Uncertainty / novel vocabulary, do nothing
                                    elif score <= 0.85:
                                        print(
                                            f"DEBUG: Gray Zone — no change | "
                                            f"score={score:.3f} | trust={trust_score}"
                                        )

                                    # GREEN ZONE — Clear stylometric match, reward
                                    else:
                                        trust_score = min(100.0, trust_score + 5.0)
                                        print(
                                            f"DEBUG: Green Zone — reward +5.0 | "
                                            f"score={score:.3f} | trust={trust_score}"
                                        )

                                    # Send trust update to sender only
                                    await websocket.send_json(
                                        {
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(confidence, 4)),
                                            "status": "active",
                                        }
                                    )

                                    # ── Session Freeze / Step-Up Auth ───────
                                    if enforce_security and trust_score < 40.0:
                                        # Refresh to prevent stale SQLAlchemy identity map
                                        db.refresh(user)

                                        if user.security_enabled:
                                            # ── SOFT LOCK (Step-Up Auth) ────
                                            manager.lock(username)
                                            # Hold the triggering message until PIN is verified
                                            manager.pending_messages[username] = text

                                            await websocket.send_json(
                                                {
                                                    "type": "auth_challenge",
                                                    "message": (
                                                        "⚠️ Unusual typing pattern detected. "
                                                        "Enter your Security PIN to resume."
                                                    ),
                                                }
                                            )

                                            await manager.broadcast_except(
                                                username,
                                                {
                                                    "type": "system_alert",
                                                    "message": (
                                                        f"⚠️ {username}'s session has been frozen "
                                                        "pending identity verification."
                                                    ),
                                                    "clear": False,
                                                },
                                            )

                                            # Do NOT broadcast the unverified message yet;
                                            # skip to next receive iteration.
                                            continue

                                        else:
                                            # ── HARD KICK (no PIN registered) ──
                                            await websocket.close(
                                                code=4001,
                                                reason="Session locked due to unusual typing behavior",
                                            )
                                            break

                                    # Broadcast to ALL users only if sender is NOT kicked/locked
                                    await manager.broadcast(
                                        {
                                            "type": "chat",
                                            "sender": username,
                                            "message": text,
                                            "trust_score": round(trust_score, 2),
                                            "is_broadcast": True,
                                        }
                                    )

                        except httpx.RequestError as e:
                            # Log ML service failure without crashing chat
                            print(f"ML Service error: {e}")

                except WebSocketDisconnect:
                    raise
                except Exception as e:
                    import traceback

                    traceback.print_exc()
                    print(f"DEBUG: Exception in websocket inner loop: {e}")
                    # keep alive

    except WebSocketDisconnect:
        print(f"DEBUG: {username} disconnected (WebSocketDisconnect)")
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"DEBUG: Outer websocket exception for {username}: {e}")
    finally:
        # SAFEGUARD: guarantee cleanup regardless of disconnect cause
        manager.disconnect(username)
