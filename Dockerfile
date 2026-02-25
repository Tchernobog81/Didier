# Utilisation d'une image Python 3.13 slim optimisée pour le Raspberry Pi (ARM64)
FROM python:3.13-slim

# Métadonnées de l'image
LABEL maintainer="Florian"
LABEL description="Image Docker pour Didier-Brain, l'orchestrateur intelligent."

# Définition du dossier de travail dans le conteneur
WORKDIR /app

# Installation des dépendances système requises
# - Audio: alsa-utils, pulseaudio-utils, libpulse0, pipewire
# - Vision: libgl1, libglib2.0-0, libsm6, libxext6, libxrender1
# - HailoRT: dépendances de base (libusb)
# - Utilitaires: wget, curl pour le script de setup
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils \
    pulseaudio-utils \
    libpulse0 \
    pipewire \
    pipewire-pulse \
    libpipewire-0.3-0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libusb-1.0-0 \
    libv4l-0 \
    v4l-utils \
    ffmpeg \
    python3-opencv \
    bluez \
    psmisc \
    wget \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Permet à whisper.cpp de trouver ses bibliothèques partagées
ENV LD_LIBRARY_PATH=/app/bin

# Copie du reste de l'application (sera aussi mappé par volume pour le dev)
COPY . .

# Commande pour lancer l'API (contrôle via HTTP)
CMD ["uvicorn", "core.api:app", "--host", "0.0.0.0", "--port", "5000"]
