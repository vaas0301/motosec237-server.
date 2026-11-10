# DÉPLOIEMENT EN LIGNE — MOTOSEC 237 v0.2

Le serveur est **en ligne uniquement** (décision utilisateur, 2026-11-10).
Pas de serveur local Wi-Fi. Ce document donne la marche à suivre
concrète. Aucun prix définitif n'est affirmé : les offres gratuites /
peu chères changent ; vérifiez les conditions en vigueur au moment du
déploiement, et ne créez aucun compte payant sans l'avoir décidé.

## Option recommandée : Render, offre gratuite (Blueprint)

Le fichier `render.yaml` à la racine du dépôt déploie le serveur en un
clic, sans rien taper en ligne de commande. Étapes :

### 1. Mettre le code dans un dépôt GitHub

```bash
cd motosec237
git init
git add server/ db/ docs/ render.yaml
git commit -m "MOTOSEC 237 v0.2 — serveur en ligne"
git push   # vers votre dépôt GitHub
```

Ne jamais commiter : `.env`, `server_config.json`, `*.db`,
`app/android/local.properties`, `.venv/`.

### 2. Créer le service sur Render (compte gratuit, sans carte)

1. Créer un compte sur render.com (gratuit, pas de carte bancaire
   demandée pour l'offre gratuite).
2. New + → Blueprint → choisissez le dépôt GitHub.
3. Render lit `render.yaml` et demande **2 valeurs** :
   - `MOTOSEC_PAIRING_CODE` : code d'enregistrement des appareils
     (6 chiffres, à garder secret, à taper dans l'appli).
   - `GOOGLE_MAPS_API_KEY` : clé serveur Google, restreinte à l'API
     Directions (voir `docs/GOOGLE-MAPS.md`). Peut être ajoutée plus
     tard : sans elle, `/maps/route` répond 503 et l'appli retombe sur
     la ligne droite.
   `SECRET_KEY` est généré automatiquement par Render.
4. Render donne une URL, par exemple
   `https://motosec237-server.onrender.com`.

### 3. Tester

```bash
curl https://motosec237-server.onrender.com/health
# attendu : {"status":"ok","version":"0.2.0","mode":"online",...}
curl https://motosec237-server.onrender.com/config
```

L'offre gratuite s'endort après inactivité : le premier appel est lent
(quelques dizaines de secondes). C'est normal sur l'offre gratuite,
pas un bug.

### 4. Configurer l'appli

```bash
flutter run --dart-define=MOTOSEC_BASE_URL=https://motosec237-server.onrender.com
```

L'écran d'accueil doit afficher « Serveur en ligne :
https://motosec237-server.onrender.com ».

## Autres options (même code)

| Option | Idée | Points d'attention |
|---|---|---|
| Railway (crédit d'essai) | Déploiement depuis un dépôt Git | Crédit d'essai limité, puis facturation à l'usage |
| PythonAnywhere (offre gratuite) | Hébergement Python simple | Limites de l'offre gratuite (tâches, domaines) |
| VPS (petit serveur) | Contrôle total, Docker | À administrer (mises à jour, HTTPS, sauvegardes) |

Pour ces options, la commande de démarrage est :
`uvicorn main:app --host 0.0.0.0 --port $PORT` (ou déploiement Docker
avec le `Dockerfile` fourni, dossier `server/`).

## Variables d'environnement (À REMPLIR, aucune valeur réelle ici)

```
DATABASE_URL=sqlite:///./motosec237.db
SECRET_KEY=À_REMPLIR_chaine_aleatoire_longue
MOTOSEC_PAIRING_CODE=À_REMPLIR_6_chiffres
ALLOWED_ORIGINS=https://votre-domaine.exemple
MOTOSEC_DEMO_OTP=0
GOOGLE_MAPS_API_KEY=À_REMPLIR_cle_serveur_directions
```

`SECRET_KEY` : générez une chaîne aléatoire longue (par exemple avec
`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).
`MOTOSEC_PAIRING_CODE` : 6 chiffres, à garder secret, à communiquer
aux appareils à enregistrer.
`MOTOSEC_DEMO_OTP` : **0 en production** (1 = le code OTP est renvoyé
dans la réponse, DEV ONLY).

## HTTPS

Activez le HTTPS fourni par l'hébergeur (certificat automatique dans la
plupart des offres, Render inclus). L'appli Flutter n'accepte pas d'URL
en `http://` en production.

## Sauvegardes (dès le pilote)

La base SQLite est un fichier (`motosec237.db`) : sauvegardez-le
régulièrement (téléchargement / copie). En production, prévoyez la
bascule PostgreSQL (voir `docs/BASE-DONNEES.md`) avant de dépasser le
pilote de Meiganga.

## Ce qui n'est PAS fait ici

Aucun compte hébergeur n'a été créé, aucune URL de production n'existe :
l'URL `https://motosec237-server.onrender.com` est un exemple à
remplacer par la vôtre. Aucune clé, aucun mot de passe n'est inscrit
dans le code. La mise en ligne elle-même (création du compte Render et
clic sur Blueprint) reste à faire par l'utilisateur : ce sont ses
comptes.
