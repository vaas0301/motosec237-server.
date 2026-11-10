"""MOTOSEC 237 v0.2 — itinéraire routier Google Maps (proxy serveur).

Pourquoi un proxy serveur : la clé API Google ne doit JAMAIS être dans
l'appli Flutter. L'appli appelle son propre serveur
(GET /maps/route), le serveur appelle l'API Directions Google avec la
clé lue dans la variable d'environnement GOOGLE_MAPS_API_KEY, et ne
renvoie à l'appli que l'itinéraire (points, distance, durée).

Sans clé configurée : l'endpoint répond 503 avec un message clair, et
l'appli retombe sur la ligne droite (approximation documentée).
Sans réseau / clé invalide : 502, même repli côté appli.

Bibliothèque standard uniquement (urllib) : aucune dépendance ajoutée.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


class MapsRouteError(Exception):
    """Erreur itinéraire, avec un message destiné à l'appli (jamais la clé)."""


def decode_polyline(encoded):
    """Décode une polyligne encodée Google en liste de (lat, lng).

    Algorithme public de Google (encodage delta + varint). Testé dans
    test_maps_route.py avec une polyligne de référence.
    """
    points = []
    index = 0
    lat = 0
    lng = 0
    while index < len(encoded):
        for delta in ("lat", "lng"):
            shift = 0
            result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if (result & 1) else (result >> 1)
            if delta == "lat":
                lat += d
            else:
                lng += d
        points.append((lat / 1e5, lng / 1e5))
    return points


def _get_json(url, opener=None):
    opener = opener or urllib.request.urlopen
    try:
        with opener(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MapsRouteError(f"Directions Google : HTTP {e.code}.")
    except urllib.error.URLError:
        raise MapsRouteError("Directions Google injoignable (réseau).")
    except TimeoutError:
        raise MapsRouteError("Directions Google : délai dépassé.")
    except Exception:
        raise MapsRouteError("Directions Google : réponse illisible.")


def fetch_route(origin_lat, origin_lng, dest_lat, dest_lng, api_key, opener=None):
    """Itinéraire routier entre deux points via l'API Directions.

    Retourne {"points": [(lat, lng), ...], "distance_km": float,
    "duration_min": float, "summary": str, "source": "directions"}.
    Lève MapsRouteError si la clé manque ou si Google refuse / échoue.
    """
    if not api_key:
        raise MapsRouteError(
            "Clé Directions non configurée côté serveur (GOOGLE_MAPS_API_KEY)."
        )
    params = urllib.parse.urlencode({
        "origin": f"{origin_lat},{origin_lng}",
        "destination": f"{dest_lat},{dest_lng}",
        "mode": "driving",
        "key": api_key,
    })
    data = _get_json(f"{DIRECTIONS_URL}?{params}", opener=opener)
    status = data.get("status")
    if status != "OK":
        if status == "ZERO_RESULTS":
            raise MapsRouteError("Aucun itinéraire routier trouvé entre ces deux points.")
        if status in ("REQUEST_DENIED", "OVER_QUERY_LIMIT"):
            raise MapsRouteError(
                f"Directions Google refusée ({status}) : vérifiez la clé et "
                "l'activation de l'API Directions dans Google Cloud."
            )
        raise MapsRouteError(f"Directions Google : statut {status}.")
    routes = data.get("routes") or []
    if not routes:
        raise MapsRouteError("Directions Google : aucun itinéraire renvoyé.")
    route = routes[0]
    legs = route.get("legs") or []
    distance_m = sum((leg.get("distance") or {}).get("value", 0) for leg in legs)
    duration_s = sum((leg.get("duration") or {}).get("value", 0) for leg in legs)
    encoded = ((route.get("overview_polyline") or {}).get("points") or "")
    points = decode_polyline(encoded) if encoded else []
    if not points:
        points = [(origin_lat, origin_lng), (dest_lat, dest_lng)]
    return {
        "points": points,
        "distance_km": round(distance_m / 1000, 3),
        "duration_min": round(duration_s / 60, 1),
        "summary": route.get("summary", ""),
        "source": "directions",
    }
