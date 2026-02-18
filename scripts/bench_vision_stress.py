#!/usr/bin/env python3
import time
import sys
import os
import logging

# Ajout du dossier parent au path pour importer orchestrator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from orchestrator.vision import VisionManager

# Configuration des logs pour voir les infos du VisionManager
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    print("🔥 BENCHMARK STRESS VISION & THROTTLING")
    print("=======================================")
    
    # 1. Initialisation
    print("[1/4] Initialisation du VisionManager...")
    # On utilise une config minimale. Le VisionManager va tenter de charger Hailo/Caméra.
    config = {
        "vision": {
            "camera_index": 0,
            "model_path": "models/hailo/hailo_model.hef",
            "use_litert": False
        }
    }
    
    try:
        vm = VisionManager(config)
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        return

    # Vérification si le thread tourne
    if not vm.running:
        print("⚠️  Le thread Vision ne semble pas démarré (pas de caméra ?).")
        print("    Tentative de forçage en mode simulation...")
        vm.running = True
        import threading
        # Mock des méthodes hardware si absentes
        vm.capture = lambda save=False: "dummy_frame" 
        vm.detect = lambda frame, internal=False: [{"label": "sim", "confidence": 0.99}]
        t = threading.Thread(target=vm._watchdog_loop, daemon=True)
        t.start()
    
    # 2. Phase de chauffe
    print("[2/4] Phase de chauffe (5s)...")
    time.sleep(5)
    stats = vm.monitor.get_stats()
    initial_temp = stats.temperature_c
    initial_fps = stats.fps
    print(f"   -> Température initiale: {initial_temp}°C")
    print(f"   -> FPS stable: {initial_fps:.2f}")

    # 3. Simulation Surchauffe (Test Throttler)
    print("\n[3/4] TEST DU THROTTLER (Simulation Surchauffe)")
    print("   -> Abaissement artificiel du seuil de température...")
    
    original_max_temp = vm.throttler.max_temp
    # On fixe le seuil 5°C sous la température actuelle pour déclencher la sécurité
    fake_threshold = max(20.0, initial_temp - 5.0)
    vm.throttler.max_temp = fake_threshold
    
    print(f"   -> Seuil réglé à {fake_threshold}°C (Temp actuelle: {initial_temp}°C)")
    print("   -> Observation de la chute des FPS (10s)...")
    
    for i in range(10):
        time.sleep(1)
        s = vm.monitor.get_stats()
        # On force une lecture de temp si le monitor ne l'a pas encore fait (il le fait toutes les 5s)
        current_t = s.temperature_c
        print(f"   T+{i+1}s | FPS: {s.fps:.2f} | Temp: {current_t}°C | Seuil: {vm.throttler.max_temp}°C")

    # 4. Retour à la normale
    print("\n[4/4] Retour à la normale")
    vm.throttler.max_temp = original_max_temp
    print(f"   -> Seuil restauré à {original_max_temp}°C")
    print("   -> Observation de la remontée des FPS (5s)...")
    
    for i in range(5):
        time.sleep(1)
        s = vm.monitor.get_stats()
        print(f"   T+{i+1}s | FPS: {s.fps:.2f}")

    vm.close()
    print("\n✅ Benchmark terminé.")

if __name__ == "__main__":
    main()