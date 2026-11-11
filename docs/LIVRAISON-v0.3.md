# LIVRAISON v0.3 — Circuit conducteur (2026-11-11)

Phase 3 : le motoman s'inscrit, l'admin vérifie, le conducteur se met
en ligne, voit les demandes des clients et dit « J'arrive » ; le
client voit les motos disponibles et choisit celle qui pourra venir.
Même base que la v0.2, mêmes tarifs provisoires, même design.

## Ce qui est nouveau

### 1. Inscription conducteur (serveur + appli)

- Serveur : `POST /drivers/register` — dossier conducteur (téléphone,
  nom, type de pièce CNI/passeport + numéro, numéro de permis) +
  première moto (plaque UNIQUE, marque, modèle, couleur, code boîtier
  optionnel mais UNIQUE quand il est renseigné). Statut initial
  `pending`. Un seul dossier par utilisateur (un 2e envoi renvoie le
  dossier existant, sans doublon). Plaque ou code boîtier déjà pris :
  409 clair.
- Appli : Profil → « Mon dossier conducteur » → « Devenir conducteur »
  (formulaire avec validation : téléphone, plaque, permis, pièce
  obligatoires).

### 2. Vérification par l'admin (sans admin web)

- Serveur : `POST /drivers/{id}/verify` — `{"pairing_code": ...,
  "decision": "verified"|"rejected", "reason": "..."}`. Protégé par
  le code d'appairage (le même que l'enregistrement des appareils) :
  en attendant l'admin web (phase 9), c'est l'admin qui appelle cet
  endpoint. `verified` : dossier vérifié, rôle `driver` dans
  `app_users`, motos vérifiées. `rejected` : dossier refusé, motif
  conservé (`rejection_reason`) et visible par le conducteur.
- Appli : « Mon dossier conducteur » affiche le statut (en attente /
  vérifié / refusé + motif / suspendu) et les motos.

### 3. En ligne / hors ligne

- Serveur : `POST /drivers/{id}/online` (`{"online": true|false}`,
  vérifiés seulement) et `POST /drivers/{id}/position` (publier sa
  position met un conducteur vérifié en ligne).
- Une position « en ligne » n'est valable que 10 minutes : un
  conducteur qui oublie de se mettre hors ligne disparaît tout seul
  de la liste (pas de marqueur figé). Hors ligne, il disparaît
  immédiatement.
- Appli : bascule « En ligne / Hors ligne » dans le dossier
  conducteur (vérifiés seulement).

### 4. Le client choisit, le conducteur dit « J'arrive »

- Serveur :
  - `POST /rides/{id}/request` — le client publie sa course
    (draft → requested).
  - `GET /drivers/nearby?lat&lng` — conducteurs que le client peut
    choisir : vérifiés, en ligne, position fraîche. Chacun avec son
    nom, sa note, sa distance et ses motos vérifiées (plaque, marque,
    modèle, couleur). Aucun conducteur inventé.
  - `POST /rides/{id}/choose-driver` — attribution atomique : un
    seul conducteur par course (le 2e choix reçoit 409), conducteur
    vérifié + en ligne + avec une moto vérifiée + pas déjà engagé
    sur une autre course. La course reste `requested` : c'est au
    conducteur de confirmer.
  - `GET /drivers/requests?driver_id=...` — demandes visibles par le
    conducteur vérifié : courses ouvertes + celles qui lui sont
    proposées (`chosen_for_me`, en premier).
  - `POST /rides/{id}/accept` — « J'arrive » : seul le conducteur
    choisi peut accepter, la course passe en `assigned`.
  - `POST /rides/{id}/decline` — le conducteur choisi refuse : la
    course redevient `requested` sans conducteur, le client peut en
    choisir un autre.
- Appli :
  - Commander : après la création de la course, l'appli la publie
    puis ouvre « Choisir un conducteur » (nom, moto, plaque, note,
    distance, bouton Choisir). Si le conducteur vient d'être pris
    (409), la liste est actualisée. Puis le suivi live (v0.2).
  - Dossier conducteur → « Demandes de courses » (actualisé toutes
    les 10 s) : « J'arrive » / « Refuser » sur les courses proposées.

### 5. Paiement en espèces uniquement

Décision utilisateur du 2026-11-11 : pas de MTN MoMo ni Orange Money
(phase 8 annulée). Le Profil affiche « Espèces (cash) » et le
serveur refuse toute autre méthode (`POST /rides` avec
`payment_method` différent de `cash` → 400).

### 6. Autres

- `compileSdk = 36` dans `app/android/app/build.gradle.kts` (correctif
  appliqué par l'utilisateur sur la v0.2, repris ici : ne pas revenir
  à 34). `targetSdk` et `minSdk` inchangés.
- Icônes lanceur = logo M-route choisi (correctif v0.2.1 repris ici).
- Versions : appli 0.3.0+4, serveur 0.3.0.
- Base de données : nouvelles colonnes `drivers.online`,
  `drivers.rejection_reason`, `motorcycles.box_code` (unique quand
  renseigné). La migration est automatique au démarrage du serveur
  (ALTER TABLE) : la base Render existante est mise à jour toute
  seule au premier redémarrage, sans rien faire.
- `GET /drivers/nearby` ne renvoie plus seulement des positions :
  la réponse contient maintenant nom, note, distance et motos.

## Vérifié ici (2026-11-11)

- Serveur : `pytest` **58/58 réussis** (32 v0.1/v0.2 + 26 nouveaux :
  inscription, doublons plaque/boîtier, vérification admin,
  en ligne, nearby vérifié+en ligne+frais, demandes, choix atomique,
  accept/refus, cash uniquement).
- Migration v0.2 → v0.3 testée sur une base v0.2 réelle : les 3
  colonnes sont créées au démarrage, et l'unicité du code boîtier est
  appliquée sur la base migrée.
- Serveur démarré en conditions production (`SECRET_KEY` rempli,
  `MOTOSEC_DEMO_OTP=0`, sans clé Directions) : `/health` OK v0.3.0,
  puis le circuit complet en curl : inscription → pending →
  vérification → verified → en ligne + position → course publiée →
  nearby (conducteur visible avec sa moto) → choix → demande
  `chosen_for_me` → « J'arrive » → `assigned` → suivi OK.
- Appli : `flutter analyze` et `flutter test` NON exécutables ici
  (pas de Flutter dans la VM de construction) — le code Dart a été
  relu avec soin (imports, types, clés FR/EN, Riverpod), mais il
  RESTE À VÉRIFIER sur le PC : `flutter analyze` puis `flutter test`
  (16 tests v0.2 + 9 nouveaux : validation, lecture JSON, appels API).

## Comment appliquer (dossier complet v0.3)

Ce zip contient le projet ENTIER (même structure que la v0.2).

1. **Remplacer le contenu du dossier** `C:\MOTOSEC237-v0.2-serveur-suivi`
   par le contenu de ce zip (copier-coller, accepter le remplacement
   des fichiers). **Ne PAS supprimer le dossier lui-même** : il
   contient `.git` (pour pousser le serveur) et `local.properties`
   (clé carte, si elle existe). Aucun fichier à supprimer.
2. **Pousser le serveur sur GitHub** (Render redéploie tout seul) :
   ```
   cd C:\MOTOSEC237-v0.2-serveur-suivi
   git add server db docs render.yaml README.md
   git commit -m "MOTOSEC v0.3 : circuit conducteur"
   git push origin main
   ```
   Dépôt : https://github.com/vaas0301/motosec237-server..git
   (le point final fait partie de l'adresse). Attendre que Render
   affiche « Deployed », puis vérifier :
   `curl https://<votre-serveur>.onrender.com/health`
   → `"version":"0.3.0"`.
3. **Relancer l'appli** (le serveur est déjà en ligne, pas besoin de
   le relancer en local) :
   ```
   cd C:\MOTOSEC237-v0.2-serveur-suivi\app
   flutter run --dart-define=MOTOSEC_BASE_URL=https://<votre-serveur>.onrender.com
   ```
   Gradle a déjà téléchargé ses dépendances lors du build v0.2 : ce
   lancement réutilise le cache, il est nettement plus rapide que
   le premier (18 minutes).

## Validation admin (curl, depuis n'importe quel terminal)

Remplacer `VOTRE_SERVEUR`, `CODE_APPAIRAGE` et `ID_CONDUCTEUR` :

```
# 1. Voir le dossier (ou dans l'appli : Profil → Mon dossier)
curl "https://VOTRE_SERVEUR/drivers/me?user_id=%2B237690000101" \
  -H "X-Device-Token: VOTRE_JETON_APPAREIL"

# 2. Vérifier le dossier
curl -X POST "https://VOTRE_SERVEUR/drivers/ID_CONDUCTEUR/verify" \
  -H "X-Device-Token: VOTRE_JETON_APPAREIL" \
  -H "Content-Type: application/json" \
  -d '{"pairing_code":"CODE_APPAIRAGE","decision":"verified"}'

# 2bis. Refuser le dossier (motif visible par le conducteur)
curl -X POST "https://VOTRE_SERVEUR/drivers/ID_CONDUCTEUR/verify" \
  -H "X-Device-Token: VOTRE_JETON_APPAREIL" \
  -H "Content-Type: application/json" \
  -d '{"pairing_code":"CODE_APPAIRAGE","decision":"rejected","reason":"Permis illisible."}'
```

Le jeton d'appareil (`X-Device-Token`) est celui que l'appli a reçu à
l'enregistrement ; en test, on peut aussi en créer un avec
`POST /devices/register` (code d'appairage).

## Test bout en bout (2 téléphones, ou 1 téléphone + curl)

1. Téléphone A (motoman) : Profil → Mon dossier conducteur →
   Devenir conducteur → remplir (téléphone, CNI, permis, moto) →
   Envoyer. Statut : en attente.
2. Admin : vérifier le dossier (curl ci-dessus, ou plus tard
   l'admin web). Statut : vérifié.
3. Téléphone A : bascule « En ligne » (publie la position).
4. Téléphone B (client) : Commander → choisir la destination →
   Commander → la liste des conducteurs s'affiche (nom, moto,
   plaque, distance) → Choisir → le suivi s'ouvre.
5. Téléphone A : Demandes de courses → la course proposée →
   « J'arrive » → la course passe en `assigned`, le client voit la
   moto arriver sur la carte (suivi v0.2).
6. Variante refus : téléphone A refuse → la course redevient
   disponible, le client en choisit un autre.

## Simplifications connues de la v0.3 (à ne pas confondre avec des bugs)

- **Position « en ligne » = centre de Meiganga.** L'appli n'a pas
  encore le GPS réel du téléphone (pas de paquet geolocator) : quand
  le conducteur se met en ligne, c'est la position du centre de
  Meiganga qui est publiée. Tous les conducteurs en ligne sont donc
  à la même position pour l'instant. Le GPS réel sera branché dans
  une phase ultérieure.
- **Moto ajoutée par un conducteur déjà vérifié = vérifiée
  directement** (le conducteur est de confiance après vérification).
  L'admin peut suspendre le conducteur à tout moment (statut
  `suspended` : invisible des demandes et du nearby).
- **Le nom du client affiché au conducteur** est « Utilisateur
  client-d… » tant que le client n'a pas de nom enregistré (le
  client est identifié par `client-demo` dans l'appli v0.3).
- **Pas de notification** quand une course est proposée au
  conducteur : il faut ouvrir « Demandes de courses » (actualisé
  toutes les 10 s).
- **Une course hors ligne** (créée sans réseau) reste en `draft`
  dans la file d'attente : il faut la republier une fois de retour
  en ligne (Commander à nouveau).

## Fichiers

- `MOTOSEC237-v0.3-complet.zip` — 0.3.0+4 (appli), serveur 0.3.0.
- Contenu : app/ (circuit conducteur + compileSdk 36 + icônes logo),
  server/, db/, docs/ (dont ce fichier), logo/, render.yaml, README.md.

## Fichiers nouveaux / modifiés (v0.3)

Nouveaux : `server/test_drivers.py`, `app/lib/screens/driver_register_screen.dart`,
`app/lib/screens/driver_file_screen.dart`, `app/lib/screens/driver_requests_screen.dart`,
`app/lib/screens/choose_driver_screen.dart`, `app/test/driver_test.dart`,
`docs/LIVRAISON-v0.3.md`.
Modifiés : `server/main.py`, `db/schema.sql`, `app/lib/services/api_client.dart`,
`app/lib/models.dart`, `app/lib/l10n/app_strings.dart`,
`app/lib/screens/order_screen.dart`, `app/lib/screens/profile_screen.dart`,
`app/lib/main.dart`, `app/pubspec.yaml`, `app/android/app/build.gradle.kts`
(compileSdk 36), `server/test_server.py` (version 0.3.0),
`docs/DEPLOIEMENT-EN-LIGNE.md` (version 0.3.0), `docs/BASE-DONNEES.md`,
`README.md`, icônes `app/android/app/src/main/res/mipmap-*/ic_launcher.png`.
Aucun fichier à supprimer.
