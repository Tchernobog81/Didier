# Rollback Edge Workers

Ce document décrit un rollback rapide vers un mode legacy 5003 uniquement.

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
sudo systemctl stop didier-api.service didier-vision.service didier-brain.service didier-audio.service
sudo systemctl disable didier-api.service didier-vision.service didier-brain.service didier-audio.service
```

Vérifier :

```bash
systemctl --no-pager --full status didier-api.service didier-vision.service didier-brain.service didier-audio.service
```

## 3) Relancer uniquement le legacy 5003

```bash
sudo systemctl enable run_didier.service
sudo systemctl restart run_didier.service
```

Validation rapide :

```bash
curl -sS http://127.0.0.1:5003/health
curl -sS http://127.0.0.1:5003/device-status
curl -sS http://127.0.0.1:5003/docker/diagram
```
