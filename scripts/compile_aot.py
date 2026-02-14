#!/usr/bin/env python3
"""
Compilation AOT Edge pour Didier.

- Compile des modèles ONNX/TFLite vers HEF via `hailo_compile` quand disponible.
- Prépare le runtime (vérif assets Kokoro + warm-up Ollama optionnel).
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [AOT-COMPILER] - %(levelname)s - %(message)s",
)


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        return 1, str(exc)
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode, output


def _compile_with_hailo(source: Path, output: Path, target: str) -> bool:
    if shutil.which("hailo_compile") is None:
        logging.error("`hailo_compile` introuvable dans PATH.")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    attempts = [
        ["hailo_compile", str(source), "-o", str(output), "--target", target],
        ["hailo_compile", "--model", str(source), "--output", str(output), "--hw-arch", target],
        ["hailo_compile", str(source), "--output", str(output)],
    ]
    for cmd in attempts:
        rc, out = _run(cmd)
        if rc == 0:
            logging.info("Compilation OK: %s -> %s", source, output)
            return True
        logging.warning("Echec commande (%s): %s", " ".join(cmd), out[:500])
    return False


def _default_hef_path(source: Path) -> Path:
    return source.with_suffix(".hef")


def _pick_source_for_hef(vision_dirs: list[Path]) -> Path | None:
    preferred = [
        "yolov8n_fp16.onnx",
        "yolov8n.onnx",
        "yolov8n.tflite",
        "yolov5n.onnx",
        "yolov5n.tflite",
    ]
    for vision_dir in vision_dirs:
        for name in preferred:
            candidate = vision_dir / name
            if candidate.exists():
                return candidate
    for vision_dir in vision_dirs:
        for candidate in sorted(vision_dir.glob("*.onnx")):
            return candidate
    for vision_dir in vision_dirs:
        for candidate in sorted(vision_dir.glob("*.tflite")):
            return candidate
    return None


def _warm_ollama(base_url: str, model: str) -> bool:
    payload = json.dumps(
        {
            "model": model,
            "prompt": "bonjour",
            "stream": False,
            "options": {"num_predict": 1, "temperature": 0.0},
        }
    ).encode("utf-8")
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            if resp.status >= 400:
                logging.error("Warm-up Ollama échoué (status=%s).", resp.status)
                return False
        logging.info("Warm-up Ollama OK (%s).", model)
        return True
    except (urlerror.URLError, TimeoutError) as exc:
        logging.error("Warm-up Ollama échoué: %s", exc)
        return False


def _check_kokoro_assets(tts_cfg: dict) -> bool:
    model_path = Path(str(tts_cfg.get("model_path", ""))).expanduser()
    voices_path = Path(str(tts_cfg.get("voices_path", ""))).expanduser()
    config_path = Path(str(tts_cfg.get("config_path", ""))).expanduser()
    ok = True
    for label, path in (
        ("tts.model_path", model_path),
        ("tts.voices_path", voices_path),
        ("tts.config_path", config_path),
    ):
        if not path.exists():
            logging.error("Asset manquant: %s -> %s", label, path)
            ok = False
        else:
            logging.info("Asset OK: %s -> %s", label, path)
    return ok


def _compile_from_config(config_path: Path, force: bool, warm_ollama_enabled: bool) -> int:
    if not config_path.exists():
        logging.error("Config introuvable: %s", config_path)
        return 2
    data = json.loads(config_path.read_text(encoding="utf-8"))
    vision_cfg = data.get("vision", {}) if isinstance(data, dict) else {}
    tts_cfg = data.get("tts", {}) if isinstance(data, dict) else {}
    ollama_cfg = data.get("ollama", {}) if isinstance(data, dict) else {}

    overall_ok = True
    _check_kokoro_assets(tts_cfg)

    hef_target = Path(str(vision_cfg.get("model_path", "models/hailo/hailo_model.hef")))
    if hef_target.suffix.lower() != ".hef":
        logging.warning("vision.model_path n'est pas un .hef (%s), compilation ignorée.", hef_target)
    else:
        source = _pick_source_for_hef(
            [Path("models/vision"), Path("/mnt/didier_ssd/didier/models/vision")]
        )
        if source is None:
            logging.warning("Aucune source ONNX/TFLite trouvée dans models/vision.")
            overall_ok = False
        elif hef_target.exists() and not force:
            logging.info("HEF déjà présent: %s (utiliser --force pour recompiler)", hef_target)
        else:
            ok = _compile_with_hailo(source, hef_target, target="hailo8l")
            overall_ok = overall_ok and ok

    if warm_ollama_enabled:
        base_url = str(ollama_cfg.get("base_url", "http://127.0.0.1:11434"))
        model = str(ollama_cfg.get("model", "")).strip()
        if model:
            overall_ok = _warm_ollama(base_url, model) and overall_ok
        else:
            logging.warning("ollama.model vide, warm-up ignoré.")

    return 0 if overall_ok else 1


def _compile_single_model(model: Path, output: Path | None, target: str, force: bool) -> int:
    if not model.exists():
        logging.error("Modèle introuvable: %s", model)
        return 2
    if model.suffix.lower() == ".hef":
        logging.info("Le modèle source est déjà un HEF: %s", model)
        return 0
    out = output if output else _default_hef_path(model)
    if out.exists() and not force:
        logging.info("HEF déjà présent: %s (utiliser --force pour recompiler)", out)
        return 0
    return 0 if _compile_with_hailo(model, out, target=target) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Didier AOT Compiler")
    parser.add_argument("--model", help="Chemin du modèle source (.onnx/.tflite)")
    parser.add_argument("--output", help="Chemin de sortie .hef")
    parser.add_argument("--target", default="hailo8l", help="Architecture cible hailo_compile")
    parser.add_argument("--from-config", default="config/config.json", help="Config JSON Didier")
    parser.add_argument("--force", action="store_true", help="Force la recompilation")
    parser.add_argument(
        "--warm-ollama",
        action="store_true",
        help="Fait un warm-up Ollama depuis la config",
    )
    args = parser.parse_args()

    if args.model:
        return _compile_single_model(
            model=Path(args.model),
            output=Path(args.output) if args.output else None,
            target=args.target,
            force=args.force,
        )
    return _compile_from_config(
        config_path=Path(args.from_config),
        force=args.force,
        warm_ollama_enabled=args.warm_ollama,
    )


if __name__ == "__main__":
    sys.exit(main())
