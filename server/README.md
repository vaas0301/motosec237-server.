# MOTOSEC 237 — Serveur EN LIGNE (v0.2)

API FastAPI + SQLite (dev). **Pas de serveur local Wi-Fi** : l'appli
Flutter appelle ce serveur par internet via une seule `BASE_URL`
configurable. Voir `docs/DEPLOIEMENT-EN-LIGNE.md` pour la mise en ligne
et `docs/ARCHITECTURE.md` pour les choix justifiés.

## Lancer en dev (test uniquement, pas un mode produit)

```bash
cd server
python3 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt
MOTOSEC_PAIRING_CODE=123456 ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
curl http://127.0.0.1:8000/health
```

## Tests

```bash
../.venv/bin/python -m pytest -v
```

## Endpoints (v0.2)

`GET /health`, `GET /config`, `POST /devices/register`,
`POST /auth/otp/request`, `POST /auth/otp/verify`, `POST /sync`,
`GET/POST /rides`, `GET /rides/{id}`, `POST /drivers/{id}/position`,
`GET /drivers/nearby`, `GET /pricing/estimate`, `POST /sos`,
`GET /maps/route` (proxy Directions, clé serveur), `GET /rides/{id}/track`,
`POST /rides/{id}/position` (suivi live).

## Mise en ligne

`render.yaml` à la racine du dépôt : Blueprint Render en un clic.
Voir `docs/DEPLOIEMENT-EN-LIGNE.md`.
