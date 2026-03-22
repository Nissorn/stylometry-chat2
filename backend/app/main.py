from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import httpx
from collections import deque
import asyncio
import json
import os

from . import models, auth
from .database import engine, get_db
from .auth import router as auth_router

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
async def websocket_endpoint(websocket: WebSocket, token: str = None, db: Session = Depends(get_db)):
    await websocket.accept()
    if not token:
        print("DEBUG: Connection closed due to missing token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    try:
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

        # Session State
        trust_score = 100.0
        msg_buffer = deque(maxlen=5)

        try:
            async with httpx.AsyncClient() as client:
                while True:
                    try:
                        payload_txt = await websocket.receive_text()
                        print(f"DEBUG: Raw received: {payload_txt}")
                        try:
                            data = json.loads(payload_txt)
                            if not isinstance(data, dict):
                                data = {"message": str(payload_txt), "enforce_security": False}
                        except Exception:
                            data = {"message": str(payload_txt), "enforce_security": False}
                        
                        text = str(data.get("message", ""))
                        enforce_security = bool(data.get("enforce_security", False))
                            
                        # Echo logic
                        await websocket.send_json({"type": "chat", "sender": "me", "text": text})
                        await websocket.send_json({"type": "chat", "sender": "bot", "text": f"Echo: {text}"})
                        
                        # Stylometry buffering
                        clean_text = text.strip()
                        if len(clean_text) > 0:
                            msg_buffer.append(clean_text)
                            
                            # Auto-Collection (Baseline formulation)
                            if trust_score > 90.0:
                                data_dir = "/ml_workspace/data"
                                try:
                                    os.makedirs(data_dir, exist_ok=True)
                                    baseline_path = os.path.join(data_dir, f"{username}_baseline.txt")
                                    with open(baseline_path, "a", encoding="utf-8") as f:
                                        f.write(clean_text + "\n")
                                        
                                    # Auto-Retraining Trigger
                                    with open(baseline_path, "r", encoding="utf-8") as f:
                                        line_count = sum(1 for line in f if line.strip())
                                        
                                    if line_count == 20 or (line_count > 20 and line_count % 10 == 0):
                                        print(f"DEBUG: Auto-Triggering /train for {username} at {line_count} lines")
                                        asyncio.create_task(client.post(f"http://stylometry-ml-service:8001/train/{username}", timeout=30.0))
                                        
                                except Exception as e:
                                    print(f"DEBUG: Failed to write baseline data or trigger training: {e}")
                        
                        # Check buffer sliding window
                        if len(msg_buffer) == 5:
                            if not enforce_security:
                                # Bypass ML service completely
                                trust_score = 100.0  # Reset/Maintain at 100
                                await websocket.send_json({
                                    "type": "trust_update",
                                    "trust_score": 100.0,
                                    "confidence": 1.0,
                                    "status": "inactive",
                                    "message": "Status: Monitoring Disabled (Data Collection Mode)"
                                })
                                continue
                                
                            try:
                                ml_payload = {
                                    "username": username,
                                    "messages": list(msg_buffer)
                                }
                                response = await client.post(ML_SERVICE_URL, json=ml_payload, timeout=5.0)
                                if response.status_code == 200:
                                    ml_data = response.json()
                                    confidence = float(ml_data.get("confidence_score", 1.0))
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
                                    else:
                                        # ACTIVE STATUS - Apply trust score mathematics
                                        # Count baseline dynamically for Grace Period
                                        baseline_path = os.path.join("/ml_workspace/data", f"{username}_baseline.txt")
                                        try:
                                            with open(baseline_path, "r", encoding="utf-8") as f:
                                                baseline_count = sum(1 for line in f if line.strip())
                                        except FileNotFoundError:
                                            baseline_count = 0
                                            
                                        # Reward Logic
                                        if confidence > 0.85:
                                            change_val = 5.0
                                            trust_score = min(100.0, trust_score + change_val)
                                            print(f"DEBUG: Current Trust Score: {trust_score}, Change: +{change_val} (Reward)")
                                        # Penalty Logic
                                        elif confidence < 0.7:
                                            if baseline_count <= 20:
                                                penalty_multiplier = 0.0
                                            elif baseline_count <= 60:
                                                penalty_multiplier = 15.0
                                            elif baseline_count <= 120:
                                                penalty_multiplier = 40.0
                                            elif baseline_count <= 200:
                                                penalty_multiplier = 80.0
                                            else:
                                                penalty_multiplier = 150.0
                                                
                                            change_val = float((0.7 - confidence) * penalty_multiplier)
                                            trust_score = max(0.0, trust_score - change_val)
                                            print(f"DEBUG: Current Trust Score: {trust_score}, Change: -{change_val} (Penalty Multiplier: {penalty_multiplier})")
                                        else:
                                            print(f"DEBUG: Current Trust Score: {trust_score}, Change: 0.0 (Neutral)")
                                            
                                        # Send trust update to UI
                                        await websocket.send_json({
                                            "type": "trust_update",
                                            "trust_score": float(round(trust_score, 2)),
                                            "confidence": float(round(confidence, 4)),
                                            "status": "active"
                                        })
                                        
                                        # Session Freeze Check (Only if enforcement is ON)
                                        if enforce_security and trust_score < 40.0:
                                            await websocket.close(code=4001, reason="Session locked due to unusual typing behavior")
                                            break
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
            pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"DEBUG: Outer websocket exception: {e}")
