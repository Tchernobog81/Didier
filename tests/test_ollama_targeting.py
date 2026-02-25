from core.ollama_targeting import resolve_pixel_ollama_base_url


def test_resolve_pixel_ollama_from_pixel_device_ip():
    root_cfg = {
        "routing": {"pixel_ollama": {"enabled": True, "port": 11434}},
        "hardware": {"discovery": {"pixel_ip_hints": []}},
    }
    shared_state = {
        "hardware_profile": {
            "tpu": {
                "pixel_devices": [
                    {"ip": "192.168.1.50"},
                ]
            }
        }
    }
    base = resolve_pixel_ollama_base_url(root_config=root_cfg, shared_state=shared_state)
    assert base == "http://192.168.1.50:11434"


def test_resolve_pixel_ollama_from_ip_hint_when_profile_is_empty():
    root_cfg = {
        "routing": {"pixel_ollama": {"enabled": True, "port": 11434}},
        "hardware": {"discovery": {"pixel_ip_hints": ["192.168.1.50"]}},
    }
    shared_state = {"hardware_profile": {"tpu": {"pixel_devices": []}}}
    base = resolve_pixel_ollama_base_url(root_config=root_cfg, shared_state=shared_state)
    assert base == "http://192.168.1.50:11434"
