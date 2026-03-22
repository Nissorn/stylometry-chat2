from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import random
import os
import joblib
import numpy as np

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.base import BaseEstimator, TransformerMixin
from xgboost import XGBClassifier

class StylometricFeatureExtractor(BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        return self

    def transform(self, X, y=None):
        features = []
        for text in X:
            text = str(text)
            length = len(text)
            laugh_count = len(re.findall(r'5+|[hH]aha|ฮ่า+|อิอิ', text))
            elongation_count = len(re.findall(r'(.)\1{2,}|ๆ', text))
            punct_count = len(re.findall(r'[?!.]{2,}|~+', text))
            space_count = text.count(' ')
            features.append([length, laugh_count, elongation_count, punct_count, space_count])
        return np.array(features)

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
    if not user_texts:
        raise HTTPException(status_code=400, detail="No valid text found in messages")
        
    pos_samples = random.choices(user_texts, k=50)
    labels = [1] * len(pos_samples)
    
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
        "สนใจสั่งซื้อครับ",
        "555555 โคตรฮา",
        "ดีจ้า วันนี้ทำไร",
        "หิวข้าวววว กินไรดี",
        "สุดยอดดดด",
        "อืม ตามนั้นแหละ",
        "รับทราบครับผม",
        "ฝันดีนะ",
        "สู้ๆ น้า",
        "รบกวนหน่อยนะคะ",
        "hello how are you",
        "test test 123",
        "what's up man",
        "good morning!",
        "เดี๋ยวทักไปใหม่นะ",
        "รอก่อนแป๊บ",
        "รีบไหม",
        "ตอนนี้ยุ่งมาก เดี่ยวโทรกลับ",
        "ส่งโลเคชั่นมาหน่อย",
        "โอนแล้ว 500 บาท",
        "พรุ่งนี้หยุดไหม",
        # New Diverse Additions
        "ok", "555", "ยืมเงินหน่อย",
        "asdfghjkl", "ฟหกดเาสวง",
        "I need some help please", "This is urgently required",
        "what do you mean by that?", "can you explain more",
        "really!!!", "what???", "no way!!!", "hurry up!!!",
        "???????", ".........."
    ]
    
    # Balance the dataset (or just append)
    neg_samples = random.choices(negative_texts, k=50)
    labels.extend([0] * len(neg_samples))
    all_texts = pos_samples + neg_samples
    
    # 1. Train Meta Extractor & Standardize
    meta_extractor = StylometricFeatureExtractor()
    X_meta = meta_extractor.fit_transform(all_texts)
    
    scaler = StandardScaler()
    X_meta_scaled = scaler.fit_transform(X_meta)
    
    # 2. Train TF-IDF
    tfidf = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=1000)
    X_tfidf = tfidf.fit_transform(all_texts).toarray()
    
    # Concatenate features
    X_combined = np.hstack((X_meta_scaled, X_tfidf))
    
    # 3. Train XGBoost model
    xgb_model = XGBClassifier(
        n_estimators=100, 
        max_depth=3, 
        learning_rate=0.1,
        random_state=42, 
        objective='binary:logistic',
        use_label_encoder=False, 
        eval_metric="logloss"
    )
    xgb_model.fit(X_combined, labels)
    
    # 4. Save Artifacts to /ml_workspace/models/{username}
    joblib.dump(meta_extractor, os.path.join(user_dir, "meta.pkl"))
    joblib.dump(scaler, os.path.join(user_dir, "scaler.pkl"))
    joblib.dump(tfidf, os.path.join(user_dir, "tfidf.pkl"))
    joblib.dump(xgb_model, os.path.join(user_dir, "xgb_model.pkl"))
    
    return {"status": "success", "message": f"Orchestration POC: Trained unique model for {username}"}

@app.post("/predict")
def predict(req: PredictRequest):
    user_dir = os.path.join(ML_WORKSPACE, req.username)
    meta_path = os.path.join(user_dir, "meta.pkl")
    scaler_path = os.path.join(user_dir, "scaler.pkl")
    tfidf_path = os.path.join(user_dir, "tfidf.pkl")
    xgb_path = os.path.join(user_dir, "xgb_model.pkl")
    
    print(f"DEBUG: Checking for model at: {user_dir}")
    print(f"DEBUG: Model directory exists: {os.path.exists(user_dir)}")
    print(f"DEBUG: xgb_model.pkl exists: {os.path.exists(xgb_path)}")
    
    # COLD START TRIGGER: If personal models don't exist
    if not os.path.exists(xgb_path):
        print(f"DEBUG: Cold start triggered for {req.username}. Models missing.")
        return {"confidence_score": 1.0, "status": "cold_start"}
        
    # ACTIVE INFERENCE: Load personal artifacts dynamically
    try:
        meta_extractor = joblib.load(meta_path)
        scaler = joblib.load(scaler_path)
        tfidf = joblib.load(tfidf_path)
        xgb_model = joblib.load(xgb_path)
        print(f"DEBUG: Successfully loaded Meta, Scaler, TF-IDF and XGB models for {req.username}")
    except Exception as e:
        print(f"DEBUG: Failed to load models for {req.username}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load user artifacts: {str(e)}")
        
    # Process each message individually and average the scores
    valid_msgs = [m for m in req.messages if m.strip()]
    if not valid_msgs:
        return {"confidence_score": 1.0, "status": "active"}

    print(f"DEBUG: Processing {len(valid_msgs)} Individual Texts: {valid_msgs}")
    
    X_meta = meta_extractor.transform(valid_msgs)
    print(f"DEBUG: Meta features (First msg): {X_meta[0]}")
    
    X_meta_scaled = scaler.transform(X_meta)
    
    X_tfidf_sparse = tfidf.transform(valid_msgs)
    X_tfidf = X_tfidf_sparse.toarray()
    print(f"DEBUG: TF-IDF shape: {X_tfidf.shape}, non-zero elements: {X_tfidf_sparse.nnz}")
    
    X_combined = np.hstack((X_meta_scaled, X_tfidf))
    probabilities = xgb_model.predict_proba(X_combined)
    
    # Prob of class 1 for each message
    confidences = [float(p[1]) if len(p) > 1 else 1.0 for p in probabilities]
    confidence = sum(confidences) / len(confidences)
    
    print(f"DEBUG: Individual message confidences: {confidences}")
    print(f"DEBUG: Raw Average Confidence Score for {req.username}: {confidence}")
    
    return {"confidence_score": confidence, "status": "active"}
