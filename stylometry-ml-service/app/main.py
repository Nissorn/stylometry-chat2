from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import random

app = FastAPI(title="Stylometry ML Microservice")

class PredictRequest(BaseModel):
    username: str
    messages: List[str]

@app.get("/")
def read_root():
    return {"status": "ML Service is running"}

@app.post("/predict")
def predict(req: PredictRequest):
    # PLACEHOLDER LOGIC: return random confidence between 0.1 and 0.9
    confidence = random.uniform(0.1, 0.9)
    # Just to simulate sometimes good, sometimes bad confidence
    return {"confidence_score": confidence}
