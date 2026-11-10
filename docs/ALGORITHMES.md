# ALGORITHMES — MOTOSEC 237 v0.1

Implémentations miroir : `server/geo.py`, `server/pricing.py`,
`server/otp.py` (Python) et `app/lib/geo.dart`, `app/lib/otp.dart`
(Dart). Les tests Python et Flutter doivent donner les mêmes résultats.

## 1. Distance par Haversine

```
a = sin²((lat2-lat1)/2) + cos(lat1)·cos(lat2)·sin²((lng2-lng1)/2)
d = 2 · R · asin(√a),  R = 6371 km
```
Variables : latitudes/longitudes en degrés (WGS 84). Hypothèse : Terre
sphérique (erreur < 0,5 % sur des trajets urbains). Cas limites : même
point → 0 ; latitude hors [-90, 90] ou longitude hors [-180, 180] →
erreur. Vérifié : Meiganga → 0,01° nord ≈ 1,112 km.

## 2. Recherche et classement des conducteurs proches

Entrée : position du client, liste des conducteurs **avec position
connue**, rayon (défaut 5 km). Pour chaque conducteur : distance
Haversine ; on garde ceux dans le rayon, triés par distance croissante.
Cas limites : rayon ≤ 0 → liste vide ; aucun conducteur → liste vide
(pas de faux conducteur inventé). La position d'un conducteur est sa
dernière position connue (`drivers.last_lat/last_lng`).

## 3. Attribution concurrente des courses

Non construite en v0.1 (phase 4). Principe prévu : une course `requested`
n'est attribuée qu'à un seul conducteur (transition d'état atomique en
base, premier acceptant gagne, les autres reçoivent « déjà attribuée »).

## 4. Estimation des tarifs (PARAMÈTRES PROVISOIRES À VALIDER)

```
tarif = max(tarif_minimum, base + distance_km × prix_km + durée_min × prix_minute)
commission = tarif × 15 %
```
Valeurs provisoires v0.1 : base 300 FCFA, 150 FCFA/km, 20 FCFA/min,
minimum 500 FCFA. Ce ne sont **pas** des tarifs définitifs : à valider
sur le terrain à Meiganga avant tout lancement commercial. Exemple
vérifié : 5 km, 10 min → 300 + 750 + 200 = 1250 FCFA.

## 5. Suivi GPS

Points GPS (`gps_points`) : latitude, longitude, précision, vitesse,
horodatage, liés à la course. Synchronisés par `op_id` (jamais deux
fois). Sans réseau : stockés localement, envoyés au retour du réseau.

## 6. Détection des déviations / 7. Immobilisations anormales

Non construites en v0.1 (phase 5/6). Principe prévu : comparaison de la
position à l'itinéraire prévu (seuil de distance + durée), signalement
comme **anomalie à qualifier par un opérateur humain**, jamais comme une
preuve d'agression ou de vol.

## 8. Alertes SOS

Bouton SOS → `POST /sos` → incident `kind='sos'`, `status='open'`.
Aucun appel automatique en v0.1 : un opérateur doit qualifier l'alerte.

## 9. Vérification OTP

Code 6 chiffres, validité 10 minutes, 5 tentatives maximum puis blocage
15 minutes. Codes hachés (SHA-256) en base, jamais en clair. En v0.1 le
code ne part pas encore par SMS (agrégateur à brancher) ; en dev, le
serveur peut le renvoyer si `MOTOSEC_DEMO_OTP=1` (jamais en production).

## 10. Traçabilité des colis

Non construite en v0.1 (phase 7). Principe prévu : `tracking_code`
unique par colis, événements horodatés (`ride_events`), OTP à la
livraison, preuve de livraison.

## 11. Transitions d'état

Course : `draft → requested → assigned → ongoing → completed /
cancelled`. Seules les transitions autorisées sont acceptées (contrôle
applicatif, phase 4). En v0.1 seule la création du brouillon est
implémentée.

## 12. Synchronisation après une coupure réseau

File d'attente locale (SQLite, table `outbox`) : chaque opération a un
`op_id` (UUID). Envoi → accusé (`acked`) : suppression locale. Doublon
(`duplicates`) : suppression sans re-compter. Conflit (même `op_id`,
contenu différent) : le premier enregistrement est gardé, le conflit est
journalisé, rien n'est écrasé. Une opération n'est jamais supprimée avant
l'accusé.
