# Rollback Edge Workers

Ce document décrit la baseline actuelle:
- point d'entrée unique `didier-api.service` sur `5010`
- worker ASR dédié `didier-asr.service` sur `5014`
- legacy `run_didier.service` et `didier.service` archivés/désactivés
- déploiement production: **100% systemd natif**

## 1) Rollback git (2 commits edge)

Lister les 2 derniers commits edge :

```bash
git log --oneline -n 5
```

Rollback non destructif recommandé :

```bash
git revert --no-edit <commit_2_hardening_checks> <commit_1_workers_proxy>
```

Alternative (retour exact à un SHA précédent, destructif sur les changements non commités) :

```bash
git reset --hard <sha_avant_edge>
```

## 2) Stop/disable des workers edge systemd

```bash
sudo systemctl stop didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service
sudo systemctl disable didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service
```

Vérifier :

```bash
systemctl --no-pager --full status didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service
```

## 3) Relancer le point d'entrée unifié (5010)

```bash
sudo systemctl disable --now run_didier.service didier.service || true
sudo systemctl enable didier-api.service
sudo systemctl restart didier-api.service
```

Validation rapide :

```bash
curl -sS http://127.0.0.1:5010/health
curl -sS http://127.0.0.1:5014/health
curl -sS http://127.0.0.1:5010/device-status
curl -sS http://127.0.0.1:5010/docker/diagram
```

## 4) Rollback d'urgence vers legacy 5003 (temporaire)

```bash
sudo systemctl disable --now didier-api.service || true
sudo systemctl unmask run_didier.service 2>/dev/null || true
sudo systemctl enable run_didier.service
sudo systemctl restart run_didier.service

curl -sS http://127.0.0.1:5003/health
```

## 5) Rollback OpenClaw natif -> wrapper (sans couper l'API 5010)

Objectif: désactiver `openclaw.service` (Node natif) et repasser en mode wrapper Python piloté par `didier-openclaw-bridge.service`.

### a) Désactiver le mode natif dans la config Didier

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("config/config.json")
d = json.loads(p.read_text(encoding="utf-8"))
d.setdefault("openclaw", {})["native_enabled"] = False
d["openclaw"]["wrapper_heartbeat_enabled"] = True
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("updated", p)
PY
```

### b) Forcer le bridge en mode wrapper (`DIDIER_OPENCLAW_NATIVE_ONLY=0`)

```bash
sudo mkdir -p /etc/systemd/system/didier-openclaw-bridge.service.d
cat <<'EOF' | sudo tee /etc/systemd/system/didier-openclaw-bridge.service.d/wrapper.conf >/dev/null
[Service]
Environment=DIDIER_OPENCLAW_NATIVE_ONLY=0
EOF
```

### c) Stopper OpenClaw natif et redémarrer bridge + API

```bash
sudo systemctl disable --now openclaw.service
sudo systemctl daemon-reload
sudo systemctl restart didier-openclaw-bridge.service didier-api.service
```

### d) Validation wrapper

```bash
curl -sS http://127.0.0.1:5010/agent/metrics?timeout_s=2
systemctl is-active didier-api.service didier-openclaw-bridge.service openclaw.service
```

Attendu:
- `didier-api.service` = `active`
- `didier-openclaw-bridge.service` = `active`
- `openclaw.service` = `inactive`

### e) Revenir ensuite au natif

```bash
sudo rm -f /etc/systemd/system/didier-openclaw-bridge.service.d/wrapper.conf
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("config/config.json")
d = json.loads(p.read_text(encoding="utf-8"))
d.setdefault("openclaw", {})["native_enabled"] = True
d["openclaw"]["wrapper_heartbeat_enabled"] = False
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("updated", p)
PY
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw.service
sudo systemctl restart didier-openclaw-bridge.service didier-api.service
```
