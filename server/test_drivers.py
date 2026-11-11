"""Tests du serveur MOTOSEC 237 v0.3 — circuit conducteur.

Inscription, vérification admin, en ligne / hors ligne, demandes,
choix du conducteur par le client, « J'arrive » / refus. Exécutés
réellement avec pytest.

Isolation : chaque test vide TOUTES les tables avant et après (la base
est partagée avec les autres fichiers de tests — l'ordre d'import ne
doit rien changer).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/motosec237_test_drivers.db")
os.environ.setdefault("MOTOSEC_PAIRING_CODE", "123456")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("MOTOSEC_DEMO_OTP", "1")

for p in ("/tmp/motosec237_test_drivers.db", "/tmp/motosec237_test_drivers.db-journal"):
    if os.path.exists(p):
        os.remove(p)
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)

MEIGANGA = {"lat": 6.5167, "lng": 14.3}


@pytest.fixture(autouse=True)
def _wipe():
    _clean()
    yield
    _clean()


def _clean():
    conn = main.get_db()
    try:
        # Les clés étrangères sont coupées pour le nettoyage : l'ordre
        # des tables n'a pas d'importance (rides référence drivers et
        # app_users sans CASCADE). Sans ça, le DELETE échoue et la
        # connexion fuit avec un verrou ouvert (30 s par test).
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()


def _token():
    r = client.post("/devices/register", json={
        "pairing_code": "123456", "device_name": "Téléphone test", "role": "client"})
    assert r.status_code == 200, r.text
    return r.json()["device_token"]


def _headers():
    return {"X-Device-Token": _token()}


def _register(h, phone="+237690000101", plate="CE123AB", box_code="BOX-001",
              name="Aboubakar Diallo"):
    r = client.post("/drivers/register", json={
        "user_id": phone, "full_name": name,
        "id_document_type": "CNI", "id_document_ref": "CNI-987654",
        "licence_number": "PERMIS-12345",
        "motorcycle": {"plate": plate, "brand": "Yamaha", "model": "DT125",
                       "color": "rouge", "box_code": box_code,
                       "owner_name": name}}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _verify(h, driver_id, decision="verified", reason=""):
    return client.post(f"/drivers/{driver_id}/verify", json={
        "pairing_code": "123456", "decision": decision, "reason": reason},
        headers=h)


def _verified_online_driver(h, phone="+237690000101", plate="CE123AB",
                            box_code="BOX-001", lat=6.5167, lng=14.3):
    """Un conducteur vérifié, en ligne, avec une position fraîche."""
    d = _register(h, phone=phone, plate=plate, box_code=box_code)
    r = _verify(h, d["id"])
    assert r.status_code == 200, r.text
    r = client.post(f"/drivers/{d['id']}/online", json={"online": True}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post(f"/drivers/{d['id']}/position",
                    json={"lat": lat, "lng": lng}, headers=h)
    assert r.status_code == 200, r.text
    return d


def _requested_ride(h, client_id="client-demo", origin_lat=6.5167, origin_lng=14.3):
    r = client.post("/rides", json={
        "client_id": client_id, "origin_lat": origin_lat, "origin_lng": origin_lng,
        "dest_lat": 6.5267, "dest_lng": 14.3, "duration_min": 5}, headers=h)
    assert r.status_code == 200, r.text
    ride_id = r.json()["id"]
    r = client.post(f"/rides/{ride_id}/request", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ inscription
def test_register_creates_pending_driver_and_moto():
    h = _headers()
    d = _register(h, plate="ce123ab")  # minuscules -> normalisées
    assert d["status"] == "pending"
    assert d["already_registered"] is False
    assert d["licence_number"] == "PERMIS-12345"
    assert len(d["motorcycles"]) == 1
    moto = d["motorcycles"][0]
    assert moto["plate"] == "CE123AB"
    assert moto["box_code"] == "BOX-001"
    assert moto["verified"] == 0  # pas encore vérifiée


def test_register_duplicate_plate_rejected():
    h = _headers()
    _register(h, phone="+237690000101", plate="CE123AB")
    r = client.post("/drivers/register", json={
        "user_id": "+237690000102", "full_name": "Autre",
        "id_document_type": "CNI", "id_document_ref": "CNI-111",
        "licence_number": "PERMIS-999",
        "motorcycle": {"plate": "CE123AB", "brand": "Honda"}}, headers=h)
    assert r.status_code == 409


def test_register_duplicate_box_code_rejected():
    h = _headers()
    _register(h, phone="+237690000101", plate="CE123AB", box_code="BOX-001")
    r = client.post("/drivers/register", json={
        "user_id": "+237690000102", "full_name": "Autre",
        "id_document_type": "CNI", "id_document_ref": "CNI-111",
        "licence_number": "PERMIS-999",
        "motorcycle": {"plate": "CE999ZZ", "brand": "Honda", "box_code": "BOX-001"}},
        headers=h)
    assert r.status_code == 409


def test_register_same_user_returns_existing():
    h = _headers()
    first = _register(h)
    again = _register(h, plate="CE999ZZ")  # autre plaque, même utilisateur
    assert again["already_registered"] is True
    assert again["id"] == first["id"]
    assert len(again["motorcycles"]) == 1  # la 2e moto n'est pas ajoutée
    assert again["motorcycles"][0]["plate"] == "CE123AB"


def test_register_missing_fields_400():
    h = _headers()
    base = {"user_id": "+237690000101", "full_name": "Test",
            "id_document_type": "CNI", "id_document_ref": "CNI-1",
            "licence_number": "PERMIS-1",
            "motorcycle": {"plate": "CE123AB"}}
    no_plate = dict(base, motorcycle={"plate": "  "})
    assert client.post("/drivers/register", json=no_plate, headers=h).status_code == 400
    no_licence = dict(base, licence_number=" ")
    assert client.post("/drivers/register", json=no_licence, headers=h).status_code == 400
    no_doc = dict(base, id_document_ref=" ")
    assert client.post("/drivers/register", json=no_doc, headers=h).status_code == 400


# ------------------------------------------------------------ vérification
def test_verify_wrong_pairing_code_403():
    h = _headers()
    d = _register(h)
    r = client.post(f"/drivers/{d['id']}/verify", json={
        "pairing_code": "000000", "decision": "verified"}, headers=h)
    assert r.status_code == 403


def test_verify_bad_decision_400():
    h = _headers()
    d = _register(h)
    r = client.post(f"/drivers/{d['id']}/verify", json={
        "pairing_code": "123456", "decision": "peut-etre"}, headers=h)
    assert r.status_code == 400


def test_verify_approve_sets_verified_and_role_and_moto():
    h = _headers()
    d = _register(h)
    r = _verify(h, d["id"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
    assert r.json()["verified_at"]
    assert r.json()["motorcycles"][0]["verified"] == 1
    conn = main.get_db()
    user = conn.execute(
        "SELECT role FROM app_users WHERE id = ?", (d["user_id"],)).fetchone()
    conn.close()
    assert user["role"] == "driver"


def test_verify_reject_sets_reason():
    h = _headers()
    d = _register(h)
    r = _verify(h, d["id"], decision="rejected", reason="Permis illisible.")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "Permis illisible."
    assert r.json()["online"] == 0


# ------------------------------------------------------------ en ligne
def test_online_requires_verified():
    h = _headers()
    d = _register(h)  # encore pending
    r = client.post(f"/drivers/{d['id']}/online", json={"online": True}, headers=h)
    assert r.status_code == 403


def test_online_toggle():
    h = _headers()
    d = _register(h)
    _verify(h, d["id"])
    on = client.post(f"/drivers/{d['id']}/online", json={"online": True}, headers=h)
    assert on.status_code == 200 and on.json()["online"] is True
    off = client.post(f"/drivers/{d['id']}/online", json={"online": False}, headers=h)
    assert off.status_code == 200 and off.json()["online"] is False


def test_position_sets_online_for_verified_only():
    h = _headers()
    d = _verified_online_driver(h)
    me = client.get("/drivers/me", params={"user_id": d["user_id"]}, headers=h)
    assert me.json()["online"] == 1
    # Un dossier en attente qui publie une position ne passe pas en ligne.
    pending = _register(h, phone="+237690000102", plate="CE999ZZ", box_code="BOX-002")
    r = client.post(f"/drivers/{pending['id']}/position",
                    json={"lat": 6.5167, "lng": 14.3}, headers=h)
    assert r.status_code == 200
    me = client.get("/drivers/me", params={"user_id": pending["user_id"]}, headers=h)
    assert me.json()["online"] == 0


# ------------------------------------------------------------ nearby
def test_nearby_only_verified_online_fresh():
    h = _headers()
    # A : vérifié, en ligne, position fraîche -> visible.
    a = _verified_online_driver(h, phone="+237690000101", plate="CE111AA",
                                box_code="BOX-A", lat=6.5167, lng=14.3)
    # B : vérifié, en ligne, position PÉRIMÉE (20 min) -> invisible.
    b = _verified_online_driver(h, phone="+237690000102", plate="CE222BB",
                                box_code="BOX-B", lat=6.5167, lng=14.3)
    conn = main.get_db()
    stale = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    conn.execute("UPDATE drivers SET last_seen_at=? WHERE id=?", (stale, b["id"]))
    conn.commit()
    conn.close()
    # C : vérifié mais hors ligne -> invisible.
    c = _register(h, phone="+237690000103", plate="CE333CC", box_code="BOX-C")
    _verify(h, c["id"])
    # D : en attente avec position fraîche -> invisible.
    d = _register(h, phone="+237690000104", plate="CE444DD", box_code="BOX-D")
    client.post(f"/drivers/{d['id']}/position",
                json={"lat": 6.5167, "lng": 14.3}, headers=h)

    r = client.get("/drivers/nearby", params={"lat": 6.5167, "lng": 14.3}, headers=h)
    assert r.status_code == 200, r.text
    drivers = r.json()["drivers"]
    assert [x["id"] for x in drivers] == [a["id"]]
    shown = drivers[0]
    assert shown["name"] == "Aboubakar Diallo"
    assert shown["distance_km"] == 0.0
    assert shown["rating_avg"] == 0
    assert shown["motorcycles"][0]["plate"] == "CE111AA"


def test_nearby_empty_without_drivers():
    h = _headers()
    r = client.get("/drivers/nearby", params={"lat": 6.5167, "lng": 14.3}, headers=h)
    assert r.status_code == 200
    assert r.json()["drivers"] == []


# ------------------------------------------------------------ demandes
def test_requests_requires_verified():
    h = _headers()
    d = _register(h)  # pending
    r = client.get("/drivers/requests", params={"driver_id": d["id"]}, headers=h)
    assert r.status_code == 403


def test_requests_lists_open_and_chosen_first():
    h = _headers()
    a = _verified_online_driver(h, phone="+237690000101", plate="CE111AA", box_code="BOX-A")
    b = _verified_online_driver(h, phone="+237690000102", plate="CE222BB", box_code="BOX-B")
    open_ride = _requested_ride(h, client_id="client-demo")
    chosen_ride = _requested_ride(h, client_id="client-demo")
    r = client.post(f"/rides/{chosen_ride['id']}/choose-driver",
                    json={"driver_id": a["id"]}, headers=h)
    assert r.status_code == 200, r.text

    seen_a = client.get("/drivers/requests", params={"driver_id": a["id"]}, headers=h)
    reqs = seen_a.json()["requests"]
    assert [x["id"] for x in reqs] == [chosen_ride["id"], open_ride["id"]]
    assert reqs[0]["chosen_for_me"] is True
    assert reqs[1]["chosen_for_me"] is False
    # B ne voit pas la course proposée à A, seulement la course ouverte.
    seen_b = client.get("/drivers/requests", params={"driver_id": b["id"]}, headers=h)
    assert [x["id"] for x in seen_b.json()["requests"]] == [open_ride["id"]]


# ------------------------------------------------------------ publication
def test_request_ride_transition():
    h = _headers()
    r = client.post("/rides", json={
        "client_id": "client-demo", "origin_lat": 6.5167, "origin_lng": 14.3,
        "dest_lat": 6.5267, "dest_lng": 14.3, "duration_min": 5}, headers=h)
    ride_id = r.json()["id"]
    assert r.json()["status"] == "draft"
    ok = client.post(f"/rides/{ride_id}/request", headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "requested"
    again = client.post(f"/rides/{ride_id}/request", headers=h)
    assert again.status_code == 409


# ------------------------------------------------------------ choix
def test_choose_driver_assigns_atomically():
    h = _headers()
    a = _verified_online_driver(h)
    ride = _requested_ride(h)
    r = client.post(f"/rides/{ride['id']}/choose-driver",
                    json={"driver_id": a["id"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["driver_id"] == a["id"]
    assert r.json()["motorcycle_id"] == a["motorcycles"][0]["id"]
    assert r.json()["status"] == "requested"  # en attente du « J'arrive »
    # Un deuxième conducteur ne peut plus être choisi sur cette course.
    b = _verified_online_driver(h, phone="+237690000102", plate="CE222BB", box_code="BOX-B")
    r2 = client.post(f"/rides/{ride['id']}/choose-driver",
                     json={"driver_id": b["id"]}, headers=h)
    assert r2.status_code == 409


def test_choose_driver_rejects_offline_and_unverified():
    h = _headers()
    ride = _requested_ride(h)
    # Vérifié mais hors ligne.
    offline = _register(h, phone="+237690000102", plate="CE222BB", box_code="BOX-B")
    _verify(h, offline["id"])
    r = client.post(f"/rides/{ride['id']}/choose-driver",
                    json={"driver_id": offline["id"]}, headers=h)
    assert r.status_code == 409
    # En attente de vérification.
    pending = _register(h, phone="+237690000103", plate="CE333CC", box_code="BOX-C")
    r = client.post(f"/rides/{ride['id']}/choose-driver",
                    json={"driver_id": pending["id"]}, headers=h)
    assert r.status_code == 409


def test_choose_driver_rejects_busy_driver():
    h = _headers()
    a = _verified_online_driver(h)
    ride1 = _requested_ride(h)
    ride2 = _requested_ride(h)
    r1 = client.post(f"/rides/{ride1['id']}/choose-driver",
                     json={"driver_id": a["id"]}, headers=h)
    assert r1.status_code == 200, r1.text
    # A est déjà engagé sur la course 1 : pas de 2e course.
    r2 = client.post(f"/rides/{ride2['id']}/choose-driver",
                     json={"driver_id": a["id"]}, headers=h)
    assert r2.status_code == 409


# ------------------------------------------------------------ J'arrive / refus
def test_accept_by_chosen_driver_only():
    h = _headers()
    a = _verified_online_driver(h)
    b = _verified_online_driver(h, phone="+237690000102", plate="CE222BB", box_code="BOX-B")
    ride = _requested_ride(h)
    client.post(f"/rides/{ride['id']}/choose-driver",
                json={"driver_id": a["id"]}, headers=h)
    # B n'est pas le conducteur choisi.
    assert client.post(f"/rides/{ride['id']}/accept",
                       json={"driver_id": b["id"]}, headers=h).status_code == 409
    ok = client.post(f"/rides/{ride['id']}/accept",
                     json={"driver_id": a["id"]}, headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "assigned"
    # Deuxième acceptation impossible (la course n'est plus 'requested').
    assert client.post(f"/rides/{ride['id']}/accept",
                       json={"driver_id": a["id"]}, headers=h).status_code == 409


def test_decline_returns_ride_to_requested_and_rechoice():
    h = _headers()
    a = _verified_online_driver(h)
    b = _verified_online_driver(h, phone="+237690000102", plate="CE222BB", box_code="BOX-B")
    ride = _requested_ride(h)
    client.post(f"/rides/{ride['id']}/choose-driver",
                json={"driver_id": a["id"]}, headers=h)
    declined = client.post(f"/rides/{ride['id']}/decline",
                           json={"driver_id": a["id"]}, headers=h)
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "requested"
    assert declined.json()["driver_id"] is None
    assert declined.json()["motorcycle_id"] is None
    # Le client peut choisir un autre conducteur.
    again = client.post(f"/rides/{ride['id']}/choose-driver",
                        json={"driver_id": b["id"]}, headers=h)
    assert again.status_code == 200, again.text
    assert again.json()["driver_id"] == b["id"]


def test_decline_by_other_driver_409():
    h = _headers()
    a = _verified_online_driver(h)
    b = _verified_online_driver(h, phone="+237690000102", plate="CE222BB", box_code="BOX-B")
    ride = _requested_ride(h)
    client.post(f"/rides/{ride['id']}/choose-driver",
                json={"driver_id": a["id"]}, headers=h)
    assert client.post(f"/rides/{ride['id']}/decline",
                       json={"driver_id": b["id"]}, headers=h).status_code == 409


# ------------------------------------------------------------ motos + cash
def test_add_motorcycle_and_list():
    h = _headers()
    d = _verified_online_driver(h)
    r = client.post(f"/drivers/{d['id']}/motorcycles", json={
        "plate": "CE777YY", "brand": "Honda", "model": "CG125",
        "color": "bleu", "box_code": "BOX-777"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["plate"] == "CE777YY"
    assert r.json()["verified"] == 1  # conducteur déjà vérifié
    dup = client.post(f"/drivers/{d['id']}/motorcycles", json={
        "plate": "CE777YY", "brand": "Honda"}, headers=h)
    assert dup.status_code == 409
    lst = client.get(f"/drivers/{d['id']}/motorcycles", headers=h)
    assert len(lst.json()["motorcycles"]) == 2


def test_cash_only_enforced():
    h = _headers()
    body = {"client_id": "client-demo", "origin_lat": 6.5167, "origin_lng": 14.3,
            "dest_lat": 6.5267, "dest_lng": 14.3, "duration_min": 5}
    r = client.post("/rides", json={**body, "payment_method": "mtn_momo"}, headers=h)
    assert r.status_code == 400
    r = client.post("/rides", json={**body, "payment_method": "cash"}, headers=h)
    assert r.status_code == 200


def test_my_driver_file():
    h = _headers()
    d = _register(h)
    me = client.get("/drivers/me", params={"user_id": d["user_id"]}, headers=h)
    assert me.status_code == 200
    assert me.json()["id"] == d["id"]
    assert me.json()["status"] == "pending"
    assert len(me.json()["motorcycles"]) == 1
    missing = client.get("/drivers/me", params={"user_id": "+237690000999"}, headers=h)
    assert missing.status_code == 404
