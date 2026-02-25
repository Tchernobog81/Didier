import os
import httpx
from huggingface_hub import HfApi

class ModelManager:
    def __init__(self, config=None, cache_dir="data/models"):
        self.cache_dir = cache_dir
        self.config = config or {}
        os.makedirs(self.cache_dir, exist_ok=True)
        self.api = HfApi()
        self.index = []

    def load_index(self):
        # placeholder: could load cached metadata from disk
        self.index = []

    def search_hf(self, query, limit=10):
        # search models on Hugging Face (metadata only)
        hits = self.api.list_models(filter=f"{query}", sort="lastModified", limit=limit)
        # return lightweight metadata
        return [{"modelId": m.modelId, "tags": m.tags, "downloads": getattr(m, 'downloads', None)} for m in hits]

    def generate(self, prompt: str, model: str = None, timeout: int = None) -> str:
        """Call a local Ollama instance to generate a completion.

        Uses OLLAMA_URL env var if set, otherwise defaults to http://ollama:11434.
        Returns the text response or raises an exception on failure.
        """
        # Config extraction
        ollama_conf = self.config.get("ollama", {})
        target_model = model or ollama_conf.get("model", "llama3.2:1b")
        
        # Priorité : Config JSON > Env Var > Défaut
        config_url = ollama_conf.get("base_url")
        env_url = os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_HOST")
        url = config_url or env_url or "http://127.0.0.1:11434"
        
        # Paramètres d'inférence optimisés pour le Pi 5
        final_timeout = timeout or ollama_conf.get("timeout_seconds", 120)
        num_predict = ollama_conf.get("num_predict", 100) # Limite la verbosité pour sauver le CPU
        temperature = ollama_conf.get("temperature", 0.4)

        endpoint = f"{url}/api/generate"
        try:
            payload = {
                "model": target_model, 
                "prompt": prompt, 
                "stream": False,
                "options": {
                    "num_predict": num_predict,
                    "temperature": temperature
                }
            }
            resp = httpx.post(endpoint, json=payload, timeout=final_timeout)
            resp.raise_for_status()
            data = resp.json()
            # didier_orchestrator returns {"response": "..."}
            if isinstance(data, dict):
                return data.get("response") or data.get("output") or str(data)
            return str(data)
        except Exception as e:
            # bubble up for the caller to handle fallback
            raise

    def download_model(self, model_id, local_name=None):
        # WARNING: downloading full transformer models may be heavy for a Pi.
        # This function should be implemented with care: choose small quantized models.
        raise NotImplementedError("Implement model download per target runtime (onnx/tflite).")
