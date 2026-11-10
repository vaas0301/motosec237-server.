# LIVRAISON — MOTOSEC 237 v0.1, base épurée (2026-11-10)

## Ce qui a été livré

Zip : `MOTOSEC237-v0.1-base-epuree.zip` (app + server + db + docs + logo).
Copie : `~/workspace/your_files/MOTOSEC237-v0.1-base-epuree.zip`.

## Corrections de l'utilisateur appliquées

1. **Serveur EN LIGNE UNIQUEMENT** : pas de serveur local Wi-Fi, pas de
   port 8767, pas de `Lancer-Serveur.bat`. Le serveur FastAPI est conçu
   pour être déployé en ligne (Dockerfile, variables d'environnement,
   `docs/DEPLOIEMENT-EN-LIGNE.md`). La file d'attente `op_id` reste dans
   l'appli pour tenir quand le réseau de Meiganga coupe.
2. **Design combiné vert émeraude + bleu ciel** : vert = marque/boutons
   principaux, bleu ciel `#38BDF8` / clair `#E0F2FE` / foncé `#0284C7` =
   carte, suivi, boutons secondaires, « en cours ». Voir
   `docs/DESIGN-SYSTEM.md` (contraste vérifié).
3. **Google Maps obligatoire** : `google_maps_flutter`, carte centrée sur
   Meiganga (6.5167, 14.3 — coordonnées vérifiées), mode dégradé hors
   ligne. Clé API à créer par l'utilisateur (voir `docs/GOOGLE-MAPS.md`).
4. **Bilingue FR / EN** : choix de langue au premier lancement + dans
   Profil, choix persisté, chaînes FR/EN centralisées, test
   d'exhaustivité. Slogan EN proposé : « Every ride under control. »
   (à valider).

## Fichiers créés (34 + logo)

- `app/` : `pubspec.yaml`, `lib/main.dart`, `lib/theme.dart`,
  `lib/config.dart`, `lib/geo.dart`, `lib/otp.dart`, `lib/models.dart`,
  `lib/sync_queue.dart`, `lib/providers.dart`, `lib/widgets.dart`,
  `lib/l10n/app_strings.dart`, `lib/data/local_db.dart`,
  `lib/services/api_client.dart`, `lib/services/maps_service.dart`,
  écrans `language/home/order/tracking/profile/auth`,
  `android/.../AndroidManifest.xml` (clé `${MAPS_API_KEY}`),
  `android/app/build.gradle`, `assets/icon/app_icon.png` (logo choisi),
  `test/geo_test.dart`, `test/strings_test.dart`, `test/otp_test.dart`.
- `server/` : `main.py`, `geo.py`, `pricing.py`, `otp.py`,
  `requirements.txt`, `Dockerfile`, `.env.example`, `README.md`,
  `test_server.py`, `test_logic.py`.
- `db/schema.sql` : 17 tables métier + techniques (18 avec
  `sqlite_sequence`), portable PostgreSQL.
- `docs/` : `ARCHITECTURE.md`, `BASE-DONNEES.md`, `GOOGLE-MAPS.md`,
  `DESIGN-SYSTEM.md`, `ALGORITHMES.md`, `INSTALLATION.md`,
  `DEPLOIEMENT-EN-LIGNE.md`, ce rapport.
- `README.md`, `.gitignore`.

## Résultats RÉELS des vérifications (2026-11-10)

| Vérification | Commande | Résultat |
|---|---|---|
| Tests serveur Python | `pytest -q` (dans `server/`) | **22 passed, 0 failed** |
| Tests Flutter | `flutter test` (dans `app/`) | **12 passed, 0 failed** |
| Analyse Flutter | `flutter analyze` | **No issues found** |
| Logique Dart pure | script de 13 vérifications (`dart`) | **13/13 réussies** |
| Analyse Dart pure | `dart analyze` (geo/otp/strings) | **No issues found** |
| Schéma BDD | application de `schema.sql` sur base vide | **18 tables créées** |
| Serveur en vrai | `uvicorn` + `curl /health`, `/config`, `/pricing/estimate` | **200 OK** (`fare 1250 FCFA` pour 5 km / 10 min) |
| Secrets / IP locales | recherche `AIza`, clés, `192.168`, ports 8765/8766/8767 | **Aucun secret, aucune IP locale en dur** (le seul « 8767 » est la phrase qui dit qu'il n'y a pas de port 8767) |

Deux bugs ont été trouvés et corrigés par les tests (pas annoncés comme
réussis avant correction) : paramètre OTP manquant et clé étrangère
`client-demo` ; puis une attente de test fausse (distance 5,004 km et
non 5,000 km — le code avait raison, 1251 FCFA).

## État par catégorie

- **Conçu** : architecture en ligne, modèle relationnel, algorithmes
  (Haversine, proches, tarif, OTP, synchro), design system, i18n.
- **Développé** : appli Flutter (4 onglets + langue + auth OTP + SOS),
  API FastAPI (12 endpoints), schéma BDD, file `op_id`.
- **Testé** : voir tableau ci-dessus (Python + Flutter, exécutés ici).
- **Réellement opérationnel** : serveur en dev (`uvicorn`, `/health`
  OK) ; appli non encore lancée sur téléphone (pas d'APK construite
  ici — voir checklist).
- **Nécessite un service externe** : clé API Google Maps (à créer),
  hébergement en ligne (à choisir), SMS OTP (agrégateur à brancher).

## Ce que la v0.1 ne contient DÉLIBÉRÉMENT pas

Paiements MTN/Orange Money, colis, admin web, vérification conducteurs,
centre de sécurité opéré, itinéraire routier Directions (ligne droite en
v0.1), attribution concurrente, détection de déviation/immobilisation,
PostgreSQL/PostGIS (chemin documenté), APK.

## Checklist pour l'utilisateur

1. Dézipper `MOTOSEC237-v0.1-base-epuree.zip`.
2. Mettre le serveur en ligne (`docs/DEPLOIEMENT-EN-LIGNE.md`) et noter
   l'URL. Tester `…/health`.
3. Créer la clé Google Maps (`docs/GOOGLE-MAPS.md`), créer
   `app/android/local.properties` avec `MAPS_API_KEY=VOTRE_CLE`.
4. `cd app && flutter pub get && flutter run
   --dart-define=MOTOSEC_BASE_URL=https://votre-serveur.exemple`
5. Premier lancement : choisir FR ou EN, puis tester à Meiganga :
   commander une course (départ Meiganga centre), vérifier l'estimation,
   couper le réseau et vérifier que la course est mise en file d'attente
   puis envoyée au retour du réseau, tester le bouton SOS (alerte
   enregistrée, pas d'appel automatique).
6. Valider les tarifs provisoires sur le terrain avant tout lancement
   commercial (base 300, 150/km, 20/min, min 500 FCFA — à valider).

## Note sur les SDK

Pour vérifier pour de vrai, les SDK Dart 3.5.4 et Flutter 3.27.4 ont été
téléchargés dans `motosec237/.dart-sdk/` et `motosec237/flutter/` : ils
sont **exclus du zip** (voir `.gitignore`) et ne sont pas à livrer.
