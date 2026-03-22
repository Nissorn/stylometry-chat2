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
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Session State
    trust_score = 100.0
    msg_buffer = deque(maxlen=5)

    try:
        async with httpx.AsyncClient() as client:
            while True:
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
                            confidence = ml_data.get("confidence_score", 1.0)
                            
                            # Reward Logic
                            if confidence > 0.8:
                                trust_score = min(100.0, trust_score + 5.0)
                            # Penalty Logic
                            elif confidence < 0.5:
                                penalty = (0.5 - confidence) * 100.0
                                trust_score = max(0.0, trust_score - penalty)
                                
                            # Send trust update to UI
                            await websocket.send_json({
                                "type": "trust_update",
                                "trust_score": round(trust_score, 2),
                                "confidence": round(confidence, 4)
                            })
                            
                            # Session Freeze Check
                            if trust_score < 40.0:
                                await websocket.close(code=4001, reason="Session locked due to unusual typing behavior")
                                break
                    except httpx.RequestError as e:
                        # Log ml service failure without crashing chat
                        print(f"ML Service error: {e}")
                        
    except WebSocketDisconnect:
        pass
