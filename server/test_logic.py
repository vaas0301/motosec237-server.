"""Tests des algorithmes (Haversine, conducteurs proches, tarif, OTP)."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from geo import MEIGANGA_LAT, MEIGANGA_LNG, haversine_km, nearby_drivers  # noqa: E402
from otp import generate_otp, hash_otp, is_expired, otp_expires_at  # noqa: E402
from pricing import estimate_fare  # noqa: E402


def test_meiganga_centre():
    assert MEIGANGA_LAT == 6.5167 and MEIGANGA_LNG == 14.3


def test_haversine_same_point_zero():
    assert haversine_km(6.5167, 14.3, 6.5167, 14.3) == 0.0


def test_haversine_001_degree_north_about_1_11_km():
    d = haversine_km(6.5167, 14.3, 6.5267, 14.3)
    assert abs(d - 1.112) < 0.01, d


def test_haversine_invalid_lat_raises():
    try:
        haversine_km(100.0, 14.3, 6.5, 14.3)
    except ValueError:
        return
    raise AssertionError("lat 100 aurait dû lever ValueError")


def test_nearby_orders_by_distance_and_filters_radius():
    drivers = [
        {"id": "loin", "lat": 6.6167, "lng": 14.3},
        {"id": "proche", "lat": 6.5217, "lng": 14.3},
        {"id": "moyen", "lat": 6.5367, "lng": 14.3},
    ]
    out = nearby_drivers(drivers, 6.5167, 14.3, radius_km=5.0)
    assert [d["id"] for d in out] == ["proche", "moyen"]
    assert out[0]["distance_km"] < out[1]["distance_km"]


def test_nearby_empty_and_zero_radius():
    assert nearby_drivers([], 6.5167, 14.3) == []
    assert nearby_drivers([{"id": "x", "lat": 6.5167, "lng": 14.3}], 6.5167, 14.3, radius_km=0) == []


def test_fare_formula_5km_10min():
    r = estimate_fare(5.0, 10.0)
    assert r["fare_fcfa"] == 1250  # 300 + 750 + 200
    assert r["commission_fcfa"] == 188  # 15 % de 1250 arrondi
    assert r["driver_share_fcfa"] == 1250 - 188


def test_fare_minimum_applies():
    assert estimate_fare(0, 0)["fare_fcfa"] == 500


def test_fare_negative_raises():
    try:
        estimate_fare(-1, 0)
    except ValueError:
        return
    raise AssertionError("distance négative aurait dû lever ValueError")


def test_otp_format_and_hash():
    code = generate_otp()
    assert len(code) == 6 and code.isdigit()
    assert hash_otp(code) != code
    assert hash_otp(code) == hash_otp(code)


def test_otp_expiry():
    assert not is_expired(otp_expires_at().isoformat())
    past = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    assert is_expired(past)
