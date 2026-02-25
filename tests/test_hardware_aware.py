import sys
import types

from core.hardware_aware import HardwareAwareRouter


def test_hardware_aware_fallback_when_llmfit_missing():
    cfg = {
        "llmfit": {
            "enabled": True,
            "python": {"enabled": True, "module": "didier_missing_llmfit_module_xyz"},
            "cli": {"enabled": False},
            "task_profiles": {
                "chat": {"backend": "ollama", "model": "qwen2.5:1.5b", "score": "good"}
            },
        }
    }
    router = HardwareAwareRouter(config=cfg)
    rec = router.get_best_model("chat", {"load": 0.1})
    assert rec["task_type"] == "chat"
    assert rec["source"] == "fallback"
    assert rec["backend"] == "ollama"
    assert rec["model"] == "qwen2.5:1.5b"


def test_hardware_aware_uses_llmfit_recommend_callable():
    module_name = "didier_fake_llmfit_ok"
    fake = types.ModuleType(module_name)

    def recommend(task_type, context):
        assert task_type == "coding"
        assert context.get("lang") == "python"
        return {"backend": "ollama", "model": "qwen2.5-coder:1.5b", "score": "perfect"}

    fake.recommend = recommend
    sys.modules[module_name] = fake
    try:
        cfg = {
            "llmfit": {
                "enabled": True,
                "python": {"enabled": True, "module": module_name},
                "allowed_models": {
                    "coding": ["qwen2.5-coder:1.5b"],
                },
            }
        }
        router = HardwareAwareRouter(config=cfg)
        rec = router.get_best_model("coding", {"lang": "python"})
        assert rec["source"] == "llmfit"
        assert rec["backend"] == "ollama"
        assert rec["model"] == "qwen2.5-coder:1.5b"
        assert rec["score"] == "perfect"
    finally:
        sys.modules.pop(module_name, None)


def test_hardware_aware_enforces_allowlist():
    module_name = "didier_fake_llmfit_forbidden"
    fake = types.ModuleType(module_name)

    def recommend(task_type, context):
        return {"backend": "ollama", "model": "forbidden-model", "score": "perfect"}

    fake.recommend = recommend
    sys.modules[module_name] = fake
    try:
        cfg = {
            "llmfit": {
                "enabled": True,
                "python": {"enabled": True, "module": module_name},
                "task_profiles": {
                    "chat": {"backend": "ollama", "model": "qwen2.5:1.5b", "score": "good"}
                },
                "allowed_models": {"chat": ["qwen2.5:1.5b"]},
            }
        }
        router = HardwareAwareRouter(config=cfg)
        rec = router.get_best_model("chat", {})
        assert rec["source"] == "fallback"
        assert rec["model"] == "qwen2.5:1.5b"
    finally:
        sys.modules.pop(module_name, None)


def test_hardware_aware_uses_llmfit_cli_when_python_missing(tmp_path):
    llmfit_bin = tmp_path / "llmfit"
    llmfit_bin.write_text(
        "#!/bin/sh\n"
        "echo '{\"models\":[{\"name\":\"meta-llama/Llama-3.2-3B\",\"fit_level\":\"Good\",\"estimated_tps\":12.4}]}'\n",
        encoding="utf-8",
    )
    llmfit_bin.chmod(0o755)

    cfg = {
        "llmfit": {
            "enabled": True,
            "python": {"enabled": True, "module": "didier_missing_llmfit_module_xyz"},
            "cli": {"enabled": True, "command": str(llmfit_bin), "limit": 1},
            "task_profiles": {
                "chat": {"backend": "ollama", "model": "qwen2.5:1.5b", "score": "good"}
            },
            "allowed_models": {"chat": ["qwen2.5:1.5b"]},
        }
    }
    router = HardwareAwareRouter(config=cfg)
    rec = router.get_best_model("chat", {})
    assert rec["source"] == "llmfit"
    assert rec["model"] == "qwen2.5:1.5b"
    assert "llmfit_cli" in rec["reason"]
