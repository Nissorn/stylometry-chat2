from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import httpx
from collections import deque
import asyncio
import json
import os
from typing import Dict

from . import models, auth
from .database import engine, get_db
from .auth import router as auth_router
from .crypto import encrypt, decrypt

models.Base.metadata.create_all(bind=engine)

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

    async def connect(self, username: str, websocket: WebSocket):
        self.active_connections[username] = websocket
        print(f"DEBUG: ConnectionManager — {username} connected. Active: {list(self.active_connections.keys())}")

    def disconnect(self, username: str):
        self.active_connections.pop(username, None)
        print(f"DEBUG: ConnectionManager — {username} disconnected. Active: {list(self.active_connections.keys())}")

    async def broadcast(self, payload: dict):
        """Send payload to ALL currently connected users.
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
async def websocket_endpoint(websocket: WebSocket, token: str = None, db: Session = Depends(get_db)):
    await websocket.accept()
    if not token:
        print("DEBUG: Connection closed due to missing token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── JWT Validation ──────────────────────────────────────────────────────
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
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
    _baseline_prefill_path = os.path.join("/ml_workspace/data", f"{username}_baseline.txt")
    try:
        with open(_baseline_prefill_path, "r", encoding="utf-8") as _f:
            _all_lines = [l.strip() for l in _f if l.strip()]
        _seed_msgs = []
        for _line in (_all_lines[-4:] if len(_all_lines) >= 4 else _all_lines):
            _plain = decrypt(_line)
            _seed_msgs.append(_plain if _plain is not None else _line)
    except FileNotFoundError:
        _seed_msgs = []
    msg_buffer = deque(_seed_msgs, maxlen=5)
    score_buffer = deque(maxlen=5)  # Tracks raw per-message confidence scores for strike counting
    print(f"DEBUG: Session started for {username} — buffer pre-filled with {len(_seed_msgs)} baseline messages")

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
                            data = {"message": str(payload_txt), "enforce_security": False}
                    except Exception:
                        data = {"message": str(payload_txt), "enforce_security": False}

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
                                baseline_path = os.path.join(data_dir, f"{username}_baseline.txt")

                                # Encrypt the plaintext before persisting
                                ciphertext_line = encrypt(clean_text)
                                with open(baseline_path, "a", encoding="utf-8") as f:
                                    f.write(ciphertext_line + "\n")

                                # Count lines (each ciphertext is a single line — no internal newlines)
                                with open(baseline_path, "r", encoding="utf-8") as f:
                                    line_count = sum(1 for line in f if line.strip())

                                if line_count == 20 or (line_count > 20 and line_count % 10 == 0):
                                    print(f"DEBUG: Auto-Triggering /train for {username} at {line_count} lines")
                                    asyncio.create_task(client.post(f"http://stylometry-ml-service:8001/train/{username}", timeout=30.0))

                            except Exception as e:
                                print(f"DEBUG: Failed to write baseline data or trigger training: {e}")

                    # Evaluate from message 1 (deque maxlen=5 handles sliding window automatically)
                    if len(msg_buffer) >= 1:
                        if not enforce_security:
                            # Bypass ML service completely
                            trust_score = 100.0
                            await websocket.send_json({
                                "type": "trust_update",
                                "trust_score": 100.0,
                                "confidence": 1.0,
                                "status": "inactive",
                                "message": "Status: Monitoring Disabled (Data Collection Mode)"
                            })
                            # Still broadcast the message to all users even when security is OFF
                            await manager.broadcast({
                                "type": "chat",
                                "sender": username,
                                "message": text,
                                "trust_score": round(trust_score, 2),
                                "is_broadcast": True
                            })
                            continue

                        try:
                            # SAFEGUARD: msg_buffer contains raw plaintext — /predict receives plaintext
                            ml_payload = {
                                "username": username,
                                "messages": list(msg_buffer)  # plaintext
                            }
                            response = await client.post(ML_SERVICE_URL, json=ml_payload, timeout=5.0)
                            if response.status_code == 200:
                                ml_data = response.json()
                                confidence = float(ml_data.get("confidence_score", 1.0))
                                latest_message_confidence = float(ml_data.get("latest_message_confidence", 1.0))
                                status_msg = ml_data.get("status", "active")
                                print(f"DEBUG: Received from ML Service -> Status: {status_msg}, Score: {confidence}")

                                if status_msg == "cold_start":
                                    await websocket.send_json({
                                        "type": "trust_update",
                                        "trust_score": float(round(trust_score, 2)),
                                        "confidence": float(round(confidence, 4)),
                                        "status": "cold_start",
                                        "message": "Collecting baseline data..."
                                    })
                                    # Broadcast in cold_start too so the sender's message
                                    # appears for all users
                                    await manager.broadcast({
                                        "type": "chat",
                                        "sender": username,
                                        "message": text,
                                        "trust_score": round(trust_score, 2),
                                        "is_broadcast": True
                                    })
                                else:
                                    # ACTIVE STATUS — 3-Zone Gray Zone Trust Logic
                                    # !! DO NOT ALTER THESE THRESHOLDS !!
                                    baseline_path = os.path.join("/ml_workspace/data", f"{username}_baseline.txt")
                                    try:
                                        with open(baseline_path, "r", encoding="utf-8") as f:
                                            baseline_count = sum(1 for line in f if line.strip())
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
                                        print(f"DEBUG: Red Zone — penalty -{penalty} | score={score:.3f} | trust={trust_score}")

                                    # GRAY ZONE — Uncertainty / novel vocabulary, do nothing
                                    elif score <= 0.85:
                                        print(f"DEBUG: Gray Zone — no change | score={score:.3f} | trust={trust_score}")

                                    # GREEN ZONE — Clear stylometric match, reward
                                    else:
                                        trust_score = min(100.0, trust_score + 5.0)
                                        print(f"DEBUG: Green Zone — reward +5.0 | score={score:.3f} | trust={trust_score}")

                                    # Send trust update to sender only
                                    await websocket.send_json({
                                        "type": "trust_update",
                                        "trust_score": float(round(trust_score, 2)),
                                        "confidence": float(round(confidence, 4)),
                                        "status": "active"
                                    })

                                    # Session Freeze Check (sender only, before broadcast)
                                    if enforce_security and trust_score < 40.0:
                                        await websocket.close(code=4001, reason="Session locked due to unusual typing behavior")
                                        break

                                    # Broadcast to ALL users only if sender is NOT kicked
                                    await manager.broadcast({
                                        "type": "chat",
                                        "sender": username,
                                        "message": text,
                                        "trust_score": round(trust_score, 2),
                                        "is_broadcast": True
                                    })

                        except httpx.RequestError as e:
                            # Log ml service failure without crashing chat
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
