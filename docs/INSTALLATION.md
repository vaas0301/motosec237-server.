# INSTALLATION — MOTOSEC 237 v0.1

Tout en français. Il n'y a **pas d'étape serveur local** : le serveur est
en ligne uniquement (voir `docs/DEPLOIEMENT-EN-LIGNE.md`).

## Prérequis

- Flutter 3.27+ (SDK) et Android Studio (ou VS Code + extension Flutter).
- Python 3.12 (pour tester le serveur en dev).
- Un compte Google Cloud (pour la clé Google Maps, voir
  `docs/GOOGLE-MAPS.md`).
- Un téléphone Android (l'APK n'est pas construite ici).

## 1. Récupérer la base

Dézipper `MOTOSEC237-v0.1-base-epuree.zip` dans un dossier de travail.

## 2. Mettre le serveur en ligne (obligatoire avant l'appli)

Suivre `docs/DEPLOIEMENT-EN-LIGNE.md` et noter l'URL obtenue, par
exemple `https://votre-serveur.exemple` (c'est un exemple, pas une URL
réelle). Tester : `https://votre-serveur.exemple/health` doit répondre
`{"status": "ok", "mode": "online", ...}`.

## 3. Créer la clé Google Maps

Suivre `docs/GOOGLE-MAPS.md`, puis créer `app/android/local.properties` :

```
MAPS_API_KEY=VOTRE_CLE_ICI
```

## 4. Lancer l'appli

```bash
cd app
flutter pub get
flutter run --dart-define=MOTOSEC_BASE_URL=https://votre-serveur.exemple
```

Sans `--dart-define`, l'appli démarre en **mode démo locale** (affiché
sur l'écran d'accueil) : les courses sont mises en file d'attente, rien
n'est envoyé.

## 5. Tester le serveur en dev (optionnel, pour les développeurs)

```bash
cd server
python3 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt
MOTOSEC_PAIRING_CODE=123456 ../.venv/bin/python -m pytest -v
MOTOSEC_PAIRING_CODE=123456 ../.venv/bin/uvicorn main:app --port 8000
```

Ceci lance le même code que le serveur en ligne, sur la machine de dev,
**uniquement pour tester** — ce n'est pas un mode « serveur local » du
produit.

## 6. Ajouter une langue

Ajouter une entrée dans `app/lib/l10n/app_strings.dart`, ajouter le
`Locale` dans `app/lib/main.dart`, relancer `flutter test` (le test
`strings_test.dart` impose les mêmes clés dans toutes les langues).

## Dépannage

- Carte vide → clé Google Maps absente ou invalide (voir GOOGLE-MAPS.md).
- « Serveur en ligne non configuré » → `--dart-define` oublié.
- « Appareil non enregistré » → enregistrer l'appareil avec le code
  d'appairage (`POST /devices/register`).
- « Opérations conservées en attente » → pas de réseau : normal, elles
  partiront quand le réseau revient.
