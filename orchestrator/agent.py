import random
import logging
from typing import Any

class DidierAgent:
    def __init__(self, memory, model_manager, audio_manager=None, vision_manager=None):
        self.memory = memory
        self.model_manager = model_manager
        self.audio_manager = audio_manager
        self.vision_manager = vision_manager
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

        # 1. Gestion de la Vision (Déclencheur simple par mot-clé)
        vision_context = ""
        if self.vision_manager:
            keywords = ["regarde", "vois", "photo", "image", "see", "look"]
            if any(k in prompt.lower() for k in keywords):
                logging.info("👀 Didier ouvre les yeux (Vision demandée)...")
                frame = self.vision_manager.capture(save=True)
                if frame is not None:
                    # Appel au NPU
                    detections = self.vision_manager.detect(frame)
                    det_str = "Rien de spécial."
                    if detections:
                        det_str = f"Objets détectés via NPU: {len(detections)} (Flux actif)."
                    vision_context = f"\n[Système: Photo prise. Analyse NPU: {det_str}]"
                else:
                    vision_context = "\n[Système: Échec de la capture caméra.]"

        # Build a short persona / system prompt for models
        sys_prompt = self._persona_prefix()
        full_prompt = f"{sys_prompt}{vision_context}\nHuman: {prompt}\nDidier:"

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
            
        # 2. Synthèse Vocale (TTS)
        if self.audio_manager:
            self.audio_manager.speak(reply)
            
        return reply
