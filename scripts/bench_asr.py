#!/usr/bin/env python3
import argparse
import csv
import os
import struct
import subprocess
import time
import wave
from pathlib import Path


def try_import_soundfile():
    try:
        import soundfile as sf  # type: ignore

        return sf
    except Exception:
        return None


def wav_duration(path: Path) -> float:
    sf = try_import_soundfile()
    if sf:
        info = sf.info(str(path))
        return float(info.frames) / float(info.samplerate)
    import wave

    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
    return float(frames) / float(rate)


def downmix_to_mono(path: Path) -> None:
    sf = try_import_soundfile()
    if not sf:
        return
    data, sr = sf.read(str(path), dtype="float32")
    if hasattr(data, "ndim") and data.ndim > 1:
        data = data.mean(axis=1)
        sf.write(str(path), data, sr)


def ensure_sample(args: argparse.Namespace) -> Path:
    sample_path = Path(args.sample_path)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    if sample_path.exists() and sample_path.stat().st_size > 0:
        return sample_path
    if args.no_record:
        # Generate a short silent sample to avoid grabbing the mic.
        frames = int(args.sample_rate * args.sample_seconds)
        with wave.open(str(sample_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(args.sample_rate)
            silence = struct.pack("<h", 0) * frames
            wf.writeframes(silence)
        return sample_path
    cmd = [
        "arecord",
        "-D",
        args.alsa_device,
        "-f",
        "S16_LE",
        "-c",
        str(args.channels),
        "-r",
        str(args.sample_rate),
        "-d",
        str(args.sample_seconds),
        str(sample_path),
    ]
    subprocess.run(cmd, check=True)
    downmix_to_mono(sample_path)
    return sample_path


def list_models(models_dir: Path) -> list[Path]:
    if not models_dir.exists():
        return []
    models = [p for p in models_dir.glob("ggml-*.bin") if p.is_file()]
    models.sort(key=lambda p: p.stat().st_size)
    return models


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alsa-device", default="hw:2,0")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=4)
    parser.add_argument("--sample-seconds", type=int, default=3)
    parser.add_argument("--sample-path", default="data/bench.wav")
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--models-dir", default="models")
    parser.add_argument("--whisper-bin", default="bin/whisper.cpp")
    parser.add_argument("--lang", default="fr")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", default="logs/bench_asr.csv")
    parser.add_argument("--max-models", type=int, default=0)
    args = parser.parse_args()

    try:
        os.nice(10)
    except Exception:
        pass

    try:
        sample = ensure_sample(args)
    except FileNotFoundError as exc:
        print(str(exc))
        return 2
    duration = max(0.001, wav_duration(sample))

    models = list_models(Path(args.models_dir))
    if args.max_models and args.max_models > 0:
        models = models[: args.max_models]
    if not models:
        print("No ggml-*.bin models found.")
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output.exists()

    with output.open("a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                [
                    "ts",
                    "model",
                    "seconds",
                    "rtf",
                    "threads",
                    "beam_size",
                    "best_of",
                ]
            )
        for model in models:
            cmd = [
                str(Path(args.whisper_bin)),
                "-m",
                str(model),
                "-f",
                str(sample),
                "-l",
                args.lang,
                "-otxt",
                "-np",
                "-nt",
                "-bs",
                "1",
                "-bo",
                "1",
                "-nf",
                "-t",
                str(args.threads),
            ]
            start = time.time()
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as exc:
                print(f"Model {model.name} failed: {exc}")
                continue
            elapsed = time.time() - start
            rtf = elapsed / duration
            writer.writerow(
                [
                    int(time.time()),
                    model.name,
                    f"{elapsed:.3f}",
                    f"{rtf:.3f}",
                    args.threads,
                    1,
                    1,
                ]
            )
            txt_path = sample.with_suffix(".wav.txt")
            if txt_path.exists():
                try:
                    txt_path.unlink()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
