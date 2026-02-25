import os
import logging
import subprocess
import soundfile as sf
from kokoro_onnx import Kokoro

class AudioManager:
    def __init__(self, config: dict):
        self.config = config.get("tts", {})
        self.model_path = self.config.get("model_path", "models/tts/kokoro-v1.0.onnx")
        self.voices_path = self.config.get("voices_path", "models/tts/voices-v1.0.bin")
        self.output_path = self.config.get("output_path", "data/didier_speaks.wav")
        self.bluetooth_sink = config.get("bluetooth", {}).get("sink_name", "bluez_output.00_07_80_E0_3F_F0.1")
        
        self.kokoro = None
        self._init_tts()

    def _init_tts(self):
        if not os.path.exists(self.model_path) or not os.path.exists(self.voices_path):
            logging.error(f"❌ Modèles TTS introuvables : {self.model_path}")
            return

        try:
            logging.info(f"🗣️ Chargement du modèle TTS Kokoro...")
            self.kokoro = Kokoro(self.model_path, self.voices_path)
            logging.info("✅ TTS chargé.")
        except Exception as e:
            logging.error(f"❌ Erreur chargement TTS: {e}")

    def speak(self, text: str):
        """Génère l'audio et le joue."""
        if not self.kokoro:
            logging.warning("TTS non disponible, je reste muet.")
            return False

        if not text:
            return False

        logging.info(f"🔊 Didier dit : '{text}'")
        
        try:
            # 1. Génération
            # Le modèle Kokoro ONNX attend (text, voice_name)
            # 'af_bella' est souvent le défaut, ou 'af_sarah', 'am_michael' etc.
            # On utilise une voix par défaut si non spécifiée
            wav = self.kokoro.create(text, voice="af_bella", speed=1.0, lang="en-us")
            
            # Sauvegarde
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            sf.write(self.output_path, wav, 24000)
            
            # 2. Lecture
            self._play_audio(self.output_path)
            return True

        except Exception as e:
            logging.error(f"❌ Erreur parole : {e}")
            return False

    def _play_audio(self, file_path):
        """Joue un fichier WAV via paplay sur le sink Bluetooth."""
        cmd = ["paplay", file_path]
        
        # Si un sink spécifique est configuré, on l'utilise
        if self.bluetooth_sink:
            cmd.extend(["-d", self.bluetooth_sink])
            
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            logging.warning(f"⚠️ Echec lecture sur {self.bluetooth_sink}, tentative sur défaut.")
            try:
                subprocess.run(["paplay", file_path], check=True)
            except Exception as e:
                logging.error(f"❌ Impossible de jouer le son : {e}")
        except FileNotFoundError:
            logging.error("❌ 'paplay' non trouvé. PulseAudio est-il installé ?")