from kokoro_onnx import Kokoro
import soundfile as sf
import subprocess
import os
import time

# --- CONFIGURATION DES CHEMINS ---
BASE_VOICES = "/home/tchernobog/workspace/Didier/voices"
MODEL_PATH = os.path.join(BASE_VOICES, "kokoro-v0.19.onnx")
VOICES_PATH = os.path.join(BASE_VOICES, "voices.json")
OUTPUT_FILE = "/home/tchernobog/workspace/Didier/premier_discours.wav"

# --- NOM DE L'ENCEINTE (On utilise le nom qui a marché en terminal) ---
SINK_NAME = "bluez_output.00_07_80_E0_3F_F0.1"

def parler_didier():
    print("🧠 Didier charge son cerveau vocal...")
    
    if not os.path.exists(MODEL_PATH):
        print(f"❌ Erreur : Modèle introuvable ici : {MODEL_PATH}")
        return

    # 1. Génération
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    texte = "Florian, si tu entends ça, c'est que j'ai enfin pris le contrôle de la Soun-de-boks. Sacha, prépare-toi, l'orchestrateur est en ligne."
    
    print("🎤 Synthèse de la voix en cours (2026 Edition)...")
    start_time = time.time()
    samples, sample_rate = kokoro.create(texte, voice='af_bella', speed=1.0)
    print(f"✅ Voix générée en {time.time() - start_time:.2f} secondes.")
    
    # 2. Sauvegarde
    sf.write(OUTPUT_FILE, samples, sample_rate)
    
    # 3. Lecture FORCÉE sur la Soundboks
    print(f"🔊 Envoi du flux vers {SINK_NAME}...")
    # On ajoute explicitement le -d (device) comme dans ton test terminal
    result = subprocess.run(["paplay", "-d", SINK_NAME, OUTPUT_FILE])
    
    if result.returncode == 0:
        print("🎉 Succès ! Didier a parlé.")
    else:
        print("❌ Échec de la lecture audio.")

if __name__ == "__main__":
    parler_didier()