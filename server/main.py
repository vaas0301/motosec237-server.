"""MOTOSEC 237 v0.2 — serveur EN LIGNE (FastAPI + SQLite en dev).

CHOIX UTILISATEUR (2026-11-10) : serveur EN LIGNE UNIQUEMENT. Il n'y a PAS
de serveur local Wi-Fi dans MOTOSEC 237 (contrairement à MinePilot).
L'appli Flutter appelle UNE SEULE adresse configurable (BASE_URL) par
internet, depuis n'importe où. Google Maps exige internet de toute façon,
ce choix est cohérent.

Déploiement : voir docs/DEPLOIEMENT-EN-LIGNE.md (Docker, variables
d'environnement, HTTPS). En développement local on lance le même code
avec uvicorn sur la machine de dev, uniquement pour tester — ce n'est
PAS un mode "serveur local" du produit.

Variables d'environnement :
  DATABASE_URL        sqlite:///./motosec237.db (défaut, dev) — v0.1 : SQLite
                      uniquement. Une URL postgres est REFUSÉE avec un message
                      clair (bascule documentée dans docs/BASE-DONNEES.md).
  SECRET_KEY          À REMPLIR en production (aucune valeur réelle ici).
  MOTOSEC_PAIRING_CODE  code d'enregistrement des appareils (6 chiffres).
                      Généré au premier démarrage si absent (dev seulement).
  ALLOWED_ORIGINS     origines CORS autorisées, séparées par des virgules.
  MOTOSEC_DEMO_OTP    "1" = renvoie le code OTP dans la réponse (DEV ONLY,
                      jamais en production : le code part par SMS).
  PORT                port d'écoute en dev (défaut 8000).

Lancement (dev) : uvicorn main:app --host 0.0.0.0 --port 8000
  depuis le dossier server/ (venv : ../.venv/bin/uvicorn).
"""
import hashlib
import json
import os
import secrets
import sqlite3
import string
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from geo import haversine_km, nearby_drivers
from maps_route import MapsRouteError, fetch_route
from otp import (
    OTP_LOCKOUT_MINUTES,
    OTP_MAX_ATTEMPTS,
    generate_otp,
    hash_otp,
    is_expired,
    otp_expires_at,
)
from pricing import (
    BASE_FARE_FCFA,
    COMMISSION_RATE,
    MIN_FARE_FCFA,
    PRICE_PER_KM_FCFA,
    PRICE_PER_MIN_FCFA,
    estimate_fare,
)

VERSION = "0.2.0"
BASE = Path(__file__).parent
SCHEMA_PATH = BASE.parent / "db" / "schema.sql"

# ------------------------------------------------------------------ config
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./motosec237.db")
if not DATABASE_URL.startswith("sqlite:///"):
    raise RuntimeError(
        "MOTOSEC 237 v0.1 : seule SQLite est supportée (DATABASE_URL doit "
        "commencer par sqlite:///). La bascule PostgreSQL est documentée "
        "dans docs/BASE-DONNEES.md, elle n'est pas construite dans la v0.1."
    )
DB_PATH = Path(DATABASE_URL[len("sqlite:///"):]).expanduser()
if not DB_PATH.is_absolute():
    DB_PATH = (BASE / DB_PATH).resolve()

SECRET_KEY = os.environ.get("SECRET_KEY", "")
SECRET_KEY_IS_DEV_DEFAULT = SECRET_KEY == ""
if SECRET_KEY_IS_DEV_DEFAULT:
    SECRET_KEY = "DEV-SEULEMENT-REMPLIR-SECRET_KEY-EN-PRODUCTION"  # noqa: S105

DEMO_OTP = os.environ.get("MOTOSEC_DEMO_OTP", "0") == "1"
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# v0.2 — clé Google Directions CÔTÉ SERVEUR UNIQUEMENT (jamais dans
# l'appli). Sert au proxy GET /maps/route. Sans elle, l'endpoint répond
# 503 et l'appli retombe sur la ligne droite. Restreindre cette clé à
# l'API Directions dans Google Cloud (voir docs/GOOGLE-MAPS.md).
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

CONFIG_PATH = BASE / "server_config.json"


def _pairing_code():
    if os.environ.get("MOTOSEC_PAIRING_CODE"):
        return os.environ["MOTOSEC_PAIRING_CODE"]
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["pairing_code"]
        except Exception:
            pass
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    CONFIG_PATH.write_text(json.dumps({"pairing_code": code}), encoding="utf-8")
    return code


PAIRING_CODE = _pairing_code()


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # Positions connues des conducteurs (v0.1) : dernière position connue,
    # mise à jour par POST /drivers/{id}/position. Sert à /drivers/nearby.
    for col in ("last_lat REAL", "last_lng REAL", "last_seen_at TEXT"):
        try:
            conn.execute(f"ALTER TABLE drivers ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    conn.commit()
    conn.close()


init_db()

app = FastAPI(title="MOTOSEC 237 — API en ligne", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _audit(conn, actor, action, detail):
    conn.execute(
        "INSERT INTO audit (actor, action, detail, at) VALUES (?,?,?,?)",
        (actor, action, detail, _now()),
    )


def _device(conn, token):
    if not token:
        return None
    return conn.execute(
        "SELECT * FROM devices WHERE token = ? AND revoked = 0", (token,)
    ).fetchone()


def _require_device(token):
    conn = get_db()
    row = _device(conn, token)
    conn.close()
    if row is None:
        raise HTTPException(status_code=401, detail="Appareil non enregistré ou révoqué.")
    return row


# ------------------------------------------------------------------ modèles
class RegisterIn(BaseModel):
    pairing_code: str
    device_name: str
    role: str = "client"


class OtpRequestIn(BaseModel):
    phone: str


class OtpVerifyIn(BaseModel):
    phone: str
    code: str


class OperationIn(BaseModel):
    op_id: str
    type: str
    payload: dict = Field(default_factory=dict)


class SyncIn(BaseModel):
    operations: list[OperationIn] = Field(default_factory=list)


class RideCreateIn(BaseModel):
    client_id: str = "client-demo"
    origin_lat: float
    origin_lng: float
    origin_label: str = ""
    dest_lat: float
    dest_lng: float
    dest_label: str = ""
    duration_min: float = 0.0
    payment_method: str = "cash"


class PositionIn(BaseModel):
    lat: float
    lng: float


class SosIn(BaseModel):
    ride_id: str | None = None
    reporter_phone: str = ""
    note: str = ""
    lat: float | None = None
    lng: float | None = None


class RidePositionIn(BaseModel):
    lat: float
    lng: float
    accuracy_m: float | None = None
    speed_kmh: float | None = None


# ------------------------------------------------------------------ endpoints
@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "mode": "online",
            "db": "sqlite", "maps_provider": "google_maps",
            "maps_route": "ok" if GOOGLE_MAPS_API_KEY else "cle_non_configuree"}


@app.get("/config")
def public_config():
    """Paramètres publics (aucun secret) : tarifs provisoires, centre pilote."""
    return {
        "meiganga": {"lat": 6.5167, "lng": 14.3},
        "maps_provider": "google_maps",
        "pricing_provisoire_a_valider": {
            "base_fcfa": BASE_FARE_FCFA, "per_km_fcfa": PRICE_PER_KM_FCFA,
            "per_min_fcfa": PRICE_PER_MIN_FCFA, "min_fcfa": MIN_FARE_FCFA,
            "commission_rate": COMMISSION_RATE,
        },
    }


@app.post("/devices/register")
def register_device(body: RegisterIn):
    if body.pairing_code != PAIRING_CODE:
        raise HTTPException(status_code=403, detail="Code d'appairage invalide.")
    token = secrets.token_urlsafe(32)
    device_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO devices (id, name, role, token, created_at) VALUES (?,?,?,?,?)",
        (device_id, body.device_name, body.role, token, _now()),
    )
    _audit(conn, device_id, "device.register", body.device_name)
    conn.commit()
    conn.close()
    return {"device_id": device_id, "device_token": token}


@app.post("/auth/otp/request")
def otp_request(body: OtpRequestIn):
    code = generate_otp()
    conn = get_db()
    conn.execute(
        "INSERT INTO otp_codes (phone, code_hash, attempts, expires_at, created_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(phone) DO UPDATE SET "
        "code_hash=excluded.code_hash, attempts=0, expires_at=excluded.expires_at, "
        "created_at=excluded.created_at",
        (body.phone, hash_otp(code), 0, otp_expires_at().isoformat(), _now()),
    )
    conn.commit()
    conn.close()
    out = {"phone": body.phone, "expires_in_seconds": 600,
           "message": "Code envoyé par SMS (agrégateur SMS à brancher en production)."}
    if DEMO_OTP:
        out["demo_code"] = code  # DEV ONLY, jamais en production
    return out


@app.post("/auth/otp/verify")
def otp_verify(body: OtpVerifyIn):
    conn = get_db()
    row = conn.execute("SELECT * FROM otp_codes WHERE phone = ?", (body.phone,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Aucun code demandé pour ce numéro.")
    if row["attempts"] >= OTP_MAX_ATTEMPTS:
        conn.close()
        raise HTTPException(
            status_code=429,
            detail=f"Trop de tentatives. Réessayez dans {OTP_LOCKOUT_MINUTES} minutes.",
        )
    if is_expired(row["expires_at"]):
        conn.close()
        raise HTTPException(status_code=410, detail="Code expiré. Demandez un nouveau code.")
    if hash_otp(body.code) != row["code_hash"]:
        conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE phone = ?", (body.phone,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=401, detail="Code incorrect.")
    conn.execute("DELETE FROM otp_codes WHERE phone = ?", (body.phone,))
    conn.commit()
    conn.close()
    return {"ok": True, "phone": body.phone}


def _ensure_user(conn, user_id):
    """Provisionne un utilisateur minimal s'il n'existe pas encore (v0.1 :
    le premier appel crée la fiche ; l'identité complète est vérifiée
    dans les phases d'inscription / vérification conducteur)."""
    conn.execute(
        "INSERT OR IGNORE INTO app_users (id, phone, full_name, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (user_id, user_id, "Utilisateur " + user_id[:8], _now(), _now()),
    )


def _apply_operation(conn, device_id, op):
    """Applique une opération acceptée (types connus de la v0.1)."""
    p = op.payload
    if op.type == "ride.create":
        _ensure_user(conn, p.get("client_id", "client-demo"))
        ride_id = p.get("id") or str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO rides (id, op_id, client_id, status, origin_lat, "
            "origin_lng, origin_label, dest_lat, dest_lng, dest_label, distance_km, "
            "duration_min, fare_fcfa, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ride_id, op.op_id, p.get("client_id", "client-demo"), "draft",
             p["origin_lat"], p["origin_lng"], p.get("origin_label", ""),
             p["dest_lat"], p["dest_lng"], p.get("dest_label", ""),
             p.get("distance_km"), p.get("duration_min"), p.get("fare_fcfa"),
             _now(), _now()),
        )
    elif op.type == "gps.point":
        conn.execute(
            "INSERT INTO gps_points (ride_id, lat, lng, accuracy_m, speed_kmh, recorded_at) "
            "VALUES (?,?,?,?,?,?)",
            (p["ride_id"], p["lat"], p["lng"], p.get("accuracy_m"), p.get("speed_kmh"), _now()),
        )
    elif op.type == "ride.event":
        conn.execute(
            "INSERT INTO ride_events (ride_id, op_id, event_type, detail, created_at) "
            "VALUES (?,?,?,?,?)",
            (p["ride_id"], op.op_id, p.get("event_type", "info"), p.get("detail", ""), _now()),
        )
    # Autres types : stockés dans operations (traçabilité), sans effet métier.


@app.post("/sync")
def sync(body: SyncIn, x_device_token: str | None = Header(default=None)):
    device = _require_device(x_device_token)
    acked, duplicates, conflicts = [], [], []
    conn = get_db()
    for op in body.operations:
        payload_json = json.dumps(op.payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        existing = conn.execute(
            "SELECT payload_hash FROM operations WHERE op_id = ?", (op.op_id,)
        ).fetchone()
        if existing:
            if existing["payload_hash"] == payload_hash:
                duplicates.append(op.op_id)
            else:
                conflicts.append({"op_id": op.op_id, "kept": "first"})
            continue
        conn.execute(
            "INSERT INTO operations (op_id, device_id, type, payload, payload_hash, status, received_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (op.op_id, device["id"], op.type, payload_json, payload_hash, "acked", _now()),
        )
        _apply_operation(conn, device["id"], op)
        acked.append(op.op_id)
    conn.commit()
    conn.close()
    return {"acked": acked, "duplicates": duplicates, "conflicts": conflicts}


@app.get("/rides")
def list_rides(x_device_token: str | None = Header(default=None)):
    _require_device(x_device_token)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM rides ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return {"rides": [dict(r) for r in rows]}


@app.post("/rides")
def create_ride(body: RideCreateIn, x_device_token: str | None = Header(default=None)):
    _require_device(x_device_token)
    distance = haversine_km(body.origin_lat, body.origin_lng, body.dest_lat, body.dest_lng)
    fare = estimate_fare(distance, body.duration_min)
    ride_id = str(uuid.uuid4())
    conn = get_db()
    _ensure_user(conn, body.client_id)
    conn.execute(
        "INSERT INTO rides (id, client_id, status, origin_lat, origin_lng, origin_label, "
        "dest_lat, dest_lng, dest_label, distance_km, duration_min, fare_fcfa, "
        "payment_method, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ride_id, body.client_id, "draft", body.origin_lat, body.origin_lng,
         body.origin_label, body.dest_lat, body.dest_lng, body.dest_label,
         round(distance, 3), body.duration_min, fare["fare_fcfa"],
         body.payment_method, _now(), _now()),
    )
    conn.commit()
    conn.close()
    return {"id": ride_id, "status": "draft", "distance_km": round(distance, 3), **fare}


@app.get("/rides/{ride_id}")
def get_ride(ride_id: str, x_device_token: str | None = Header(default=None)):
    _require_device(x_device_token)
    conn = get_db()
    row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Course introuvable.")
    return dict(row)


@app.get("/rides/{ride_id}/track")
def track_ride(ride_id: str, x_device_token: str | None = Header(default=None)):
    """Suivi live d'une course : course + dernière position du conducteur
    + derniers points GPS enregistrés. L'appli interroge cet endpoint
    toutes les ~10 s pendant une course active (v0.2)."""
    _require_device(x_device_token)
    conn = get_db()
    ride = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if ride is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Course introuvable.")
    driver_pos = None
    if ride["driver_id"]:
        d = conn.execute(
            "SELECT last_lat, last_lng, last_seen_at FROM drivers WHERE id = ?",
            (ride["driver_id"],)).fetchone()
        if d and d["last_lat"] is not None:
            driver_pos = {"lat": d["last_lat"], "lng": d["last_lng"],
                          "last_seen_at": d["last_seen_at"]}
    points = conn.execute(
        "SELECT lat, lng, accuracy_m, speed_kmh, recorded_at FROM gps_points "
        "WHERE ride_id = ? ORDER BY recorded_at DESC LIMIT 50",
        (ride_id,)).fetchall()
    conn.close()
    return {"ride": dict(ride), "driver_position": driver_pos,
            "gps_points": [dict(p) for p in points]}


@app.post("/rides/{ride_id}/position")
def ride_position(ride_id: str, body: RidePositionIn,
                  x_device_token: str | None = Header(default=None)):
    """Position du conducteur pendant une course (appelée par l'appli
    conducteur / le téléphone qui roule). Enregistre le point GPS et met
    à jour la dernière position connue du conducteur."""
    _require_device(x_device_token)
    if not (-90 <= body.lat <= 90 and -180 <= body.lng <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées hors limites.")
    conn = get_db()
    ride = conn.execute("SELECT driver_id FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if ride is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Course introuvable.")
    conn.execute(
        "INSERT INTO gps_points (ride_id, lat, lng, accuracy_m, speed_kmh, recorded_at) "
        "VALUES (?,?,?,?,?,?)",
        (ride_id, body.lat, body.lng, body.accuracy_m, body.speed_kmh, _now()),
    )
    if ride["driver_id"]:
        conn.execute(
            "UPDATE drivers SET last_lat=?, last_lng=?, last_seen_at=? WHERE id=?",
            (body.lat, body.lng, _now(), ride["driver_id"]),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/maps/route")
def maps_route(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float,
               x_device_token: str | None = Header(default=None)):
    """Proxy itinéraire routier Google Directions (v0.2, phase 5).

    La clé Google reste côté serveur (GOOGLE_MAPS_API_KEY) : l'appli ne
    la voit jamais. Sans clé : 503, l'appli retombe sur la ligne droite.
    Réponse : points (lat/lng), distance_km, duration_min, summary.
    """
    _require_device(x_device_token)
    if not (-90 <= origin_lat <= 90 and -90 <= dest_lat <= 90
            and -180 <= origin_lng <= 180 and -180 <= dest_lng <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées hors limites.")
    try:
        route = fetch_route(origin_lat, origin_lng, dest_lat, dest_lng,
                            GOOGLE_MAPS_API_KEY)
    except MapsRouteError as e:
        if "non configurée" in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        raise HTTPException(status_code=502, detail=str(e))
    return {"points": [{"lat": lat, "lng": lng} for lat, lng in route["points"]],
            "distance_km": route["distance_km"],
            "duration_min": route["duration_min"],
            "summary": route["summary"], "source": "directions"}


@app.post("/drivers/{driver_id}/position")
def driver_position(driver_id: str, body: PositionIn,
                    x_device_token: str | None = Header(default=None)):
    _require_device(x_device_token)
    conn = get_db()
    cur = conn.execute(
        "UPDATE drivers SET last_lat=?, last_lng=?, last_seen_at=? WHERE id=?",
        (body.lat, body.lng, _now(), driver_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    return {"ok": True}


@app.get("/drivers/nearby")
def drivers_nearby(lat: float, lng: float, radius_km: float = 5.0,
                   x_device_token: str | None = Header(default=None)):
    _require_device(x_device_token)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées hors limites.")
    conn = get_db()
    rows = conn.execute(
        "SELECT id, last_lat, last_lng FROM drivers WHERE status='verified' "
        "AND last_lat IS NOT NULL AND last_lng IS NOT NULL"
    ).fetchall()
    conn.close()
    drivers = [{"id": r["id"], "lat": r["last_lat"], "lng": r["last_lng"]} for r in rows]
    return {"drivers": nearby_drivers(drivers, lat, lng, radius_km),
            "source": "positions_connues_seulement"}


@app.get("/pricing/estimate")
def pricing_estimate(distance_km: float, duration_min: float = 0.0):
    if distance_km < 0 or duration_min < 0:
        raise HTTPException(status_code=400, detail="Distance et durée >= 0.")
    return {"distance_km": distance_km, "duration_min": duration_min,
            **estimate_fare(distance_km, duration_min),
            "provisoire_a_valider": True}


@app.post("/sos")
def sos(body: SosIn, x_device_token: str | None = Header(default=None)):
    device = _require_device(x_device_token)
    incident_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO incidents (id, ride_id, kind, status, note, last_lat, last_lng, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (incident_id, body.ride_id, "sos", "open", body.note, body.lat, body.lng, _now(), _now()),
    )
    _audit(conn, device["id"], "sos", f"incident {incident_id} ride={body.ride_id}")
    conn.commit()
    conn.close()
    # L'alerte SOS ne déclenche AUCUN appel automatique en v0.1 : elle est
    # qualifiée par un opérateur humain (centre de sécurité, phase 6).
    return {"id": incident_id, "kind": "sos", "status": "open",
            "message": "Alerte SOS enregistrée. Un opérateur doit qualifier l'alerte."}
