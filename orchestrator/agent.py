import random
from typing import Any

class DidierAgent:
    def __init__(self, memory, model_manager):
        self.memory = memory
        self.model_manager = model_manager
        # persona config
        self.name = "Didier"
        self.personality = {
            "tone": "sarcastic",
            "distance": "polite"
        }

    def _persona_prefix(self):
        # a short persona hint for LLM prompts (if/when you call one)
        return "[Didier - sarcastic & distanced persona]"

    def chat(self, prompt: str) -> str:
        # Save user prompt
        try:
            self.memory.save_message("user", prompt)
        except Exception:
            pass

        # Build a short persona / system prompt for models
        sys_prompt = self._persona_prefix()
        full_prompt = f"{sys_prompt}\nHuman: {prompt}\nDidier:"

        # Try to get a response from the model manager (Ollama by default)
        try:
            model_resp = self.model_manager.generate(full_prompt)
            reply = model_resp.strip() if model_resp else "Désolé, pas de réponse du modèle."
        except Exception:
            # fallback local replies when model call fails
            replies = [
                "Oh chouette, encore une question existentielle. Bon, voici la réponse — sommaire mais honnête.",
                "Je pourrais répondre, mais je préfère te voir essayer d'y penser tout seul d'abord.",
                "Très bon point. Malheureusement, ton réseau n'est pas aussi rapide que tes attentes."
            ]
            reply = random.choice(replies) + " (" + prompt[:120] + ")"

        # store assistant reply
        try:
            self.memory.save_message("assistant", reply)
        except Exception:
            pass
        return f"{self._persona_prefix()} {reply}"
