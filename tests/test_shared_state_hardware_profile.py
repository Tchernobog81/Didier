from core import shared_state


def test_update_hardware_profile_only_writes_on_change(tmp_path, monkeypatch):
    state_path = tmp_path / "shared_state.json"
    lock_path = tmp_path / "shared_state.lock"
    monkeypatch.setattr(shared_state, "STATE_PATH", state_path)
    monkeypatch.setattr(shared_state, "LOCK_PATH", lock_path)

    base_profile = {
        "schema": "didier.hardware_profile.v1",
        "source": "network_discovery_v1",
        "host": {"hostname": "didier-pi"},
        "cpu": {"logical_cores": 4},
        "ram": {"total_bytes": 1024},
        "npu": {"available": True, "device_count": 1, "devices": ["/dev/hailo0"]},
        "tpu": {"pixel_detected": False, "pixel_count": 0, "pixel_devices": []},
        "network_devices": [],
        "discovery": {"enable_arp": True, "enable_mdns": True},
        "scanned_at": 100.0,
    }

    first = shared_state.update_hardware_profile(base_profile, only_on_change=True)
    second = shared_state.update_hardware_profile(
        {**base_profile, "scanned_at": 200.0},
        only_on_change=True,
    )

    assert first["changed"] is True
    assert second["changed"] is False

    state = shared_state.read_state()
    profile = state.get("hardware_profile", {})
    assert profile.get("npu", {}).get("available") is True
    assert profile.get("host", {}).get("hostname") == "didier-pi"
