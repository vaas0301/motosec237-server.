"""Tests du serveur MOTOSEC 237 v0.1 (exécutés réellement avec pytest)."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/motosec237_test.db"
os.environ["MOTOSEC_PAIRING_CODE"] = "123456"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["MOTOSEC_DEMO_OTP"] = "1"

for p in ("/tmp/motosec237_test.db", "/tmp/motosec237_test.db-journal"):
    if os.path.exists(p):
        os.remove(p)
# La base est créée à l'import (init_db) ; le fichier doit être absent avant.
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def _token():
    r = client.post("/devices/register", json={
        "pairing_code": "123456", "device_name": "Téléphone test", "role": "client"})
    assert r.status_code == 200, r.text
    return r.json()["device_token"]


def test_health_online():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["mode"] == "online"
    assert r.json()["version"] == "0.3.0"


def test_register_wrong_code_refused():
    r = client.post("/devices/register", json={
        "pairing_code": "000000", "device_name": "Intrus", "role": "client"})
    assert r.status_code == 403


def test_sync_requires_token():
    r = client.post("/sync", json={"operations": []})
    assert r.status_code == 401


def test_sync_idempotent_no_duplicate():
    token = _token()
    op = {"op_id": "op-test-1", "type": "ride.create", "payload": {
        "client_id": "client-demo", "origin_lat": 6.5167, "origin_lng": 14.3,
        "dest_lat": 6.5267, "dest_lng": 14.3, "distance_km": 1.11,
        "duration_min": 5, "fare_fcfa": 500}}
    h = {"X-Device-Token": token}
    r1 = client.post("/sync", json={"operations": [op]}, headers=h)
    assert r1.json()["acked"] == ["op-test-1"], r1.text
    r2 = client.post("/sync", json={"operations": [op]}, headers=h)
    assert r2.json()["duplicates"] == ["op-test-1"], r2.text
    assert r2.json()["acked"] == []
    rides = client.get("/rides", headers=h).json()["rides"]
    assert len([x for x in rides if x.get("op_id") == "op-test-1"]) == 1


def test_sync_conflict_keeps_first():
    token = _token()
    h = {"X-Device-Token": token}
    op1 = {"op_id": "op-test-2", "type": "ride.create", "payload": {
        "client_id": "client-demo", "origin_lat": 6.5167, "origin_lng": 14.3,
        "dest_lat": 6.5267, "dest_lng": 14.3}}
    op2 = {"op_id": "op-test-2", "type": "ride.create", "payload": {
        "client_id": "AUTRE", "origin_lat": 0.0, "origin_lng": 0.0,
        "dest_lat": 0.0, "dest_lng": 0.0}}
    assert client.post("/sync", json={"operations": [op1]}, headers=h).json()["acked"] == ["op-test-2"]
    r = client.post("/sync", json={"operations": [op2]}, headers=h)
    assert r.json()["conflicts"] and r.json()["conflicts"][0]["op_id"] == "op-test-2"
    rides = client.get("/rides", headers=h).json()["rides"]
    kept = [x for x in rides if x.get("op_id") == "op-test-2"][0]
    assert kept["client_id"] == "client-demo"


def test_ride_create_fare_matches_pricing():
    token = _token()
    r = client.post("/rides", json={
        "origin_lat": 6.5167, "origin_lng": 14.3,
        "dest_lat": 6.5617, "dest_lng": 14.3, "duration_min": 10},
        headers={"X-Device-Token": token})
    assert r.status_code == 200, r.text
    # Distance réelle ~5,004 km (0,045° de latitude) : le tarif est calculé
    # sur la distance Haversine exacte, pas sur 5,000 km arrondis.
    dist = r.json()["distance_km"]
    expected = max(500, round(300 + dist * 150 + 10 * 20))
    assert r.json()["fare_fcfa"] == expected, r.json()


def test_pricing_minimum_fare():
    r = client.get("/pricing/estimate", params={"distance_km": 0, "duration_min": 0})
    assert r.json()["fare_fcfa"] == 500


def test_otp_flow_and_lockout():
    phone = "+237690000001"
    r = client.post("/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200
    code = r.json()["demo_code"]  # DEV ONLY (MOTOSEC_DEMO_OTP=1)
    assert len(code) == 6
    bad = client.post("/auth/otp/verify", json={"phone": phone, "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/auth/otp/verify", json={"phone": phone, "code": code})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    # Après succès, le code est consommé : plus aucun code pour ce numéro.
    gone = client.post("/auth/otp/verify", json={"phone": phone, "code": code})
    assert gone.status_code == 404


def test_otp_lockout_after_5_attempts():
    phone = "+237690000002"
    client.post("/auth/otp/request", json={"phone": phone})
    for _ in range(5):
        client.post("/auth/otp/verify", json={"phone": phone, "code": "000000"})
    r = client.post("/auth/otp/verify", json={"phone": phone, "code": "000000"})
    assert r.status_code == 429


def test_sos_creates_open_incident():
    token = _token()
    r = client.post("/sos", json={"note": "Test SOS v0.1", "lat": 6.5167, "lng": 14.3},
                    headers={"X-Device-Token": token})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "sos" and r.json()["status"] == "open"


def test_drivers_nearby_empty_without_positions():
    token = _token()
    r = client.get("/drivers/nearby", params={"lat": 6.5167, "lng": 14.3},
                   headers={"X-Device-Token": token})
    assert r.status_code == 200
    assert r.json()["drivers"] == []  # aucune position connue : pas de faux conducteurs
