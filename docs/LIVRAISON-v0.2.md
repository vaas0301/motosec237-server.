# LIVRAISON v0.2 — Serveur en ligne + suivi Google Maps (2026-11-10, soir)

Phase 5 (itinéraire routier) + préparation complète de la mise en ligne.
Même base que la v0.1.1, mêmes tarifs provisoires, même design.

## Ce qui est nouveau

### 1. Serveur prêt à mettre en ligne (Render, offre gratuite)

- `render.yaml` à la racine : Blueprint Render — le serveur se déploie
  en un clic depuis un dépôt GitHub, sans ligne de commande.
- `SECRET_KEY` généré par Render ; 2 valeurs à saisir au déploiement :
  `MOTOSEC_PAIRING_CODE` (6 chiffres) et `GOOGLE_MAPS_API_KEY` (clé
  serveur Directions, peut être ajoutée plus tard).
- `MOTOSEC_DEMO_OTP=0` dans le Blueprint (jamais 1 en production).

### 2. Itinéraire routier Google (phase 5)

- Serveur : `GET /maps/route` — proxy de l'API Directions. La clé
  Google reste côté serveur (`GOOGLE_MAPS_API_KEY`), jamais dans
  l'appli. Sans clé : 503 clair, l'appli retombe sur la ligne droite.
- Appli : écrans Commander et Suivre affichent le vrai itinéraire
  routier (distance et durée réelles pour le tarif) ; la ligne droite
  n'apparaît plus que comme repli, étiquetée comme telle.
- Décodage de polyligne implémenté des deux côtés (Python + Dart),
  testé avec l'exemple canonique de Google.

### 3. Suivi live du conducteur (phase 5)

- Serveur : `GET /rides/{id}/track` (course + position conducteur +
  points GPS) et `POST /rides/{id}/position` (publication de position
  pendant une course).
- Appli : après une commande réussie, l'écran Suivre s'ouvre sur la
  course et déplace le marqueur orange du conducteur, interrogé toutes
  les 10 s. Bouton Recentrer. SOS inchangé. Mode dégradé hors ligne
  inchangé (une coupure réseau n'est jamais un incident).

## Vérifié ici (2026-11-10)

- Serveur : `pytest` **32/32 réussis** (22 v0.1 + 10 nouveaux :
  polyligne, proxy Directions, 503 sans clé, track/position).
- Serveur démarré en conditions production (`SECRET_KEY` rempli,
  `MOTOSEC_DEMO_OTP=0`, sans clé Directions) : `/health` OK v0.2.0,
  `/config` OK, enregistrement d'appareil OK, `/maps/route` répond
  503 avec le bon message, création de course + position + track OK.
- Appli : `flutter analyze` sans problème, `flutter test` **16/16**
  (12 v0.1 + 4 nouveaux : polyligne, repli, lecture JSON, repli sans
  serveur).
- APK non construite ici (même limite VM que la v0.1.1).

## Ce qui reste à faire par l'utilisateur (2 comptes, 5 minutes chacun)

1. **Serveur en ligne** — voir `docs/DEPLOIEMENT-EN-LIGNE.md` :
   pousser `server/ db/ docs/ render.yaml` sur GitHub, créer un compte
   gratuit Render, New → Blueprint → choisir le dépôt, saisir les
   2 valeurs, récupérer l'URL `https://...onrender.com`.
2. **Clés Google Maps** — voir `docs/GOOGLE-MAPS.md` : projet
   « MOTOSEC 237 », facturation activée (obligatoire), API Maps SDK
   for Android + Directions API, DEUX clés : carte (dans
   `app/android/local.properties`) et serveur (variable
   `GOOGLE_MAPS_API_KEY` sur Render).

Puis lancer : `flutter run --dart-define=MOTOSEC_BASE_URL=<url Render>`
(voir `docs/INSTALLATION.md`).

## Fichiers

- `MOTOSEC237-v0.2-serveur-suivi.zip` — 0.2.0+3 (appli), serveur 0.2.0.
- Contenu : app/ (Android réparé v0.1.1 inclus), server/, db/,
  docs/ (9 docs + 3 rapports de livraison), logo/, render.yaml.
