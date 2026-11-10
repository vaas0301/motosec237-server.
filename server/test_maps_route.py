"""Tests v0.2 : itinéraire routier Directions (proxy) et suivi live."""
import io
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/motosec237_test_maps.db")
os.environ.setdefault("MOTOSEC_PAIRING_CODE", "123456")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("MOTOSEC_DEMO_OTP", "1")

for p in ("/tmp/motosec237_test_maps.db", "/tmp/motosec237_test_maps.db-journal"):
    if os.path.exists(p):
        os.remove(p)
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from maps_route import MapsRouteError, decode_polyline, fetch_route  # noqa: E402

client = TestClient(main.app)

# Exemple canonique de la documentation Google (polyligne encodée).
ENCODED_REF = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
POINTS_REF = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def _token():
    r = client.post("/devices/register", json={
        "pairing_code": "123456", "device_name": "Téléphone test maps", "role": "client"})
    assert r.status_code == 200, r.text
    return r.json()["device_token"]


def _fake_opener(payload):
    def opener(url, timeout=10):
        return io.BytesIO(json.dumps(payload).encode("utf-8"))
    return opener


def test_decode_polyline_reference_google():
    pts = decode_polyline(ENCODED_REF)
    assert len(pts) == 3
    for got, want in zip(pts, POINTS_REF):
        assert abs(got[0] - want[0]) < 1e-5 and abs(got[1] - want[1]) < 1e-5


def test_fetch_route_ok_avec_reponse_directions():
    payload = {"status": "OK", "routes": [{
        "summary": "Route de test",
        "overview_polyline": {"points": ENCODED_REF},
        "legs": [{"distance": {"value": 10000}, "duration": {"value": 600}}],
    }]}
    route = fetch_route(38.5, -120.2, 43.252, -126.453, "FAUSSE-CLE-TEST",
                        opener=_fake_opener(payload))
    assert route["source"] == "directions"
    assert route["distance_km"] == 10.0
    assert route["duration_min"] == 10.0
    assert len(route["points"]) == 3


def test_fetch_route_sans_cle_refuse_clairement():
    try:
        fetch_route(6.5167, 14.3, 6.5267, 14.3, "")
        raise AssertionError("aurait dû lever MapsRouteError")
    except MapsRouteError as e:
        assert "non configurée" in str(e)


def test_fetch_route_refus_google_explicite():
    payload = {"status": "REQUEST_DENIED", "routes": []}
    try:
        fetch_route(6.5167, 14.3, 6.5267, 14.3, "CLE-INVALIDE",
                    opener=_fake_opener(payload))
        raise AssertionError("aurait dû lever MapsRouteError")
    except MapsRouteError as e:
        assert "REQUEST_DENIED" in str(e)


def test_maps_route_exige_token():
    r = client.get("/maps/route", params={
        "origin_lat": 6.5167, "origin_lng": 14.3, "dest_lat": 6.5267, "dest_lng": 14.3})
    assert r.status_code == 401


def test_maps_route_503_sans_cle_serveur():
    token = _token()
    old = main.GOOGLE_MAPS_API_KEY
    main.GOOGLE_MAPS_API_KEY = ""
    try:
        r = client.get("/maps/route", params={
            "origin_lat": 6.5167, "origin_lng": 14.3,
            "dest_lat": 6.5267, "dest_lng": 14.3},
            headers={"X-Device-Token": token})
        assert r.status_code == 503, r.text
        assert "GOOGLE_MAPS_API_KEY" in r.json()["detail"]
    finally:
        main.GOOGLE_MAPS_API_KEY = old


def test_maps_route_200_avec_itineraire(monkeypatch):
    token = _token()
    monkeypatch.setattr(main, "fetch_route", lambda *a, **k: {
        "points": [(6.5167, 14.3), (6.5267, 14.3)],
        "distance_km": 1.2, "duration_min": 4.0,
        "summary": "Route test", "source": "directions"})
    r = client.get("/maps/route", params={
        "origin_lat": 6.5167, "origin_lng": 14.3,
        "dest_lat": 6.5267, "dest_lng": 14.3},
        headers={"X-Device-Token": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "directions"
    assert body["distance_km"] == 1.2
    assert len(body["points"]) == 2


def _create_ride(token):
    r = client.post("/rides", json={
        "origin_lat": 6.5167, "origin_lng": 14.3,
        "dest_lat": 6.5267, "dest_lng": 14.3, "duration_min": 5},
        headers={"X-Device-Token": token})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_track_course_inconnue_404():
    token = _token()
    r = client.get("/rides/ride-inexistante/track",
                   headers={"X-Device-Token": token})
    assert r.status_code == 404


def test_position_puis_track_renvoie_le_point():
    token = _token()
    h = {"X-Device-Token": token}
    ride_id = _create_ride(token)
    r = client.post(f"/rides/{ride_id}/position",
                    json={"lat": 6.52, "lng": 14.3, "speed_kmh": 25},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    t = client.get(f"/rides/{ride_id}/track", headers=h)
    assert t.status_code == 200, t.text
    body = t.json()
    assert body["ride"]["id"] == ride_id
    assert body["driver_position"] is None  # pas de conducteur assigné
    assert len(body["gps_points"]) == 1
    assert body["gps_points"][0]["lat"] == 6.52
    assert body["gps_points"][0]["speed_kmh"] == 25


def test_position_course_inconnue_404():
    token = _token()
    r = client.post("/rides/ride-inexistante/position",
                    json={"lat": 6.52, "lng": 14.3},
                    headers={"X-Device-Token": token})
    assert r.status_code == 404
