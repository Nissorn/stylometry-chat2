from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import httpx
from collections import deque
import asyncio

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
async def websocket_endpoint(websocket: WebSocket, token: str = None, db: Session = Depends(get_db)):
    await websocket.accept()
    if not token:
        print("DEBUG: Connection closed due to missing token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            print("DEBUG: Connection closed - JWT missing sub")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception as e:
        print(f"DEBUG: Connection closed - JWT Error: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
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
                    data = await websocket.receive_text()
                    
                    # Echo logic
                    await websocket.send_json({"type": "chat", "sender": "me", "text": data})
                    await websocket.send_json({"type": "chat", "sender": "bot", "text": f"Echo: {data}"})
                    
                    # Stylometry buffering
                    if len(data.strip()) > 0:
                        msg_buffer.append(data.strip())
                    
                    # Check buffer sliding window
                    if len(msg_buffer) == 5:
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
                                    # Reward Logic
                                    if confidence > 0.8:
                                        change_val = 5.0
                                        trust_score = min(100.0, trust_score + change_val)
                                        print(f"DEBUG: Current Trust Score: {trust_score}, Change: +{change_val} (Reward)")
                                    # Penalty Logic
                                    elif confidence < 0.5:
                                        change_val = float((0.5 - confidence) * 100.0)
                                        trust_score = max(0.0, trust_score - change_val)
                                        print(f"DEBUG: Current Trust Score: {trust_score}, Change: -{change_val} (Penalty)")
                                    else:
                                        print(f"DEBUG: Current Trust Score: {trust_score}, Change: 0.0 (Neutral)")
                                        
                                    # Send trust update to UI
                                    await websocket.send_json({
                                        "type": "trust_update",
                                        "trust_score": float(round(trust_score, 2)),
                                        "confidence": float(round(confidence, 4)),
                                        "status": "active"
                                    })
                                    
                                    # Session Freeze Check
                                    if trust_score < 40.0:
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
