"""MOTOSEC 237 — géographie (Haversine, conducteurs proches).
Formules documentées dans docs/ALGORITHMES.md. Coordonnées WGS 84.
Meiganga (centre pilote) : 6.5167 N, 14.3 E (sources : geodatos / latlong.info).
"""
import math

EARTH_RADIUS_KM = 6371.0
MEIGANGA_LAT = 6.5167
MEIGANGA_LNG = 14.3


def haversine_km(lat1, lng1, lat2, lng2):
    """Distance orthodromique en km (Haversine).
    d = 2 * R * asin(sqrt(sin²((lat2-lat1)/2) + cos(lat1)*cos(lat2)*sin²((lng2-lng1)/2)))
    Hypothèses : Terre sphérique R = 6371 km ; suffisant pour Meiganga
    (erreur < 0,5 % sur des trajets urbains de quelques km).
    """
    for v, name, lo, hi in ((lat1, "lat1", -90, 90), (lat2, "lat2", -90, 90),
                            (lng1, "lng1", -180, 180), (lng2, "lng2", -180, 180)):
        if not (lo <= v <= hi):
            raise ValueError(f"{name} hors limites : {v}")
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearby_drivers(drivers, lat, lng, radius_km=5.0):
    """Classe les conducteurs par distance croissante, dans le rayon donné.
    drivers : liste de dicts avec lat, lng, id. Retour : liste triée
    [{id, distance_km}] — ne retient que les conducteurs en ligne (le
    filtrage 'en ligne' est fait par l'appelant via le champ online).
    Cas limites : rayon <= 0 -> liste vide ; aucun conducteur -> [].
    """
    if radius_km <= 0:
        return []
    out = []
    for d in drivers:
        dist = haversine_km(lat, lng, d["lat"], d["lng"])
        if dist <= radius_km:
            out.append({"id": d["id"], "distance_km": round(dist, 3)})
    out.sort(key=lambda x: x["distance_km"])
    return out
