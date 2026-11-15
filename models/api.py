from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict
import joblib
import pandas as pd

# Load the existing trained model
artifact = joblib.load("clench_model.joblib")
model = artifact["model"]
features = artifact["features"]

app = FastAPI(title="OpenBCI EMG Intent Decoder", version="0.1")

class PredictionRequest(BaseModel):
    features: Dict[str, float]

@app.get("/")
def home():
    return {
        "status": "running",
        "model": "clench-random-forest-v1"
    }

@app.get("/features")
def get_features():
    return {"required_features": features}

@app.post("/predict")
def predict(request: PredictionRequest):
    missing = [
        name for name in features
        if name not in request.features
    ]

    if missing:
        raise HTTPException(
            status_code=422,
            detail={"missing_features": missing}
        )

    X = pd.DataFrame([{
        name: request.features[name]
        for name in features
    }])

    probability = float(model.predict_proba(X)[0, 1])
    prediction = int(model.predict(X)[0])

    return {
        "prediction": "CLENCH" if prediction else "RELAX",
        "clench_probability": round(probability, 4),
        "model_version": "v1"
    }
