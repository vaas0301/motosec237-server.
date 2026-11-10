"""MOTOSEC 237 — OTP (code à 6 chiffres).
Règles : 6 chiffres, validité 10 minutes, 5 tentatives maximum, puis
blocage 15 minutes. Les codes sont stockés hachés (SHA-256) en base,
jamais en clair. En v0.1 le code est retourné par l'endpoint de DEMANDE
uniquement en mode DÉMO (développement) ; en production il doit partir
par SMS via un agrégateur, jamais dans une réponse HTTP.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

OTP_LENGTH = 6
OTP_VALIDITY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_LOCKOUT_MINUTES = 15


def generate_otp():
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def hash_otp(code):
    return hashlib.sha256(code.encode()).hexdigest()


def otp_expires_at(now=None):
    now = now or datetime.now(timezone.utc)
    return now + timedelta(minutes=OTP_VALIDITY_MINUTES)


def is_expired(expires_at_iso, now=None):
    now = now or datetime.now(timezone.utc)
    return now >= datetime.fromisoformat(expires_at_iso)
