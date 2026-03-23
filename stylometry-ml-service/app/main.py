from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import random
import os
import joblib
import numpy as np

import re
import json
import torch
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from app.fusion_models import CharVocab, AttentionSessionCNN, StylometricFeatureExtractor

UNIVERSAL_BACKGROUND_CORPUS = [
    "การประชุมจะเริ่มในเวลา 10.00 น. ขอให้ทุกคนตรงต่อเวลาด้วยครับ",
    "ทางบริษัทขอขอบพระคุณที่ท่านให้ความสนใจในบริการของเรา",
    "วันนี้สภาพอากาศค่อนข้างแปรปรวน โปรดดูแลรักษาสุขภาพ",
    "เอกสารที่ส่งมาให้เมื่อวานได้รับครบถ้วนแล้วนะคะ ขอบคุณมากค่ะ",
    "ขออนุญาตแจ้งเปลี่ยนแปลงกำหนดการเดินทางในวันพรุ่งนี้",
    "ตลาดหุ้นวันนี้ปิดตลาดปรับตัวลดลงตามทิศทางตลาดต่างประเทศ",
    "รับทราบครับ จะดำเนินการให้เสร็จภายในวันศุกร์นี้",
    "คุณลูกค้าสามารถชำระเงินผ่านระบบคิวอาร์โค้ดได้เลยค่ะ",
    "เมื่อคืนฝนตกหนักมากเลย ถนนแถวบ้านติดสุดๆ",
    "สรุปยอดขายประจำเดือนนี้เดี๋ยวผมส่งให้ในอีเมลนะครับ",
    "โครงการนี้มีกำหนดการแล้วเสร็จภายในไตรมาสที่สามของปีหน้า",
    "เดี๋ยวแวะซื้อกาแฟก่อนเข้าออฟฟิศ มีใครเอาอะไรไหม",
    "ขอแสดงความเสียใจกับครอบครัวผู้สูญเสียด้วยครับ",
    "รบกวนช่วยตรวจสอบความถูกต้องของข้อมูลในตารางให้หน่อย",
    "พรุ่งนี้เรามีนัดคุยเรื่องโปรเจกต์ใหม่ตอนบ่ายโมงตรงนะ",
    "รัฐบาลประกาศมาตรการกระตุ้นเศรษฐกิจเฟสใหม่แล้ววันนี้",
    "ขออภัยในความไม่สะดวก ทางเราจะรีบปรับปรุงแก้ไขโดยเร็วที่สุด",
    "วันนี้ประชุมยาวมากเลย แทบจะไม่ได้พักทานข้าว",
    "สินค้าชิ้นนี้มีการรับประกัน 1 ปีนับจากวันที่ซื้อครับ",
    "สุขสันต์วันเกิด ขอให้มีความสุขมากๆ สุขภาพแข็งแรงนะ",
    "คณะกรรมการมีมติเห็นชอบกับข้อเสนอดังกล่าวเป็นเอกฉันท์",
    "ตอนนี้กำลังเดินทางไป น่าจะถึงประมาณครึ่งชั่วโมง",
    "รบกวนส่งเอกสารตัวจริงมาที่อยู่บริษัทตามที่แจ้งไว้นะคะ",
    "ดัชนีความเชื่อมั่นผู้บริโภคเดือนนี้ปรับตัวดีขึ้นเล็กน้อย",
    "เดี๋ยวพรุ่งนี้เช้าผมจะโทรไปคุยรายละเอียดอีกทีนะครับ",
    "ขอบคุณสำหรับคำแนะนำดีๆ ครับ จะนำไปปรับใช้แน่นอน",
    "ระบบจะปิดปรับปรุงชั่วคราวในคืนนี้เวลาเที่ยงคืนถึงตีสี่",
    "อาหารร้านนี้อร่อยมากเลย แนะนำให้ลองไปชิมดูนะ",
    "ทางเรากำลังเร่งตรวจสอบปัญหาที่เกิดขึ้นให้อยู่ครับ",
    "ยินดีด้วยกับความสำเร็จในครั้งนี้นะคะ สู้ต่อไปค่ะ"
]

app = FastAPI(title="Stylometry ML Microservice")

ML_WORKSPACE = "/ml_workspace/models"

# ---------------------------------------------------------------------------
# Load Pre-trained Base CNN (trained offline by scripts/train_cnn_offline.py)
# ---------------------------------------------------------------------------
BASE_CNN_MODEL = None
BASE_VOCAB = None

_BASE_WEIGHTS = "/app/base_char_cnn.pth"
_BASE_VOCAB   = "/app/base_char_cnn_vocab.json"

if os.path.exists(_BASE_WEIGHTS) and os.path.exists(_BASE_VOCAB):
    try:
        with open(_BASE_VOCAB, "r", encoding="utf-8") as _f:
            _char2idx = json.load(_f)
        BASE_VOCAB = CharVocab([])
        BASE_VOCAB.char2idx = _char2idx
        BASE_CNN_MODEL = AttentionSessionCNN(len(BASE_VOCAB))
        BASE_CNN_MODEL.load_state_dict(torch.load(_BASE_WEIGHTS, map_location="cpu"))
        BASE_CNN_MODEL.eval()
        print(f"[INFO] Pre-trained base CharCNN loaded — vocab size {len(BASE_VOCAB)}")
    except Exception as _e:
        print(f"[WARN] Could not load base CharCNN: {_e}. CNN branch will use zeros.")
else:
    print("[WARN] base_char_cnn.pth not found. Run scripts/train_cnn_offline.py first. CNN branch masked to zeros.")


class PredictRequest(BaseModel):
    username: str
    messages: List[str]

class TrainRequest(BaseModel):
    messages: List[str]

@app.get("/")
def read_root():
    return {"status": "ML Service is operating (Train on Demand Orchestration)"}

@app.post("/train/{username}")
def train_user_model(username: str):
    baseline_path = os.path.join("/ml_workspace/data", f"{username}_baseline.txt")
    if not os.path.exists(baseline_path):
        raise HTTPException(status_code=400, detail="Baseline data not found")
        
    with open(baseline_path, "r", encoding="utf-8") as f:
        user_texts = [line.strip() for line in f if line.strip()]
        
    if len(user_texts) < 20:
        raise HTTPException(status_code=400, detail="Require at least 20 baseline messages.")
        
    user_dir = os.path.join(ML_WORKSPACE, username)
    os.makedirs(user_dir, exist_ok=True)
    
    pos_samples = user_texts
    labels = [1] * len(pos_samples)
    
    # Balance the dataset using Universal Background Corpus at exactly 1:1 Ratio
    neg_samples = random.choices(UNIVERSAL_BACKGROUND_CORPUS, k=len(pos_samples))
    labels.extend([0] * len(neg_samples))
    all_texts = pos_samples + neg_samples
    
    # 1. Initialize CNN & Vocab
    vocab = CharVocab(all_texts, max_size=150)
    cnn_model = AttentionSessionCNN(len(vocab))
    cnn_model.eval()
    
    cnn_features = []
    with torch.no_grad():
        for text in all_texts:
            encoded = torch.tensor([vocab.encode(text, max_len=256)], dtype=torch.long)
            feat = cnn_model([encoded], return_features=True) # (1, 128)
            cnn_features.append(feat.squeeze(0).numpy())
    cnn_features = np.array(cnn_features)
    
    # 2. Train Meta Extractor & Standardize
    meta_extractor = StylometricFeatureExtractor()
    X_meta = meta_extractor.fit_transform(all_texts)
    
    scaler = StandardScaler()
    X_meta_scaled = scaler.fit_transform(X_meta)
    
    # 3. Train TF-IDF & Stacking LR
    tfidf = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=1000, min_df=1)
    X_tfidf = tfidf.fit_transform(all_texts)
    
    stacking_lr = LogisticRegression(max_iter=1000, random_state=42)
    stacking_lr.fit(X_tfidf, labels)
    X_tfidf_prob = stacking_lr.predict_proba(X_tfidf)[:, 1].reshape(-1, 1)
    
    # 4. FUSE to 134-Dim Vector
    if BASE_CNN_MODEL is not None:
        # Use pre-trained base CNN as a feature extractor (frozen)
        base_cnn_feats = []
        with torch.no_grad():
            for text in all_texts:
                encoded = torch.tensor([BASE_VOCAB.encode(text, max_len=256)], dtype=torch.long)
                feat = BASE_CNN_MODEL([encoded], return_features=True)
                base_cnn_feats.append(feat.squeeze(0).numpy())
        cnn_features = np.array(base_cnn_feats)
        print(f"DEBUG: Real base-CNN features shape: {cnn_features.shape}")
    else:
        # Fallback: zeros until train_cnn_offline.py has been run
        cnn_features = np.zeros((len(all_texts), 128))
        print("DEBUG: CNN masked to zeros (base_char_cnn.pth not available)")
    X_combined = np.hstack((cnn_features, X_meta_scaled, X_tfidf_prob))
    print(f"DEBUG: Fusion successful! Shape: {X_combined.shape}")
    
    # 5. Train XGBoost model with balanced params
    xgb_model = XGBClassifier(
        n_estimators=100, 
        max_depth=3, 
        learning_rate=0.1,
        reg_lambda=1.0,
        scale_pos_weight=1,
        random_state=42, 
        objective='binary:logistic',
        use_label_encoder=False, 
        eval_metric="logloss"
    )
    xgb_model.fit(X_combined, labels)
    
    # 6. Save Artifacts
    with open(os.path.join(user_dir, "vocab.json"), "w") as f:
        json.dump(vocab.char2idx, f)
    torch.save(cnn_model.state_dict(), os.path.join(user_dir, "cnn.pth"))
    joblib.dump(meta_extractor, os.path.join(user_dir, "meta.pkl"))
    joblib.dump(scaler, os.path.join(user_dir, "scaler.pkl"))
    joblib.dump(tfidf, os.path.join(user_dir, "tfidf.pkl"))
    joblib.dump(stacking_lr, os.path.join(user_dir, "lr.pkl"))
    joblib.dump(xgb_model, os.path.join(user_dir, "xgb_model.pkl"))
    
    return {"status": "success", "message": f"Auto-Retraining Complete: 134-dim model for {username}"}

@app.post("/predict")
def predict(req: PredictRequest):
    user_dir = os.path.join(ML_WORKSPACE, req.username)
    vocab_path = os.path.join(user_dir, "vocab.json")
    cnn_path = os.path.join(user_dir, "cnn.pth")
    meta_path = os.path.join(user_dir, "meta.pkl")
    scaler_path = os.path.join(user_dir, "scaler.pkl")
    tfidf_path = os.path.join(user_dir, "tfidf.pkl")
    lr_path = os.path.join(user_dir, "lr.pkl")
    xgb_path = os.path.join(user_dir, "xgb_model.pkl")
    
    if not os.path.exists(xgb_path):
        return {"confidence_score": 1.0, "latest_message_confidence": 1.0, "status": "cold_start"}
        
    try:
        with open(vocab_path, "r") as f:
            char2idx = json.load(f)
        vocab = CharVocab([]) # Dummy init
        vocab.char2idx = char2idx
        
        cnn_model = AttentionSessionCNN(len(vocab))
        cnn_model.load_state_dict(torch.load(cnn_path))
        cnn_model.eval()
        
        meta_extractor = joblib.load(meta_path)
        scaler = joblib.load(scaler_path)
        tfidf = joblib.load(tfidf_path)
        stacking_lr = joblib.load(lr_path)
        xgb_model = joblib.load(xgb_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load artifacts: {e}")
        
    # Process each message individually and average the scores
    valid_msgs = [m for m in req.messages if m.strip()]
    if not valid_msgs:
        return {"confidence_score": 1.0, "latest_message_confidence": 1.0, "status": "active"}

    # Process Late Fusion for each message INDIVIDUALLY
    confidences = []
    for msg in valid_msgs:
        # 1. Deep Feature
        with torch.no_grad():
            encoded = torch.tensor([vocab.encode(msg, max_len=256)], dtype=torch.long)
            feat = cnn_model([encoded], return_features=True)
            X_deep = feat.numpy()
            
        # 2. Meta Feature
        X_meta = meta_extractor.transform([msg])
        X_meta_scaled = scaler.transform(X_meta)
        
        # 3. TF-IDF Stacking Feature
        X_tfidf = tfidf.transform([msg])
        X_tfidf_prob = stacking_lr.predict_proba(X_tfidf)[:, 1].reshape(-1, 1)
        
        # 4. Late Fusion
        X_combined = np.hstack((X_deep, X_meta_scaled, X_tfidf_prob))
        prob = xgb_model.predict_proba(X_combined)[0, 1]
        confidences.append(float(prob))
        
    confidence = float(np.mean(confidences))
    latest_conf = float(confidences[-1]) if confidences else 1.0
    
    print(f"DEBUG: Individual message confidences: {confidences}")
    print(f"DEBUG: Final Average Confidence Score for {req.username}: {confidence} | Latest: {latest_conf}")
    
    return {
        "confidence_score": confidence, 
        "latest_message_confidence": latest_conf,
        "status": "active"
    }
