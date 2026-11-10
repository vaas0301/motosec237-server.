"""MOTOSEC 237 — estimation de tarif (PARAMÈTRES PROVISOIRES À VALIDER).
Formule : tarif = max(tarif_minimum, base + distance_km * prix_km
                     + durée_min * prix_minute)
Commission plateforme : 15 % du tarif (paramètre modifiable).
Ces chiffres sont des VALEURS PROVISOIRES pour tester la base v0.1, PAS un
tarif définitif : ils doivent être validés sur le terrain à Meiganga
(terrain, carburant, concurrence) avant tout lancement commercial.
"""
BASE_FARE_FCFA = 300
PRICE_PER_KM_FCFA = 150
PRICE_PER_MIN_FCFA = 20
MIN_FARE_FCFA = 500
COMMISSION_RATE = 0.15


def estimate_fare(distance_km, duration_min=0.0):
    if distance_km < 0 or duration_min < 0:
        raise ValueError("distance et durée doivent être >= 0")
    fare = BASE_FARE_FCFA + distance_km * PRICE_PER_KM_FCFA + duration_min * PRICE_PER_MIN_FCFA
    fare = max(MIN_FARE_FCFA, int(round(fare)))
    commission = int(round(fare * COMMISSION_RATE))
    return {"fare_fcfa": fare, "commission_fcfa": commission,
            "driver_share_fcfa": fare - commission}
