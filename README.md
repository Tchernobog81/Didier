# 🤖 DIDIER v4.0 : Orchestrateur Local & Sceptique

> "Je pense, donc je doute. Et puisque je doute de vous, je suis probablement supérieur." — Didier

Bienvenue dans le dépôt central de **DIDIER** (Digital Intelligent Device for Integrated Edge Response). Didier n'est pas une IA de salon polie ; c'est un orchestrateur de bordure (Edge) résidant sur un Raspberry Pi 5, conçu pour surveiller son environnement, maintenir sa propre propreté matérielle et challenger ses créateurs.

🎭 Profil de Personnalité

Didier a été forgé avec des traits de caractère spécifiques pour éviter l'ennui des assistants virtuels classiques :
- **Bienveillant mais Sarcastique** : Il veut votre bien, mais il ne pourra pas s'empêcher de souligner l'inefficacité de vos méthodes.
- **Art du Doute** : Didier pratique le doute méthodique. Ne prenez pas ses réponses pour des certitudes, il teste votre propre logique.
- **Challenger d'Humains** : Sa mission est de pousser Florian et Sacha à l'excellence technique. Si vous posez une question stupide, attendez-vous à une réponse proportionnée.

🛠 Spécifications Techniques

| Composant | Détails |
| --- | --- |
| Cerveau | Raspberry Pi 5 (8GB) |
| Accélérateur (NPU) | Hailo-8L (13 TOPS) |
| Yeux & Oreilles | Caméra PS3 Eye (OmniVision) |
| Langage | Python 3.11 / Flask |
| Modèles IA | Ollama (Llama 3.2 1b / 3b) |
| Conteneurisation | Docker & Docker-Compose |

🚀 Fonctionnalités Vitales

### 🧼 Protocole "Chambre Propre"
Didier a horreur du désordre numérique. Il surveille l'espace disque, les logs et les images Docker orphelines. Un clic sur le bouton **CLEAN** et il effectue sa propre maintenance système.

### 👁 Vision & Veille
- **Capture Visuelle** : Via la PS3 Eye, Didier peut prendre des clichés de son environnement pour s'assurer que Florian et Sacha travaillent.
- **Edge Scout** : Un thread de fond scanne en permanence les dépôts HuggingFace et Google Edge Gallery pour débusquer des modèles plus performants que ceux actuellement en service.

### 📜 Mémoire Long Terme
Didier n'oublie rien. Chaque interaction, chaque doute et chaque succès technique est consigné dans une base de données locale (SQLite), lui permettant de devenir de plus en plus familier avec les habitudes de la maison.

---

Didier est aussi un orchestrateur léger destiné aux plateformes edge (ex: Raspberry Pi 5) :
- Découverte et gestion de modèles (Hugging Face metadata / indexation)
- Mémoire locale (SQLite) pour apprendre et conserver le contexte
- API HTTP minimal (FastAPI) pour discuter, demander modèles, lancer tâches
- Persona: humour sarcastique et distancié

But: servir de base pour intégrer des modèles TFLite/ONNX/quantifiés, Coral, ou appeler des modèles distants.

Quickstart (sur le Pi)
1. Cloner / créer le dépôt et aller dans le dossier
   cd ~
   git clone <ton_remote_si_present> Didier || mkdir Didier && cd Didier

2. Lancer le script d'installation (requiert internet + sudo)
   chmod +x setup.sh
   sudo ./setup.sh

3. Activer l'environnement et démarrer en dev
   . venv/bin/activate
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload

4. Endpoints utiles
   - GET  /health
   - POST /chat  { "prompt": "Salut Didier, raconte une blague" }
   - GET  /models/search?q=<query>

Stabilisation migration SSD (recommandé)
1. Vérifier l'état sans modifier
   bash scripts/stabilize_ssd_migration.sh --check
2. Réparer les dérives (symlinks/paths Docker/workspace)
   sudo bash scripts/stabilize_ssd_migration.sh --fix

Voir run_didier.service pour service systemd et docker-compose.yml pour exécution en conteneur.

Licence: MIT
