import os
import json
import logging
from .agent import DidierAgent
from .model_manager import ModelManager
from .memory import Memory
from .audio import AudioManager
from .vision import VisionManager

class Orchestrator:
    def __init__(self, storage_path="data/didier.db", config_path="config/config.json"):
        # Chargement de la configuration
        self.config = {}
        try:
            with open(config_path, "r") as f:
                self.config = json.load(f)
        except Exception as e:
            logging.error(f"❌ Impossible de charger la config depuis {config_path}: {e}")

        os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)
        
        self.memory = Memory(storage_path)
        self.model_manager = ModelManager(config=self.config, cache_dir="data/models")
        self.audio_manager = AudioManager(self.config)
        self.vision_manager = VisionManager(self.config)
        
        self.agent = DidierAgent(self.memory, self.model_manager, self.audio_manager, self.vision_manager)

    def start(self):
        # load memory, warm caches, etc.
        self.memory.connect()
        self.model_manager.load_index()
        # can run background tasks here (thread loop for retrieval/learning)
        return True
