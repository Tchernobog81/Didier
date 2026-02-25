import os
import threading
import queue
import logging
import subprocess
import soundfile as sf
import numpy as np
import time
from kokoro_onnx import Kokoro

class AudioService:
    _instance_lock = threading.Lock()
    _instance = None

    @classmethod
    def get_instance(cls, config):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(config)
            return cls._instance

    def __init__(self, config):
        self.config = config
        maxsize = int(config.get("audio_queue_maxsize", 8)) if isinstance(config, dict) else 8
        self.queue = queue.Queue(maxsize=max(1, maxsize))
        self.sink = config.get("bluetooth", {}).get("sink_name", "bluez_output.00_07_80_E0_3F_F0.1")
        self.subprocess_timeout_s = 2.0
        
        # Chemins codés en dur pour l'instant, à externaliser plus tard si besoin
        self.voice_model_path = "/app/voices/fr_FR-siwis-low.onnx"
        self.voice_config_path = "/app/voices/fr_FR-siwis-low.onnx.json"
        self.output_path = "/app/data/didier_speaks.wav"
        
        self.kokoro = None
        self.running = True
        self.current_process = None
        
        # Démarrage du worker en arrière-plan
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        logging.info(f"AudioService: Initialisation du modèle vocal en arrière-plan... (Timestamp: {time.time()})")
        try:
            self.kokoro = Kokoro(model=self.voice_model_path, config_path=self.voice_config_path)
            logging.info("AudioService: Modèle Kokoro chargé avec succès.")
        except Exception as e:
            logging.error(f"AudioService: Échec du chargement du modèle : {e}")

        while self.running:
            try:
                # Attente d'une tâche (timeout pour permettre l'arrêt propre si besoin)
                task = self.queue.get(timeout=1)
                task_type = task.get("type")
                
                if task_type == "speak":
                    self._process_speak(task["text"])
                elif task_type == "beep":
                    self._process_beep()
                    
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"AudioService: Erreur dans le worker : {e}")

    def _process_speak(self, text):
        if not self.kokoro:
            logging.warning("AudioService: Modèle non prêt, parole ignorée.")
            return
        
        try:
            logging.info(f"Didier dit : '{text}'")
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            wav_data, samplerate = self.kokoro.get_speech_ary(text)
            sf.write(self.output_path, wav_data, samplerate)
            
            # Utilisation de Popen pour pouvoir interrompre la lecture (Stop d'urgence)
            self.current_process = subprocess.Popen(["paplay", "-d", self.sink, self.output_path])
            try:
                self.current_process.wait(timeout=self.subprocess_timeout_s)
            except subprocess.TimeoutExpired:
                self.current_process.terminate()
                self.current_process.wait(timeout=0.5)
            self.current_process = None
        except Exception as e:
            logging.error(f"AudioService: Erreur lors de la lecture audio : {e}")

    def _process_beep(self):
        try:
            # Génération d'un beep simple (La 440Hz)
            sample_rate = 22050; duration = 0.2
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = 0.5 * np.sin(2 * np.pi * 440 * t)
            beep_path = "/app/data/beep.wav"
            sf.write(beep_path, tone, sample_rate)
            self.current_process = subprocess.Popen(["paplay", "-d", self.sink, beep_path])
            try:
                self.current_process.wait(timeout=self.subprocess_timeout_s)
            except subprocess.TimeoutExpired:
                self.current_process.terminate()
                self.current_process.wait(timeout=0.5)
            self.current_process = None
        except Exception as e:
            logging.error(f"AudioService: Erreur lors du beep : {e}")

    def speak(self, text):
        """Ajoute une demande de parole à la file d'attente."""
        self._enqueue_task({"type": "speak", "text": text})

    def beep(self):
        """Ajoute une demande de beep à la file d'attente."""
        self._enqueue_task({"type": "beep"})

    def _enqueue_task(self, task):
        try:
            self.queue.put_nowait(task)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(task)
            except queue.Full:
                logging.warning("AudioService: Queue saturée, tâche abandonnée.")

    def clear(self):
        """STOP D'URGENCE : Vide la file d'attente et coupe la parole immédiatement."""
        # 1. Vider la file d'attente
        with self.queue.mutex:
            self.queue.queue.clear()
        
        # 2. Tuer le processus audio en cours s'il existe
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            logging.warning("AudioService: Parole interrompue d'urgence.")
