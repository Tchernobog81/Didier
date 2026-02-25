from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from orchestrator.core import Orchestrator
import os

app = FastAPI(title="Didier Orchestrator", version="4.0.0")
didier = Orchestrator(storage_path="data/didier.db")

@app.on_event("startup")
async def startup_event():
    didier.start()

@app.get("/health")
async def health():
    return {"status": "ok", "name": "Didier", "version": "4.0.0"}

@app.get("/")
async def index():
    return {"Didier": "v4.0.0 - Optimized & Async", "endpoints": ["/health", "/chat", "/ask", "/speak", "/see"]}

@app.post("/chat")
async def chat(payload: dict):
    prompt = payload.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    response = didier.agent.chat(prompt)
    return {"response": response}

@app.post("/ask")
async def ask(payload: dict):
    """Alias pour /chat avec logging activé."""
    prompt = payload.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    response = didier.agent.chat(prompt)
    return {"response": response}

@app.get("/models/search")
async def models_search(q: str):
    return didier.model_manager.search_hf(q)

# --- TTS & Audio ---

@app.post("/speak")
async def speak(payload: dict):
    """Fait parler Didier (TTS)."""
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Text required")
    
    success = didier.audio_manager.speak(text)
    if not success:
        raise HTTPException(status_code=500, detail="TTS failed")
    return {"status": "ok", "text": text}

@app.post("/speak-and-chat")
async def speak_and_chat(payload: dict):
    """Pipeline complet: User Text -> LLM -> TTS Audio."""
    prompt = payload.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    
    # 1. Cognition
    response = didier.agent.chat(prompt)
    
    # 2. Synthèse vocale
    didier.audio_manager.speak(response)
    
    return {"response": response, "audio_played": True}

# --- Vision & Capture ---

@app.get("/see")
async def see():
    """Capture une image et retourne son chemin."""
    frame = didier.vision_manager.capture(save=True)
    if frame is None:
        raise HTTPException(status_code=500, detail="Camera capture failed")
    
    path = didier.vision_manager.capture_path
    return {"status": "ok", "path": path}

@app.get("/vision/detect")
async def vision_detect():
    """Lance une détection sur le NPU."""
    frame = didier.vision_manager.capture(save=False)
    if frame is None:
        raise HTTPException(status_code=500, detail="Camera capture failed")
    
    detections = didier.vision_manager.detect(frame)
    return {"detections": detections}

# --- Maintenance & Diagnostic ---

@app.post("/clean")
async def clean():
    """Protocole 'Chambre Propre' - Maintenance système."""
    import subprocess
    import os
    
    results = []
    
    # Nettoyage Docker
    try:
        subprocess.run(["docker", "system", "df", "-f"], capture_output=True)
        results.append("docker_clean")
    except Exception as e:
        results.append(f"docker_error: {e}")
    
    # Nettoyage logs (> 10MB)
    log_dir = "logs"
    if os.path.exists(log_dir):
        for f in os.listdir(log_dir):
            path = os.path.join(log_dir, f)
            if os.path.isfile(path) and os.path.getsize(path) > 10_000_000:
                os.remove(path)
                results.append(f"cleared: {f}")
    
    # Nettoyage captures anciennes (> 7 jours)
    capture_dir = "data"
    if os.path.exists(capture_dir):
        import time
        now = time.time()
        for f in os.listdir(capture_dir):
            if f.startswith("capture"):
                path = os.path.join(capture_dir, f)
                if os.path.isfile(path) and (now - os.path.getmtime(path)) > 7*86400:
                    os.remove(path)
                    results.append(f"old_capture_removed: {f}")
    
    return {"status": "ok", "actions": results}
