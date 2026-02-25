import cv2
import os
import logging
import time
import numpy as np
import threading
from collections import deque
from dataclasses import dataclass

# Tentative d'import des librairies Hailo
# Elles sont montées depuis l'hôte dans le docker-compose
try:
    from hailo_platform import (HEF, VDevice, HailoStreamInterface, InferVStreams, ConfigureParams, InputVStreamParams, OutputVStreamParams, FormatType)
    HAILO_AVAILABLE = True
except ImportError:
    HAILO_AVAILABLE = False
    logging.warning("⚠️ Librairie 'hailo_platform' introuvable. Le NPU ne sera pas utilisé.")

# Tentative d'import LiteRT (TFLite Runtime)
try:
    import tflite_runtime.interpreter as tflite
    LITERT_AVAILABLE = True
except ImportError:
    LITERT_AVAILABLE = False
    logging.warning("⚠️ Module 'tflite_runtime' manquant. LiteRT désactivé.")

@dataclass
class InferenceStats:
    latency_ms: float = 0.0
    fps: float = 0.0
    temperature_c: float = 0.0
    throttle_factor: float = 0.0

class PerformanceMonitor:
    """Moniteur de performance industriel pour l'Edge AI."""
    def __init__(self, window_size=50):
        self.latencies = deque(maxlen=window_size)
        self.start_time = time.time()
        self.frame_count = 0
        self.last_check = time.time()
        self.current_temp = 0.0

    def update(self, latency_s):
        self.latencies.append(latency_s)
        self.frame_count += 1
        
        # Mise à jour température toutes les 5 secondes
        now = time.time()
        if now - self.last_check > 5.0:
            self.current_temp = self._read_cpu_temp()
            self.last_check = now

    def _read_cpu_temp(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return int(f.read()) / 1000.0
        except:
            return 0.0

    def get_stats(self) -> InferenceStats:
        avg_latency = (sum(self.latencies) / len(self.latencies) * 1000) if self.latencies else 0
        fps = self.frame_count / (time.time() - self.start_time) if time.time() > self.start_time else 0
        return InferenceStats(latency_ms=avg_latency, fps=fps, temperature_c=self.current_temp)

class Throttler:
    """Mécanisme de sécurité pour éviter la saturation PCIe/CPU."""
    def __init__(self, target_fps=30.0, max_temp=80.0):
        self.target_fps = target_fps
        self.max_temp = max_temp
        self.sleep_time = 1.0 / target_fps
        self.consecutive_overheat = 0

    def regulate(self, stats: InferenceStats):
        # Régulation thermique
        if stats.temperature_c > self.max_temp:
            self.consecutive_overheat += 1
            # Réduction drastique si surchauffe persistante
            factor = min(self.consecutive_overheat * 0.1, 0.5)
            time.sleep(self.sleep_time + factor)
            return factor
        else:
            self.consecutive_overheat = max(0, self.consecutive_overheat - 1)
        
        # Régulation FPS simple
        time.sleep(self.sleep_time)
        return 0.0

class VisionManager:
    def __init__(self, config: dict):
        self.config = config.get("vision", {})
        self.camera_index = self.config.get("camera_index", 0)
        self.capture_path = self.config.get("capture_path", "data/capture.jpg")
        self.use_litert = self.config.get("use_litert", False)
        
        if self.use_litert and not LITERT_AVAILABLE:
            logging.error("❌ Config demande LiteRT mais librairie absente. Installation requise: pip install tflite-runtime")

        # Config Hailo
        self.hailo_model_path = self.config.get("model_path", "models/hailo/hailo_model.hef")
        self.hailo_device = None
        self.network_group = None
        self.hef = None
        self.input_vstreams_params = None
        self.output_vstreams_params = None
        
        self.latest_detections = []
        self.running = False
        
        # Monitoring & Sécurité
        self.monitor = PerformanceMonitor()
        self.throttler = Throttler(target_fps=30.0)
        self.interpreter = None # Pour LiteRT
        
        # Initialisation
        self._init_camera()
        
        # Logique de démarrage avec Fallback
        started = False
        if self.use_litert and LITERT_AVAILABLE:
            if self._init_litert():
                started = True
            else:
                logging.warning("⚠️ LiteRT a échoué, tentative de fallback sur Hailo Native...")
        
        # Si LiteRT n'a pas démarré (ou n'était pas demandé), on tente Hailo Native
        if not started and HAILO_AVAILABLE:
            self._init_hailo()
            # On vérifie si Hailo a bien démarré
            if self.hailo_device:
                started = True
            
        if started:
            self._start_watchdog()

    def _init_camera(self):
        """Vérifie juste que la caméra est accessible sans la bloquer."""
        cap = cv2.VideoCapture(self.camera_index)
        if cap.isOpened():
            logging.info(f"✅ Caméra détectée à l'index {self.camera_index}")
            cap.release()
        else:
            logging.error(f"❌ Impossible d'accéder à la caméra {self.camera_index}")

    def _init_litert(self):
        """Initialisation du runtime LiteRT avec délégué Hailo (AOT)."""
        try:
            logging.info("🚀 Initialisation LiteRT (Google AI Edge) avec délégué NPU...")
            # Chargement du délégué Hailo (doit être présent sur le système)
            # Note: Le chemin .so dépend de l'installation HailoRT
            hailo_delegate = tflite.load_delegate('libhailo_delegate.so')
            
            # Chargement du modèle (supposé compilé ou compatible)
            # Pour Hailo, on charge souvent un .tflite qui contient les infos pour le délégué
            self.interpreter = tflite.Interpreter(
                model_path=self.hailo_model_path.replace(".hef", ".tflite"),
                experimental_delegates=[hailo_delegate]
            )
            self.interpreter.allocate_tensors()
            logging.info("✅ LiteRT Interpreter prêt.")
            return True
        except Exception as e:
            logging.error(f"❌ Échec init LiteRT: {e}")
            self.interpreter = None
            return False

    def _init_hailo(self):
        """Charge le modèle HEF sur le NPU."""
        if not os.path.exists(self.hailo_model_path):
            logging.warning(f"⚠️ Modèle Hailo introuvable : {self.hailo_model_path}")
            return

        try:
            logging.info(f"🚀 Chargement du modèle NPU : {self.hailo_model_path}")
            self.hef = HEF(self.hailo_model_path)

            # Configuration du périphérique (NPU)
            params = VDevice.create_params()
            self.hailo_device = VDevice(params)

            # Configuration du flux (Pipeline)
            configure_params = ConfigureParams.create_from_hef(hef=self.hef, interface=HailoStreamInterface.PCIe)
            self.network_groups = self.hailo_device.configure(self.hef, configure_params)
            self.network_group = self.network_groups[0]
            
            # Paramètres des flux
            self.input_vstreams_params = InputVStreamParams.make(self.network_group, format_type=FormatType.UINT8)
            self.output_vstreams_params = OutputVStreamParams.make(self.network_group, format_type=FormatType.UINT8)

            logging.info("✅ NPU Hailo initialisé et prêt à inférer.")
            
        except Exception as e:
            logging.error(f"❌ Erreur critique lors de l'init Hailo : {e}", exc_info=True)
            self.hailo_device = None

    def _start_watchdog(self):
        """Lance l'analyse continue en arrière-plan."""
        self.running = True
        thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        thread.start()
        logging.info("👁️ Watchdog visuel démarré (NPU actif en tâche de fond)")

    def _watchdog_loop(self):
        while self.running:
            start_t = time.time()
            
            if self.hailo_device or self.interpreter:
                # On capture sans sauvegarder sur disque pour la vitesse
                frame = self.capture(save=False)
                if frame is not None:
                    self.latest_detections = self.detect(frame, internal=True)
            
            # Mise à jour métriques
            latency = time.time() - start_t
            self.monitor.update(latency)
            
            # Régulation (Throttling)
            stats = self.monitor.get_stats()
            throttle = self.throttler.regulate(stats)
            
            if stats.frame_count % 100 == 0:
                logging.debug(f"📊 Stats Vision: {stats.fps:.1f} FPS, Latence: {stats.latency_ms:.1f}ms, Temp: {stats.temperature_c}°C, Throttle: {throttle}")

    def capture(self, save=True):
        """Capture une image brute (pour l'instant)."""
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            return None
        
        ret, frame = cap.read()
        cap.release()
        
        if ret and save:
            os.makedirs(os.path.dirname(self.capture_path), exist_ok=True)
            cv2.imwrite(self.capture_path, frame)
            logging.info(f"📸 Image capturée : {self.capture_path}")
            
        return frame

    def detect(self, frame, internal=False):
        """
        Lance une inférence sur le NPU.
        """
        if frame is None:
            return []
            
        # Si on appelle detect() manuellement et qu'on a déjà un résultat frais du watchdog, on le prend
        if not internal and self.latest_detections:
            # On retourne le cache pour une réponse instantanée
            return self.latest_detections
            return []

        # Routeur de backend
        if self.interpreter:
            return self._detect_litert(frame, internal)
        elif self.hailo_device:
            return self._detect_hailo_native(frame, internal)
        
        return []

    def _detect_litert(self, frame, internal):
        """Pipeline LiteRT standardisé."""
        if self.interpreter is None:
            return []

        try:
            # 1. Introspection du modèle (Input)
            input_details = self.interpreter.get_input_details()
            output_details = self.interpreter.get_output_details()
            
            input_shape = input_details[0]['shape'] # [1, H, W, C]
            h_input, w_input = input_shape[1], input_shape[2]
            input_dtype = input_details[0]['dtype']
            
            # 2. Pre-processing
            resized = cv2.resize(frame, (w_input, h_input))
            
            # Gestion Quantization vs Float
            if input_dtype == np.uint8:
                input_data = np.expand_dims(resized, axis=0)
            elif input_dtype == np.float32:
                input_data = np.expand_dims(resized, axis=0).astype(np.float32)
                input_data = input_data / 255.0
            else:
                input_data = np.expand_dims(resized, axis=0).astype(input_dtype)

            # 3. Inférence (Zero-Copy si possible via delegate)
            self.interpreter.set_tensor(input_details[0]['index'], input_data)
            self.interpreter.invoke()

            # 4. Post-processing (Détection automatique du format)
            detections = []
            
            # Cas YOLOv8 (1 sortie tensorielle [1, 4+nc, N])
            if len(output_details) == 1:
                raw_out = self.interpreter.get_tensor(output_details[0]['index'])
                detections = self._post_process_yolo(raw_out, frame.shape, (w_input, h_input), 0.5)
            
            # Cas SSD MobileNet (4 sorties: Boxes, Classes, Scores, Count)
            elif len(output_details) >= 3:
                # Heuristique standard TFLite Object Detection API
                boxes = self.interpreter.get_tensor(output_details[0]['index'])[0] # [N, 4]
                classes = self.interpreter.get_tensor(output_details[1]['index'])[0] # [N]
                scores = self.interpreter.get_tensor(output_details[2]['index'])[0] # [N]
                detections = self._post_process_ssd(boxes, classes, scores, frame.shape, 0.5)

            if not internal and detections:
                 logging.info(f"🧠 LiteRT Détections: {len(detections)} objets")

            return detections

        except Exception as e:
            if not internal:
                logging.error(f"❌ Erreur Inférence LiteRT : {e}")
            return []

    def _post_process_yolo(self, output, img_shape, input_dims, conf_thres):
        # output shape: [1, 84, 8400] (exemple COCO) -> [1, features, anchors]
        # Transpose pour avoir [1, 8400, 84]
        output = np.transpose(output, (0, 2, 1))
        data = output[0]
        
        # Optimisation numpy: filtrer par max score d'abord
        classes_scores = data[:, 4:]
        max_scores = np.max(classes_scores, axis=1)
        argmax_classes = np.argmax(classes_scores, axis=1)
        
        mask = max_scores >= conf_thres
        filtered_data = data[mask]
        filtered_scores = max_scores[mask]
        filtered_classes = argmax_classes[mask]
        
        if len(filtered_data) == 0:
            return []

        h_img, w_img = img_shape[:2]
        w_model, h_model = input_dims
        scale_x = w_img / w_model
        scale_y = h_img / h_model
        
        boxes = []
        scores = []
        class_ids = []

        for i, row in enumerate(filtered_data):
            cx, cy, w, h = row[:4]
            # Conversion coords centre -> coin haut-gauche
            x1 = int((cx - w/2) * scale_x)
            y1 = int((cy - h/2) * scale_y)
            w_scaled = int(w * scale_x)
            h_scaled = int(h * scale_y)
            
            boxes.append([x1, y1, w_scaled, h_scaled])
            scores.append(float(filtered_scores[i]))
            class_ids.append(int(filtered_classes[i]))

        # NMS (Non-Maximum Suppression) via OpenCV
        indices = cv2.dnn.NMSBoxes(boxes, scores, conf_thres, 0.45)
        
        results = []
        if len(indices) > 0:
            for i in indices.flatten():
                results.append({
                    "label": f"class_{class_ids[i]}", # TODO: Mapper avec coco.names si dispo
                    "confidence": scores[i],
                    "box": boxes[i]
                })
        return results

    def _post_process_ssd(self, boxes, classes, scores, img_shape, conf_thres):
        results = []
        h_img, w_img = img_shape[:2]
        
        for i in range(len(scores)):
            if scores[i] >= conf_thres:
                # SSD TFLite sort des boîtes normalisées [ymin, xmin, ymax, xmax]
                ymin, xmin, ymax, xmax = boxes[i]
                
                x = int(xmin * w_img)
                y = int(ymin * h_img)
                w = int((xmax - xmin) * w_img)
                h = int((ymax - ymin) * h_img)
                
                results.append({
                    "label": f"class_{int(classes[i])}",
                    "confidence": float(scores[i]),
                    "box": [x, y, w, h]
                })
        return results

    def _detect_hailo_native(self, frame, internal):
        """Pipeline Legacy HailoRT."""
        try:
            # 1. Préparation de l'image (Resize 640x640 standard YOLO)
            resized = cv2.resize(frame, (640, 640))
            input_data = np.expand_dims(resized, axis=0) # Batch size 1

            # 2. Inférence via VStreams
            with InferVStreams(self.network_group, self.input_vstreams_params, self.output_vstreams_params) as infer_pipeline:
                # Envoi
                infer_pipeline.infer(input_data)
                # Réception (Dictionnaire de numpy arrays)
                output_data = infer_pipeline.get_outputs()
            
            # 3. Analyse sommaire (Pour vérifier que ça vit)
            # output_data contient les tenseurs bruts (ex: 'yolov8_nms_postprocess')
            raw_detections = list(output_data.values())[0]
            
            # Log uniquement si ce n'est pas la boucle interne (pour éviter le spam)
            if not internal:
                logging.info(f"🧠 NPU Output shape: {raw_detections.shape}")
            
            return [{"label": "mouvement_npu", "confidence": 1.0, "raw": "ACTIVE"}]

        except Exception as e:
            if not internal: logging.error(f"❌ Erreur Inférence Hailo : {e}")
            
        return []

    def close(self):
        self.running = False
        if self.hailo_device:
            # self.hailo_device.release() # API spécifique selon version
            pass