from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    from core import api as api_module

    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    orchestrator = api_module._require_orchestrator()
    vocal = orchestrator.get_tentacle("vocal")
    if not vocal:
        raise HTTPException(status_code=503, detail="vocal tentacle not loaded")
    await vocal.speak(text)
    return {"status": "queued"}


@router.post("/music/play")
async def music_play(payload: dict[str, Any]) -> dict[str, Any]:
    from core import api as api_module

    prompt = str(payload.get("prompt", "")).strip() or "musique"
    orchestrator = api_module._require_orchestrator()
    music = orchestrator.get_tentacle("music")
    if not music:
        raise HTTPException(status_code=503, detail="music tentacle not loaded")
    await music.play(prompt)
    return {"status": "queued", "prompt": prompt}


@router.post("/audio/test")
async def audio_test() -> dict[str, Any]:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    sink = orchestrator.config.get("bluetooth.sink_name", "")
    path = api_module.Path("data/soundboks_test.wav")
    try:
        import numpy as np

        sample_rate = 22050
        segments = [
            (0.12, 1.0),
            (0.08, 0.8),
            (0.12, 0.6),
        ]
        audio = np.zeros(0, dtype=np.float32)
        for duration, gain in segments:
            n = int(sample_rate * duration)
            t = np.linspace(0, duration, n, False)
            noise = np.random.uniform(-1, 1, n).astype(np.float32)
            tone = np.sin(2 * np.pi * (500 + 200 * np.exp(-t * 8)) * t).astype(
                np.float32
            )
            envelope = np.exp(-t * 12).astype(np.float32)
            bark = gain * envelope * (0.6 * noise + 0.4 * tone)
            audio = np.concatenate([audio, bark, np.zeros(int(sample_rate * 0.05))])
        audio = np.clip(audio, -1.0, 1.0)
        api_module.sf.write(str(path), audio, sample_rate)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate test audio")

    cmd = ["paplay"]
    if sink:
        cmd += ["-d", sink]
    cmd.append(str(path))
    try:
        await api_module.asyncio.to_thread(api_module.subprocess.run, cmd, check=True)
    except Exception:
        raise HTTPException(status_code=500, detail="paplay failed")
    return {"status": "played", "sink": sink}


@router.post("/ask")
async def ask(payload: dict[str, Any]) -> dict[str, Any]:
    from core import api as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    brain = orchestrator.get_tentacle("brain")
    if not brain:
        raise HTTPException(status_code=503, detail="brain tentacle not loaded")
    clean_prompt, expert_model, expert_system, _expert = api_module._resolve_expert_prompt(
        prompt, orchestrator.config
    )
    try:
        api_module.update_status(
            thinking=True,
            state="THINKING",
            last_prompt=clean_prompt,
            last_prompt_at=api_module.time.time(),
        )
        response = await brain.generate(
            clean_prompt, model_override=expert_model, system_override=expert_system
        )
        api_module.update_status(
            thinking=False,
            state="IDLE",
            last_response=response,
            last_response_at=api_module.time.time(),
        )
    except Exception as exc:
        api_module.update_status(thinking=False, state="IDLE", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {"response": response}


@router.post("/coding")
async def coding(payload: dict[str, Any]) -> dict[str, Any]:
    from core import api as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    model = orchestrator.config.get("coding.model", orchestrator.config.get("ollama.model"))
    num_predict = orchestrator.config.get("coding.num_predict", 400)
    temperature = orchestrator.config.get("coding.temperature", 0.2)
    system_prompt = orchestrator.config.get("coding.system_prompt", "").strip()

    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nUser: {prompt}\nAssistant:"

    payload_data = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    keep_alive = orchestrator.config.get("ollama.keep_alive", None)
    if keep_alive:
        payload_data["keep_alive"] = keep_alive
    url = f"{base_url}/api/generate"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {"response": str(data.get("response", "")).strip()}


@router.get("/ollama/models")
async def ollama_models() -> dict[str, Any]:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    url = f"{base_url}/api/tags"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return data


@router.get("/asr/status")
async def asr_status() -> dict[str, Any]:
    from core import api as api_module

    return api_module._read_asr_status()


@router.post("/ask-and-speak")
async def ask_and_speak(payload: dict[str, Any]) -> dict[str, Any]:
    from core import api as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    brain = orchestrator.get_tentacle("brain")
    vocal = orchestrator.get_tentacle("vocal")
    music = orchestrator.get_tentacle("music")
    if not brain:
        raise HTTPException(status_code=503, detail="brain tentacle not loaded")
    clean_prompt, expert_model, expert_system, _expert = api_module._resolve_expert_prompt(
        prompt, orchestrator.config
    )
    if music and api_module._is_music_prompt(prompt):
        await music.play(prompt)
        response = "Musique lancée."
        if vocal:
            await vocal.speak(response)
        return {"response": response, "audio": bool(vocal), "music": True}
    try:
        api_module.update_status(
            thinking=True,
            state="THINKING",
            last_prompt=clean_prompt,
            last_prompt_at=api_module.time.time(),
        )
        response = await brain.generate(
            clean_prompt, model_override=expert_model, system_override=expert_system
        )
        api_module.update_status(
            thinking=False,
            last_response=response,
            last_response_at=api_module.time.time(),
        )
    except Exception as exc:
        api_module.update_status(thinking=False, state="IDLE", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    audio_ok = False
    if vocal:
        await vocal.speak(response)
        audio_ok = True
    else:
        api_module.update_status(state="IDLE")
    return {"response": response, "audio": audio_ok}
