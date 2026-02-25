from core import backend_routing as routing


def test_choose_backend_prefers_pixel_for_light_prompt(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "llama3.2:3b",
            "provider": "llmfit",
            "source": "llmfit",
            "score": "perfect",
            "reason": f"task={task_type}",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {"available": True, "device_count": 1},
            "tpu": {"pixel_detected": True, "pixel_count": 1},
        }
    }
    result = routing.choose_backend("salut didier", "chat", shared_state=state)
    assert result["preferred_backend"] == "pixel_tpu"
    assert result["execution_backend"] in {"local_ollama", "pixel_ollama"}
    assert result["fallback_active"] is True
    assert result["recommended_model"] == "llama3.2:3b"


def test_choose_backend_prefers_hailo_for_vision(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "yolov8s_hailo8l.hef",
            "provider": "llmfit",
            "source": "llmfit",
            "score": "good",
            "reason": "vision route",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {"available": True, "device_count": 1},
            "tpu": {"pixel_detected": False, "pixel_count": 0},
        }
    }
    result = routing.choose_backend("detecte les formes", "vision", shared_state=state)
    assert result["preferred_backend"] == "pi_hailo_vision"
    assert result["execution_backend"] == "pi_hailo_vision"
    assert result["route_hint"] == "vision_worker"


def test_choose_backend_uses_picobot_for_react_task(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "qwen2.5:1.5b",
            "provider": "llmfit",
            "source": "fallback",
            "score": "good",
            "reason": "task orchestration",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {"available": True, "device_count": 1},
            "tpu": {"pixel_detected": True, "pixel_count": 1},
        }
    }
    result = routing.choose_backend("allume la lumiere", "react_task", shared_state=state)
    assert result["preferred_backend"] == "picobot_bridge"
    assert result["execution_backend"] == "picobot_bridge"
    assert result["fallback_active"] is False


def test_choose_backend_fallbacks_to_local_without_accelerator(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "qwen2.5:1.5b",
            "provider": "llmfit",
            "source": "fallback",
            "score": "good",
            "reason": "no accelerator",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {"available": False, "device_count": 0},
            "tpu": {"pixel_detected": False, "pixel_count": 0},
        }
    }
    result = routing.choose_backend("explique moi ce log", "chat", shared_state=state)
    assert result["preferred_backend"] == "local_ollama"
    assert result["execution_backend"] == "local_ollama"
    assert result["fallback_active"] is False


def test_choose_backend_respects_configured_prompt_threshold(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "qwen2.5:1.5b",
            "provider": "llmfit",
            "source": "llmfit",
            "score": "good",
            "reason": "threshold check",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {"available": False, "device_count": 0},
            "tpu": {"pixel_detected": True, "pixel_count": 1, "pixel_devices": []},
        }
    }
    cfg = {"routing": {"light_prompt": {"max_chars": 12, "max_words": 3}}}
    result = routing.choose_backend(
        "phrase volontairement trop longue pour rester legere",
        "chat",
        shared_state=state,
        routing_config=cfg,
    )
    assert result["preferred_backend"] == "local_ollama"
    assert result["execution_backend"] == "local_ollama"
    assert result["fallback_active"] is False


def test_choose_backend_supports_custom_task_alias(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "yolov8s_hailo8l.hef",
            "provider": "llmfit",
            "source": "llmfit",
            "score": "good",
            "reason": "custom alias",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {"available": True, "device_count": 1, "type": "hailo"},
            "tpu": {"pixel_detected": False, "pixel_count": 0},
        }
    }
    cfg = {"routing": {"task_aliases": {"inspect": "vision"}}}
    result = routing.choose_backend(
        "inspecte la scene",
        "inspect",
        shared_state=state,
        routing_config=cfg,
    )
    assert result["task_type"] == "vision"
    assert result["preferred_backend"] == "pi_hailo_vision"
    assert result["npu_supported"] is True


def test_choose_backend_blocks_unsupported_npu(monkeypatch):
    monkeypatch.setattr(
        routing,
        "get_best_model",
        lambda task_type, context: {
            "model": "yolov8s_hailo8l.hef",
            "provider": "llmfit",
            "source": "llmfit",
            "score": "good",
            "reason": "unsupported npu gate",
        },
    )
    state = {
        "hardware_profile": {
            "npu": {
                "available": True,
                "device_count": 1,
                "type": "hailo",
                "devices": ["/dev/hailo0"],
            },
            "tpu": {"pixel_detected": False, "pixel_count": 0},
        }
    }
    cfg = {
        "routing": {
            "supported_devices": {"npu": ["myriad"], "tpu": ["pixel"]},
            "allow_unknown_devices": False,
        }
    }
    result = routing.choose_backend(
        "detecte les formes",
        "vision",
        shared_state=state,
        routing_config=cfg,
    )
    assert result["preferred_backend"] == "local_ollama"
    assert result["execution_backend"] == "local_ollama"
    assert result["npu_supported"] is False
