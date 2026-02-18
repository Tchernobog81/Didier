# TODO - Checklist Récapitulatoire Didier v4.0

## 📋 Progression
- [x] Tag git créé : `didier-pre-analyse-2026-02-12`
- [ ] VERSION mis à jour
- [ ] core/api_impl.py migré vers asyncio
- [ ] PLAN_UNIFICATION.md exécuter
- [ ] Monitoring 2Hz activé
- [ ] Stabilisation SSD validée
- [ ] Scripts AOT optimisés
- [ ] AudioManager (Kokoro) intégré
- [ ] Endpoint /vision/status-secondary ajouté
- [ ] Didier redémarré sur http://192.168.1.47:5003/

## 📌 Tâches Détaillées

### 🔴 CRITIQUE - Migration Async api_impl.py
- [ ] Remplacer subprocess.run() par _run_cmd_async()
- [ ] Migrer pactl, fuser, v4l2-ctl vers asyncio
- [ ] Tester endpoints /actuators

### 🔴 CRITIQUE - Unification Flask→FastAPI
- [ ] Exécuter PLAN_UNIFICATION.md
- [ ] Supprimer didier_orchestrator.py
- [ ] Valider routes migrées

### 🟠 URGENT - Monitoring 2Hz
- [ ] Activer _monitor_system()
- [ ] Optimiser /metrics (pas d'appels arecord)
- [ ] Valider performance CPU < 5%

### 🟠 URGENT - Stabilisation SSD
- [ ] Exécuter stabilize_ssd_migration.sh --check
- [ ] Corriger dérives si présentes

### 🟡 IMPORTANT - Compilation AOT Hailo
- [ ] Exécuter compile_aot.py
- [ ] Valider scripts/hailo_stub_100fps.py

### 🟡 IMPORTANT - AudioManager Kokoro
- [ ] Intégrer orchestrator/audio.py
- [ ] Tester endpoint /speak

### 🟢 BONUS - Vision Status Secondary
- [ ] Endpoint /vision/status-secondary actif
- [ ] Validation CPU < 1%

---

**Créé le** : 2026-02-12
