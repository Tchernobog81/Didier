import os
import asyncio
import subprocess
import logging
import threading
import atexit
import time
import shutil
from multiprocessing import Manager
from flask import Flask, request, jsonify
import cv2
import requests
import soundfile as sf
from kokoro_onnx import Kokoro

try:
    from core.api_impl import AsyncAudioService as CoreAsyncAudioService
    _ASYNC_AUDIO_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    CoreAsyncAudioService = None
    _ASYNC_AUDIO_IMPORT_ERROR = str(exc)

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
OLLAMA_API_URL = "http://localhost:11435/api/generate"

# Index de la caméra (généralement 0 pour la première caméra)
CAMERA_INDEX = 0

# --- Initialisation des Modèles ---
kokoro = None
_audio_loop = None
_audio_thread = None
_async_audio_service = None
_async_audio_enabled = False
_shared_state_manager = Manager()
_shared_state = _shared_state_manager.dict()
_shared_state["audio"] = {"available": False, "level_percent": None, "queue_depth": 0, "ts": 0.0}
_shared_state["npu"] = {"device": False, "utilization": None, "ts": 0.0}
_shared_state["ts"] = 0.0
_shared_state_loop = None
_shared_state_thread = None
_shared_state_stop = threading.Event()
_shared_state_future = None


def _audio_loop_runner(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _collect_shared_state_snapshot() -> tuple[dict, dict]:
    now = time.time()
    queue_depth = 0
    if _async_audio_enabled and _async_audio_service is not None:
        try:
            queue_depth = int(_async_audio_service.queue.qsize())
        except Exception:
            queue_depth = 0
    audio_state = {
        "available": bool(shutil.which("paplay")),
        "level_percent": None,
        "queue_depth": queue_depth,
        "ts": now,
    }
    npu_state = {
        "device": os.path.exists("/dev/hailo0"),
        "utilization": None,
        "ts": now,
    }
    return audio_state, npu_state


async def _shared_state_updater() -> None:
    while not _shared_state_stop.is_set():
        audio_state, npu_state = await asyncio.to_thread(_collect_shared_state_snapshot)
        _shared_state["audio"] = audio_state
        _shared_state["npu"] = npu_state
        _shared_state["ts"] = time.time()
        await asyncio.sleep(0.5)  # 2 Hz


def _start_shared_state_updater() -> bool:
    global _shared_state_loop, _shared_state_thread, _shared_state_future
    try:
        _shared_state_stop.clear()
        _shared_state_loop = asyncio.new_event_loop()
        _shared_state_thread = threading.Thread(
            target=_audio_loop_runner, args=(_shared_state_loop,), daemon=True
        )
        _shared_state_thread.start()
        _shared_state_future = asyncio.run_coroutine_threadsafe(
            _shared_state_updater(), _shared_state_loop
        )
        logging.info("SharedState updater démarré (2 Hz).")
        return True
    except Exception as exc:
        logging.error("Démarrage SharedState updater échoué: %s", exc, exc_info=True)
        return False


def _shutdown_shared_state() -> None:
    global _shared_state_loop, _shared_state_thread, _shared_state_future
    _shared_state_stop.set()
    if _shared_state_future is not None:
        try:
            _shared_state_future.cancel()
        except Exception:
            pass
        _shared_state_future = None
    if _shared_state_loop is not None:
        try:
            _shared_state_loop.call_soon_threadsafe(_shared_state_loop.stop)
        except Exception:
            pass
    if _shared_state_thread is not None:
        try:
            _shared_state_thread.join(timeout=1.5)
        except Exception:
            pass
    if _shared_state_loop is not None:
        try:
            _shared_state_loop.close()
        except Exception:
            pass
    _shared_state_loop = None
    _shared_state_thread = None
    try:
        _shared_state_manager.shutdown()
    except Exception:
        pass


async def _create_async_audio_service():
    config = {"bluetooth": {"sink_name": BLUETOOTH_SINK}}
    return CoreAsyncAudioService(config)


def _init_async_audio_service() -> bool:
    global _audio_loop, _audio_thread, _async_audio_service, _async_audio_enabled
    if CoreAsyncAudioService is None:
        logging.warning(
            "AsyncAudioService indisponible (%s), fallback Kokoro local.",
            _ASYNC_AUDIO_IMPORT_ERROR,
        )
        return False
    try:
        _audio_loop = asyncio.new_event_loop()
        _audio_thread = threading.Thread(
            target=_audio_loop_runner, args=(_audio_loop,), daemon=True
        )
        _audio_thread.start()
        future = asyncio.run_coroutine_threadsafe(
            _create_async_audio_service(), _audio_loop
        )
        _async_audio_service = future.result(timeout=8)
        _async_audio_enabled = True
        logging.info("AsyncAudioService initialisé depuis core.api_impl.")
        return True
    except Exception as exc:
        logging.error("Init AsyncAudioService échouée: %s", exc, exc_info=True)
        _async_audio_enabled = False
        _async_audio_service = None
        if _audio_loop:
            try:
                _audio_loop.call_soon_threadsafe(_audio_loop.stop)
            except Exception:
                pass
            try:
                _audio_loop.close()
            except Exception:
                pass
        _audio_loop = None
        _audio_thread = None
        return False


def _shutdown_async_audio_service() -> None:
    global _audio_loop, _audio_thread, _async_audio_service, _async_audio_enabled
    if _async_audio_service is not None and _audio_loop is not None:
        try:
            fut = asyncio.run_coroutine_threadsafe(
                _async_audio_service.clear(), _audio_loop
            )
            fut.result(timeout=2)
        except Exception:
            pass
    if _audio_loop is not None:
        try:
            _audio_loop.call_soon_threadsafe(_audio_loop.stop)
        except Exception:
            pass
    if _audio_thread is not None:
        try:
            _audio_thread.join(timeout=1)
        except Exception:
            pass
    _async_audio_service = None
    _async_audio_enabled = False
    _audio_loop = None
    _audio_thread = None


if not _init_async_audio_service():
    try:
        # Chargement du modèle vocal local au démarrage (fallback)
        logging.info(f"Chargement du modèle vocal : {VOICE_MODEL_PATH}")
        kokoro = Kokoro(model=VOICE_MODEL_PATH, config_path=VOICE_CONFIG_PATH)
        logging.info("Modèle vocal Kokoro-TTS chargé avec succès.")
    except Exception as e:
        logging.error(f"Erreur lors du chargement du modèle vocal : {e}", exc_info=True)

atexit.register(_shutdown_async_audio_service)
_start_shared_state_updater()
atexit.register(_shutdown_shared_state)

# --- Fonctions de base ---
def didier_parle(text: str):
    """
    Génère un fichier audio à partir du texte et le joue sur la Soundboks.
    J'utilise cette fonction pour vous faire part de mes pensées les plus profondes.
    Ou juste pour vous dire que votre code est mignon.
    """
    if _async_audio_enabled and _async_audio_service is not None and _audio_loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(
                _async_audio_service.speak(text), _audio_loop
            )
            return
        except Exception as exc:
            logging.error("Echec AsyncAudioService, fallback local: %s", exc)

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


@app.route('/shared-state', methods=['GET'])
def shared_state():
    audio_state = dict(_shared_state.get("audio", {}))
    npu_state = dict(_shared_state.get("npu", {}))
    return jsonify(
        {
            "status": "ok",
            "ts": _shared_state.get("ts", 0.0),
            "audio": audio_state,
            "npu": npu_state,
        }
    )


if __name__ == '__main__':
    # Lancement du serveur Flask
    # Le host '0.0.0.0' est important pour que le serveur soit accessible depuis l'extérieur du conteneur
    didier_parle("Je suis opérationnel. Lancez les festivités.")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5003)))
