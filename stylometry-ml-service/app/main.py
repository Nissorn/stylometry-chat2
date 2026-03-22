from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import random
import os
import joblib
import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier

app = FastAPI(title="Stylometry ML Microservice")

ML_WORKSPACE = "/ml_workspace/models"

class PredictRequest(BaseModel):
    username: str
    messages: List[str]

class TrainRequest(BaseModel):
    messages: List[str]

@app.get("/")
def read_root():
    return {"status": "ML Service is operating (Train on Demand Orchestration)"}

@app.post("/train/{username}")
def train_user_model(username: str, req: TrainRequest):
    if len(req.messages) < 5:
        raise HTTPException(status_code=400, detail="Require at least 5 messages to establish a baseline.")
        
    user_dir = os.path.join(ML_WORKSPACE, username)
    os.makedirs(user_dir, exist_ok=True)
    
    # Positive Samples
    user_texts = [msg for msg in req.messages if msg.strip()]
    labels = [1] * len(user_texts)
    
    # Dummy Negative Samples (Impostor texts)
    negative_texts = [
        "สวัสดีครับ ขอสอบถามข้อมูลหน่อยครับ",
        "ไม่ทราบว่ามีสินค้ารุ่นนี้ไหมคะ",
        "ขอบคุณมากครับที่ให้ข้อมูล",
        "เดี๋ยวโอนเงินแล้วจะแจ้งสลิปนะคะ",
        "จัดส่งได้วันไหนครับ",
        "ฮ่าๆๆ ตลกมากเลย",
        "วันนี้เหนื่อยจัง",
        "ใช่ๆ เห็นด้วยเลยแหละ",
        "โอเค งั้นเจอกันพรุ่งนี้นะ",
        "สนใจสั่งซื้อครับ"
    ]
    # Balance the dataset (or just append)
    neg_samples = random.choices(negative_texts, k=len(user_texts))
    labels.extend([0] * len(neg_samples))
    all_texts = user_texts + neg_samples
    
    # 1. Train TF-IDF
    tfidf = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=1000)
    X = tfidf.fit_transform(all_texts)
    
    # 2. Train Dummy Random Forest
    rf_model = RandomForestClassifier(n_estimators=50, random_state=42)
    rf_model.fit(X, labels)
    
    # 3. Save Artifacts to /ml_workspace/models/{username}
    joblib.dump(tfidf, os.path.join(user_dir, "tfidf.pkl"))
    joblib.dump(rf_model, os.path.join(user_dir, "rf_model.pkl"))
    
    return {"status": "success", "message": f"Orchestration POC: Trained unique model for {username}"}

@app.post("/predict")
def predict(req: PredictRequest):
    user_dir = os.path.join(ML_WORKSPACE, req.username)
    tfidf_path = os.path.join(user_dir, "tfidf.pkl")
    rf_path = os.path.join(user_dir, "rf_model.pkl")
    
    print(f"DEBUG: Checking for model at: {user_dir}")
    print(f"DEBUG: Model directory exists: {os.path.exists(user_dir)}")
    print(f"DEBUG: tfidf.pkl exists: {os.path.exists(tfidf_path)}")
    print(f"DEBUG: rf_model.pkl exists: {os.path.exists(rf_path)}")
    
    # COLD START TRIGGER: If personal models don't exist
    if not os.path.exists(tfidf_path) or not os.path.exists(rf_path):
        print(f"DEBUG: Cold start triggered for {req.username}. Models missing.")
        return {"confidence_score": 1.0, "status": "cold_start"}
        
    # ACTIVE INFERENCE: Load personal artifacts dynamically
    try:
        tfidf = joblib.load(tfidf_path)
        rf_model = joblib.load(rf_path)
        print(f"DEBUG: Successfully loaded TF-IDF and RF model for {req.username}")
    except Exception as e:
        print(f"DEBUG: Failed to load models for {req.username}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load user artifacts: {str(e)}")
        
    # Combine texts into a single temporal context for scoring
    combined_text = " ".join([m for m in req.messages if m.strip()])
    
    X_input = tfidf.transform([combined_text])
    probabilities = rf_model.predict_proba(X_input)[0]
    
    # Prob of class 1
    confidence = float(probabilities[1]) if len(probabilities) > 1 else 1.0
    print(f"DEBUG: Raw Confidence Score for {req.username}: {confidence}")
    
    return {"confidence_score": confidence, "status": "active"}
