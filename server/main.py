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

VERSION = "0.3.0"
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
    # v0.3 — circuit conducteur : en ligne / hors ligne, motif de refus.
    for col in ("online INTEGER NOT NULL DEFAULT 0", "rejection_reason TEXT"):
        try:
            conn.execute(f"ALTER TABLE drivers ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    # v0.3 — code boîtier du traqueur, unique quand il est renseigné
    # (NULL autorisé plusieurs fois : une moto sans boîtier reste possible).
    # SQLite REFUSE « UNIQUE » dans ALTER TABLE ADD COLUMN : on ajoute la
    # colonne simple, puis un index unique séparé (les NULL restent
    # autorisés en plusieurs exemplaires dans un index unique).
    try:
        conn.execute("ALTER TABLE motorcycles ADD COLUMN box_code TEXT")
    except sqlite3.OperationalError:
        pass  # colonne déjà présente
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_motorcycles_box_code "
            "ON motorcycles(box_code)")
    except sqlite3.OperationalError:
        pass  # index déjà présent
    conn.commit()
    conn.close()


# v0.3 — une position « en ligne » n'est valable que 10 minutes : un
# conducteur qui oublie de se mettre hors ligne disparaît tout seul de
# /drivers/nearby après ce délai (le marqueur ne reste pas figé).
ONLINE_FRESH_SECONDS = 600


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


# ------------------------------------------------------- circuit conducteur
def _fresh(last_seen_at):
    """Vrai si la dernière position connue date de moins de 10 minutes.

    Une position périmée n'est plus « en ligne » : le conducteur a coupé
    l'appli, perdu le réseau, ou oublié de se mettre hors ligne.
    """
    if not last_seen_at:
        return False
    try:
        seen = datetime.fromisoformat(last_seen_at)
    except ValueError:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - seen).total_seconds()
    return 0 <= age <= ONLINE_FRESH_SECONDS


def _driver_by_id(conn, driver_id):
    return conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()


def _driver_by_user(conn, user_id):
    return conn.execute("SELECT * FROM drivers WHERE user_id = ?", (user_id,)).fetchone()


def _driver_motorcycles(conn, driver_id):
    rows = conn.execute(
        "SELECT * FROM motorcycles WHERE driver_id = ? ORDER BY created_at",
        (driver_id,)).fetchall()
    return [dict(r) for r in rows]


def _moto_for_driver(conn, driver_id):
    """Première moto VÉRIFIÉE du conducteur (la plus ancienne) : c'est
    celle qui est attribuée à la course quand le client choisit ce
    conducteur. None s'il n'en a aucune."""
    row = conn.execute(
        "SELECT * FROM motorcycles WHERE driver_id = ? AND verified = 1 "
        "ORDER BY created_at LIMIT 1", (driver_id,)).fetchone()
    return dict(row) if row else None


def _touch_driver_position(conn, driver_id, lat, lng):
    """Met à jour la dernière position connue du conducteur.

    Un conducteur VÉRIFIÉ qui publie sa position passe en ligne (c'est
    comme ça qu'il se signale disponible). Un dossier en attente, refusé
    ou suspendu ne passe jamais en ligne, même s'il publie une position.
    """
    row = _driver_by_id(conn, driver_id)
    if row is None:
        return False
    online = 1 if row["status"] == "verified" else row["online"]
    conn.execute(
        "UPDATE drivers SET last_lat=?, last_lng=?, last_seen_at=?, online=? "
        "WHERE id=?",
        (lat, lng, _now(), online, driver_id),
    )
    return True


def _driver_public(conn, driver_row, distance_km=None):
    """Ce que le CLIENT voit d'un conducteur pour choisir (v0.3) : nom,
    note, distance, et ses motos vérifiées (plaque, marque, modèle,
    couleur). Aucun document, aucun téléphone, aucune position exacte
    au-delà de la distance."""
    user = conn.execute(
        "SELECT full_name, phone FROM app_users WHERE id = ?",
        (driver_row["user_id"],)).fetchone()
    motos = [m for m in _driver_motorcycles(conn, driver_row["id"]) if m["verified"]]
    out = {
        "id": driver_row["id"],
        "name": user["full_name"] if user else "Conducteur",
        "rating_avg": driver_row["rating_avg"],
        "distance_km": distance_km,
        "motorcycles": [
            {"id": m["id"], "plate": m["plate"], "brand": m["brand"],
             "model": m["model"], "color": m["color"]}
            for m in motos
        ],
    }
    return out


def _norm_plate(plate):
    return (plate or "").strip().upper()


def _norm_box_code(box_code):
    code = (box_code or "").strip()
    return code or None


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


# v0.3 — circuit conducteur (inscription, vérification, choix, « J'arrive »).
class MotorcycleIn(BaseModel):
    plate: str
    brand: str = ""
    model: str = ""
    color: str = ""
    box_code: str | None = None
    owner_name: str = ""


class DriverRegisterIn(BaseModel):
    user_id: str  # téléphone du motoman (identifiant utilisateur)
    full_name: str = ""
    id_document_type: str = ""  # CNI ou passeport
    id_document_ref: str = ""
    licence_number: str = ""
    motorcycle: MotorcycleIn


class VerifyIn(BaseModel):
    pairing_code: str  # code d'appairage : validation réservée à l'admin
    decision: str  # "verified" ou "rejected"
    reason: str = ""


class OnlineIn(BaseModel):
    online: bool


class ChooseDriverIn(BaseModel):
    driver_id: str


class DriverActionIn(BaseModel):
    driver_id: str


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
    # v0.3 — décision utilisateur : paiement en espèces UNIQUEMENT (pas
    # de MTN MoMo ni Orange Money). Toute autre méthode est refusée.
    if body.payment_method != "cash":
        raise HTTPException(
            status_code=400,
            detail="Paiement en espèces (cash) uniquement.")
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


@app.post("/rides/{ride_id}/request")
def request_ride(ride_id: str, x_device_token: str | None = Header(default=None)):
    """Le client publie sa course (draft -> requested) : elle devient
    visible des conducteurs en ligne (GET /drivers/requests) et le
    client peut choisir un conducteur (POST /rides/{id}/choose-driver)."""
    _require_device(x_device_token)
    conn = get_db()
    ride = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if ride is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Course introuvable.")
    if ride["status"] != "draft":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"Course déjà publiée (statut : {ride['status']}).")
    conn.execute(
        "UPDATE rides SET status='requested', updated_at=? WHERE id=?",
        (_now(), ride_id))
    conn.execute(
        "INSERT INTO ride_events (ride_id, op_id, event_type, detail, created_at) "
        "VALUES (?,?,?,?,?)",
        (ride_id, str(uuid.uuid4()), "ride_requested", "", _now()))
    conn.commit()
    row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    conn.close()
    return dict(row)


@app.post("/rides/{ride_id}/choose-driver")
def choose_driver(ride_id: str, body: ChooseDriverIn,
                  x_device_token: str | None = Header(default=None)):
    """Le client choisit le conducteur qui viendra (v0.3).

    Attribution atomique : une seule mise à jour conditionnelle
    (statut 'requested' ET aucun conducteur déjà choisi). Si deux
    clients choisissent en même temps, un seul gagne, l'autre reçoit
    409. Le conducteur doit être vérifié, en ligne avec une position
    fraîche, avoir une moto vérifiée, et ne pas être déjà engagé sur
    une autre course (requested avec conducteur, assigned, ongoing).
    La course reste 'requested' : c'est le conducteur qui confirme
    ensuite avec POST /rides/{id}/accept (« J'arrive »)."""
    _require_device(x_device_token)
    conn = get_db()
    ride = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if ride is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Course introuvable.")
    driver = _driver_by_id(conn, body.driver_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    if ride["status"] != "requested" or ride["driver_id"] is not None:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Course déjà attribuée ou non demandée.")
    if driver["status"] != "verified":
        conn.close()
        raise HTTPException(
            status_code=409, detail="Conducteur non vérifié.")
    if not driver["online"] or not _fresh(driver["last_seen_at"]):
        conn.close()
        raise HTTPException(
            status_code=409, detail="Conducteur hors ligne pour le moment.")
    busy = conn.execute(
        "SELECT id FROM rides WHERE driver_id = ? AND status IN "
        "('requested','assigned','ongoing') LIMIT 1",
        (body.driver_id,)).fetchone()
    if busy is not None:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Conducteur déjà engagé sur une autre course.")
    moto = _moto_for_driver(conn, body.driver_id)
    if moto is None:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Conducteur sans moto vérifiée.")
    cur = conn.execute(
        "UPDATE rides SET driver_id=?, motorcycle_id=?, updated_at=? "
        "WHERE id=? AND status='requested' AND driver_id IS NULL",
        (body.driver_id, moto["id"], _now(), ride_id))
    if cur.rowcount != 1:
        conn.close()
        raise HTTPException(
            status_code=409, detail="Course déjà attribuée à un autre conducteur.")
    conn.execute(
        "INSERT INTO ride_events (ride_id, op_id, event_type, detail, created_at) "
        "VALUES (?,?,?,?,?)",
        (ride_id, str(uuid.uuid4()), "driver_chosen", body.driver_id, _now()))
    conn.commit()
    row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    conn.close()
    return dict(row)


@app.post("/rides/{ride_id}/accept")
def accept_ride(ride_id: str, body: DriverActionIn,
                x_device_token: str | None = Header(default=None)):
    """Le conducteur CHOISI confirme : « J'arrive » (v0.3). La course
    passe en 'assigned'. Seul le conducteur choisi peut accepter."""
    _require_device(x_device_token)
    conn = get_db()
    ride = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if ride is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Course introuvable.")
    if ride["status"] != "requested" or ride["driver_id"] != body.driver_id:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Cette course ne vous est pas proposée.")
    conn.execute(
        "UPDATE rides SET status='assigned', updated_at=? WHERE id=?",
        (_now(), ride_id))
    conn.execute(
        "INSERT INTO ride_events (ride_id, op_id, event_type, detail, created_at) "
        "VALUES (?,?,?,?,?)",
        (ride_id, str(uuid.uuid4()), "driver_accepted", body.driver_id, _now()))
    conn.commit()
    row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    conn.close()
    return dict(row)


@app.post("/rides/{ride_id}/decline")
def decline_ride(ride_id: str, body: DriverActionIn,
                 x_device_token: str | None = Header(default=None)):
    """Le conducteur CHOISI refuse : la course redevient 'requested'
    sans conducteur, le client peut choisir un autre conducteur (v0.3).
    Seul le conducteur choisi peut refuser."""
    _require_device(x_device_token)
    conn = get_db()
    ride = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if ride is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Course introuvable.")
    if ride["status"] != "requested" or ride["driver_id"] != body.driver_id:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Cette course ne vous est pas proposée.")
    conn.execute(
        "UPDATE rides SET driver_id=NULL, motorcycle_id=NULL, updated_at=? "
        "WHERE id=?", (_now(), ride_id))
    conn.execute(
        "INSERT INTO ride_events (ride_id, op_id, event_type, detail, created_at) "
        "VALUES (?,?,?,?,?)",
        (ride_id, str(uuid.uuid4()), "driver_declined", body.driver_id, _now()))
    conn.commit()
    row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    conn.close()
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
        # La position fraîche maintient le conducteur en ligne pendant
        # la course (v0.3 : _touch_driver_position).
        _touch_driver_position(conn, ride["driver_id"], body.lat, body.lng)
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
    """Position du conducteur (mise en ligne / maintien en ligne, v0.3).

    Un conducteur vérifié qui publie sa position passe en ligne. Un
    dossier en attente, refusé ou suspendu ne passe jamais en ligne.
    """
    _require_device(x_device_token)
    if not (-90 <= body.lat <= 90 and -180 <= body.lng <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées hors limites.")
    conn = get_db()
    ok = _touch_driver_position(conn, driver_id, body.lat, body.lng)
    conn.commit()
    conn.close()
    if not ok:
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    return {"ok": True}


@app.post("/drivers/{driver_id}/online")
def driver_online(driver_id: str, body: OnlineIn,
                  x_device_token: str | None = Header(default=None)):
    """Bascule « En ligne / Hors ligne » du conducteur (v0.3).

    Seul un conducteur VÉRIFIÉ peut se mettre en ligne. Hors ligne, il
    disparaît immédiatement de /drivers/nearby et des demandes.
    """
    _require_device(x_device_token)
    conn = get_db()
    driver = _driver_by_id(conn, driver_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    if body.online and driver["status"] != "verified":
        conn.close()
        raise HTTPException(
            status_code=403,
            detail="Seul un conducteur vérifié peut se mettre en ligne.")
    conn.execute(
        "UPDATE drivers SET online=?, updated_at=? WHERE id=?",
        (1 if body.online else 0, _now(), driver_id))
    conn.commit()
    conn.close()
    return {"ok": True, "online": body.online}


@app.get("/drivers/nearby")
def drivers_nearby(lat: float, lng: float, radius_km: float = 5.0,
                   x_device_token: str | None = Header(default=None)):
    """Conducteurs que le CLIENT peut choisir (v0.3) : vérifiés, en
    ligne, avec une position fraîche (moins de 10 minutes). Chacun est
    renvoyé avec son nom, sa note, sa distance et ses motos vérifiées
    (plaque, marque, modèle, couleur) — de quoi choisir « celui qui
    pourra venir ». Aucun conducteur inventé : liste vide s'il n'y en
    a aucun."""
    _require_device(x_device_token)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées hors limites.")
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM drivers WHERE status='verified' AND online=1 "
        "AND last_lat IS NOT NULL AND last_lng IS NOT NULL"
    ).fetchall()
    fresh = [dict(r) for r in rows if _fresh(r["last_seen_at"])]
    drivers = [{"id": r["id"], "lat": r["last_lat"], "lng": r["last_lng"]}
               for r in fresh]
    near = nearby_drivers(drivers, lat, lng, radius_km)
    by_id = {r["id"]: r for r in fresh}
    out = []
    for n in near:
        out.append(_driver_public(conn, by_id[n["id"]], n["distance_km"]))
    conn.close()
    return {"drivers": out, "source": "positions_connues_seulement"}


@app.post("/drivers/register")
def register_driver(body: DriverRegisterIn,
                    x_device_token: str | None = Header(default=None)):
    """Inscription d'un motoman (v0.3) : dossier conducteur + première
    moto + documents. Statut initial 'pending' : c'est l'admin qui
    vérifie ensuite (POST /drivers/{id}/verify). Un seul dossier par
    utilisateur : si le dossier existe déjà, il est renvoyé tel quel
    (la moto n'est pas ajoutée deux fois)."""
    _require_device(x_device_token)
    plate = _norm_plate(body.motorcycle.plate)
    box_code = _norm_box_code(body.motorcycle.box_code)
    if not body.user_id.strip():
        raise HTTPException(status_code=400, detail="Numéro de téléphone obligatoire.")
    if not plate:
        raise HTTPException(status_code=400, detail="Plaque de la moto obligatoire.")
    if not body.licence_number.strip():
        raise HTTPException(status_code=400, detail="Numéro de permis obligatoire.")
    if not body.id_document_ref.strip():
        raise HTTPException(
            status_code=400, detail="Numéro de la pièce d'identité obligatoire.")
    conn = get_db()
    existing = _driver_by_user(conn, body.user_id.strip())
    if existing is not None:
        motos = _driver_motorcycles(conn, existing["id"])
        conn.close()
        return {"already_registered": True, **dict(existing), "motorcycles": motos}
    if conn.execute("SELECT id FROM motorcycles WHERE plate = ?", (plate,)).fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="Plaque déjà enregistrée.")
    if box_code and conn.execute(
            "SELECT id FROM motorcycles WHERE box_code = ?", (box_code,)).fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="Code boîtier déjà enregistré.")
    _ensure_user(conn, body.user_id.strip())
    if body.full_name.strip():
        conn.execute(
            "UPDATE app_users SET full_name=?, updated_at=? WHERE id=?",
            (body.full_name.strip(), _now(), body.user_id.strip()))
    driver_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO drivers (id, user_id, status, id_document_type, "
        "id_document_ref, licence_number, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (driver_id, body.user_id.strip(), "pending", body.id_document_type.strip(),
         body.id_document_ref.strip(), body.licence_number.strip(), _now(), _now()))
    moto_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO motorcycles (id, driver_id, plate, box_code, brand, model, "
        "color, owner_name, verified, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,0,?,?)",
        (moto_id, driver_id, plate, box_code, body.motorcycle.brand.strip(),
         body.motorcycle.model.strip(), body.motorcycle.color.strip(),
         body.motorcycle.owner_name.strip() or body.full_name.strip(),
         _now(), _now()))
    _audit(conn, driver_id, "driver.register",
           f"inscription conducteur user={body.user_id.strip()} plaque={plate}")
    conn.commit()
    row = _driver_by_id(conn, driver_id)
    motos = _driver_motorcycles(conn, driver_id)
    conn.close()
    return {"already_registered": False, **dict(row), "motorcycles": motos}


@app.get("/drivers/me")
def my_driver_file(user_id: str, x_device_token: str | None = Header(default=None)):
    """Mon dossier conducteur : profil + motos + statut + motif de
    refus éventuel (v0.3). user_id = numéro de téléphone du motoman."""
    _require_device(x_device_token)
    conn = get_db()
    driver = _driver_by_user(conn, user_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Aucun dossier conducteur.")
    motos = _driver_motorcycles(conn, driver["id"])
    conn.close()
    return {**dict(driver), "motorcycles": motos}


@app.post("/drivers/{driver_id}/verify")
def verify_driver(driver_id: str, body: VerifyIn,
                  x_device_token: str | None = Header(default=None)):
    """Validation admin du dossier conducteur (v0.3). Protégée par le
    code d'appairage (même code que l'enregistrement des appareils) :
    en attendant l'admin web (phase 9), c'est l'admin qui appelle cet
    endpoint. 'verified' : dossier vérifié, rôle 'driver' dans
    app_users, motos vérifiées. 'rejected' : dossier refusé, motif
    conservé (rejection_reason), visible par le conducteur."""
    _require_device(x_device_token)
    if body.pairing_code != PAIRING_CODE:
        raise HTTPException(status_code=403, detail="Code d'appairage invalide.")
    if body.decision not in ("verified", "rejected"):
        raise HTTPException(
            status_code=400, detail="decision doit être 'verified' ou 'rejected'.")
    conn = get_db()
    driver = _driver_by_id(conn, driver_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    if body.decision == "verified":
        conn.execute(
            "UPDATE drivers SET status='verified', verified_at=?, "
            "rejection_reason=NULL, updated_at=? WHERE id=?",
            (_now(), _now(), driver_id))
        conn.execute(
            "UPDATE app_users SET role='driver', updated_at=? WHERE id=?",
            (_now(), driver["user_id"]))
        conn.execute(
            "UPDATE motorcycles SET verified=1, updated_at=? WHERE driver_id=?",
            (_now(), driver_id))
        _audit(conn, driver_id, "driver.verify", "dossier vérifié")
    else:
        conn.execute(
            "UPDATE drivers SET status='rejected', rejection_reason=?, "
            "online=0, updated_at=? WHERE id=?",
            (body.reason.strip(), _now(), driver_id))
        conn.execute(
            "UPDATE app_users SET role='client', updated_at=? WHERE id=?",
            (_now(), driver["user_id"]))
        _audit(conn, driver_id, "driver.verify",
               f"dossier refusé : {body.reason.strip()}")
    conn.commit()
    row = _driver_by_id(conn, driver_id)
    motos = _driver_motorcycles(conn, driver_id)
    conn.close()
    return {**dict(row), "motorcycles": motos}


@app.post("/drivers/{driver_id}/motorcycles")
def add_motorcycle(driver_id: str, body: MotorcycleIn,
                   x_device_token: str | None = Header(default=None)):
    """Ajouter une moto à son dossier (v0.3). Plaque unique, code
    boîtier unique quand il est renseigné. Une moto ajoutée par un
    conducteur DÉJÀ vérifié est marquée vérifiée (le conducteur est
    de confiance après vérification) ; sinon elle attend la
    vérification du dossier."""
    _require_device(x_device_token)
    plate = _norm_plate(body.plate)
    box_code = _norm_box_code(body.box_code)
    if not plate:
        raise HTTPException(status_code=400, detail="Plaque de la moto obligatoire.")
    conn = get_db()
    driver = _driver_by_id(conn, driver_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    if conn.execute("SELECT id FROM motorcycles WHERE plate = ?", (plate,)).fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="Plaque déjà enregistrée.")
    if box_code and conn.execute(
            "SELECT id FROM motorcycles WHERE box_code = ?", (box_code,)).fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="Code boîtier déjà enregistré.")
    moto_id = str(uuid.uuid4())
    verified = 1 if driver["status"] == "verified" else 0
    conn.execute(
        "INSERT INTO motorcycles (id, driver_id, plate, box_code, brand, model, "
        "color, owner_name, verified, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (moto_id, driver_id, plate, box_code, body.brand.strip(),
         body.model.strip(), body.color.strip(),
         body.owner_name.strip(), verified, _now(), _now()))
    conn.commit()
    row = conn.execute(
        "SELECT * FROM motorcycles WHERE id = ?", (moto_id,)).fetchone()
    conn.close()
    return dict(row)


@app.get("/drivers/{driver_id}/motorcycles")
def list_motorcycles(driver_id: str, x_device_token: str | None = Header(default=None)):
    _require_device(x_device_token)
    conn = get_db()
    driver = _driver_by_id(conn, driver_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    motos = _driver_motorcycles(conn, driver_id)
    conn.close()
    return {"motorcycles": motos}


@app.get("/drivers/requests")
def driver_requests(driver_id: str, x_device_token: str | None = Header(default=None)):
    """Demandes de courses visibles par un conducteur vérifié (v0.3) :
    les courses 'requested' sans conducteur (en attente du choix du
    client) et celles qui lui sont proposées (chosen_for_me : c'est à
    lui de dire « J'arrive » ou de refuser). Les courses proposées à
    un AUTRE conducteur ne sont pas visibles. Les propositions passent
    d'abord, puis les demandes ouvertes, par ancienneté."""
    _require_device(x_device_token)
    conn = get_db()
    driver = _driver_by_id(conn, driver_id)
    if driver is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Conducteur introuvable.")
    if driver["status"] != "verified":
        conn.close()
        raise HTTPException(
            status_code=403,
            detail="Seul un conducteur vérifié voit les demandes.")
    rows = conn.execute(
        "SELECT r.*, u.full_name AS client_name, u.phone AS client_phone "
        "FROM rides r JOIN app_users u ON u.id = r.client_id "
        "WHERE r.status = 'requested' "
        "AND (r.driver_id IS NULL OR r.driver_id = ?) "
        "ORDER BY (r.driver_id = ?) DESC, r.created_at ASC LIMIT 50",
        (driver_id, driver_id)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["chosen_for_me"] = d["driver_id"] == driver_id
        out.append(d)
    return {"requests": out}


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
