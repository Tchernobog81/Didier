from fastapi import FastAPI, HTTPException
from orchestrator.core import Orchestrator

app = FastAPI(title="Didier Orchestrator")
didier = Orchestrator(storage_path="data/didier.db")

@app.on_event("startup")
async def startup_event():
    didier.start()

@app.get("/health")
async def health():
    return {"status": "ok", "name": "Didier"}

@app.post("/chat")
async def chat(payload: dict):
    prompt = payload.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    response = didier.agent.chat(prompt)
    return {"response": response}

@app.get("/models/search")
async def models_search(q: str):
    return didier.model_manager.search_hf(q)
