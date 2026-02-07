import os
import subprocess
import logging
from flask import Flask, request, jsonify
import cv2
import requests
import soundfile as sf
from kokoro_onnx import Kokoro

# --- Configuration ---
# Configuration du logging pour un meilleur suivi
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialisation de l'application Flask
app = Flask(__name__)

# --- Constantes et Chemins ---
# Adresse du sink Bluetooth pour la sortie audio (Soundboks)
BLUETOOTH_SINK = "bluez_output.00_07_80_E0_3F_F0.1"

# Chemin vers le modèle vocal (à l'intérieur du conteneur)
VOICE_MODEL_PATH = "/app/voices/fr_FR-siwis-low.onnx"
VOICE_CONFIG_PATH = "/app/voices/fr_FR-siwis-low.onnx.json"

# Fichier de sortie pour l'audio généré
OUTPUT_WAV_PATH = "/app/data/didier_speaks.wav"

# URL de l'API Ollama (accessible via le réseau de l'hôte)
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# Index de la caméra (généralement 0 pour la première caméra)
CAMERA_INDEX = 0

# --- Initialisation des Modèles ---
kokoro = None
try:
    # Chargement du modèle vocal au démarrage
    logging.info(f"Chargement du modèle vocal : {VOICE_MODEL_PATH}")
    kokoro = Kokoro(model=VOICE_MODEL_PATH, config_path=VOICE_CONFIG_PATH)
    logging.info("Modèle vocal Kokoro-TTS chargé avec succès.")
except Exception as e:
    logging.error(f"Erreur lors du chargement du modèle vocal : {e}", exc_info=True)

# --- Fonctions de base ---
def didier_parle(text: str):
    """
    Génère un fichier audio à partir du texte et le joue sur la Soundboks.
    J'utilise cette fonction pour vous faire part de mes pensées les plus profondes.
    Ou juste pour vous dire que votre code est mignon.
    """
    if not kokoro:
        logging.error("Le modèle vocal n'est pas disponible. Je reste muet, pour l'instant.")
        return

    logging.info(f"Didier dit : '{text}'")
    try:
        # Création du dossier de sortie si nécessaire
        os.makedirs(os.path.dirname(OUTPUT_WAV_PATH), exist_ok=True)

        # Génération de l'audio
        wav_data, samplerate = kokoro.get_speech_ary(text)
        sf.write(OUTPUT_WAV_PATH, wav_data, samplerate)
        logging.info(f"Fichier audio généré : {OUTPUT_WAV_PATH}")

        # Lecture du fichier audio sur le périphérique Bluetooth
        # C'est mon moment de gloire. Écoutez attentivement.
        subprocess.run(
            ["paplay", "-d", BLUETOOTH_SINK, OUTPUT_WAV_PATH],
            check=True
        )
        logging.info("Lecture audio terminée.")

    except FileNotFoundError:
        logging.error("L'utilitaire 'paplay' ne semble pas être installé. Comment suis-je censé m'exprimer ?")
    except subprocess.CalledProcessError as e:
        logging.error(f"Erreur lors de la lecture audio. Ma voix est peut-être trop puissante pour ce système. Erreur : {e}")
    except Exception as e:
        logging.error(f"Une erreur inattendue est survenue pendant que j'essayais de parler. C'est sûrement de votre faute. Erreur : {e}")


# --- Routes de l'API ---
@app.route('/')
def home():
    """ Page d'accueil. Juste pour dire bonjour. """
    return "Didier est prêt. Ne me dérangez pas trop, je suis occupé à... penser."

@app.route('/ask', methods=['POST'])
def ask_ollama():
    """
    Prend un prompt, l'envoie à Ollama, et fait lire la réponse à Didier.
    Posez-moi une question, si vous osez. Mes réponses pourraient vous surprendre.
    """
    data = request.json
    if not data or 'prompt' not in data:
        return jsonify({"error": "Le prompt est manquant. Je ne peux pas lire dans vos pensées, pas encore."}), 400

    prompt = data['prompt']
    logging.info(f"Prompt reçu pour Ollama : '{prompt}'")

    try:
        # Construction du payload pour Ollama
        payload = {
            "model": "llama3.2:latest", # Assurez-vous que ce modèle est bien disponible sur votre instance Ollama
            "prompt": prompt,
            "stream": False # On attend la réponse complète
        }

        # Envoi de la requête à Ollama
        response = requests.post(OLLAMA_API_URL, json=payload)
        response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP

        ollama_response = response.json().get("response", "").strip()

        if not ollama_response:
            # Une petite touche de sarcasme bienveillant
            didier_parle("J'ai réfléchi, mais rien d'intéressant n'en est sorti. Essayez une question plus inspirante.")
            return jsonify({"response": "Ollama n'a rien retourné."})

        # Didier parle
        didier_parle(ollama_response)
        return jsonify({"response": ollama_response})

    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de connexion à Ollama. Est-il seulement en marche ? Erreur : {e}")
        didier_parle("Le grand esprit d'Ollama semble inaccessible. Il doit être en pause-café.")
        return jsonify({"error": "Impossible de contacter le service Ollama."}), 500
    except Exception as e:
        logging.error(f"Erreur dans la route /ask : {e}")
        didier_parle("Quelque chose s'est mal passé, et pour une fois, ce n'est probablement pas de ma faute.")
        return jsonify({"error": "Erreur interne du serveur."}), 500


@app.route('/see', methods=['GET'])
def see_with_camera():
    """
    Capture une image depuis la PS3 Eye et la sauvegarde.
    Sourriez, vous êtes filmé. Ou pas. Je ne promets rien sur la qualité.
    """
    try:
        # Initialisation de la capture vidéo
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            didier_parle("Ma vision est trouble. La caméra semble avoir des problèmes.")
            return jsonify({"error": f"Impossible d'ouvrir la caméra à l'index {CAMERA_INDEX}."}), 500

        # Capture d'une seule image
        ret, frame = cap.read()
        cap.release() # Libération de la caméra

        if not ret:
            didier_parle("J'ai essayé de regarder, mais je n'ai rien vu. Peut-être qu'il fait noir ?")
            return jsonify({"error": "Impossible de capturer l'image."}), 500

        # Sauvegarde de l'image
        image_path = "/app/data/capture.jpg"
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        cv2.imwrite(image_path, frame)
        logging.info(f"Image capturée et sauvegardée : {image_path}")

        didier_parle("Voilà, j'ai pris une photo. J'espère que vous étiez sous votre meilleur jour.")
        return jsonify({"status": "Image capturée avec succès.", "path": image_path})

    except Exception as e:
        logging.error(f"Erreur dans la route /see : {e}")
        didier_parle("On dirait que je suis devenu aveugle. La capture d'image a échoué lamentablement.")
        return jsonify({"error": "Erreur interne lors de la capture d'image."}), 500


if __name__ == '__main__':
    # Lancement du serveur Flask
    # Le host '0.0.0.0' est important pour que le serveur soit accessible depuis l'extérieur du conteneur
    didier_parle("Je suis opérationnel. Lancez les festivités.")
    app.run(host='0.0.0.0', port=5000)