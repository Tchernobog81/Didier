import os
from .agent import DidierAgent
from .model_manager import ModelManager
from .memory import Memory

class Orchestrator:
    def __init__(self, storage_path="data/didier.db"):
        os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)
        self.memory = Memory(storage_path)
        self.model_manager = ModelManager(cache_dir="data/models")
        self.agent = DidierAgent(memory=self.memory, model_manager=self.model_manager)

    def start(self):
        # load memory, warm caches, etc.
        self.memory.connect()
        self.model_manager.load_index()
        # can run background tasks here (thread loop for retrieval/learning)
        return True
