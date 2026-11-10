# GOOGLE MAPS — MOTOSEC 237 v0.2

L'appli est liée à **Google Maps** (décision utilisateur, 2026-11-10).
Carte centrée sur Meiganga (6.5167 N, 14.3 E), marqueurs départ /
destination, suivi GPS. Paquet : `google_maps_flutter`.

**Nouveau en v0.2 (phase 5) : l'itinéraire routier.** L'écran Commander
et l'écran Suivre affichent le vrai itinéraire routier Google (pas une
ligne droite) quand le serveur est en ligne et que sa clé Directions
est configurée. Sans ça, l'appli retombe sur la ligne droite et
l'affiche comme telle.

## 1. DEUX clés, deux endroits (ne pas les confondre)

| Clé | Où elle vit | Sert à | Restriction |
|---|---|---|---|
| **Clé carte (Android)** | `app/android/local.properties` → `MAPS_API_KEY=...` | Afficher la carte dans l'appli | Applications Android (`com.motosec237.app` + SHA-1) + API Maps SDK for Android |
| **Clé serveur (Directions)** | Variable d'environnement `GOOGLE_MAPS_API_KEY` sur l'hébergeur | Itinéraire routier via le proxy `GET /maps/route` | API Directions uniquement |

Les deux clés viennent du **même projet Google Cloud « MOTOSEC 237 »**
(c'est plus simple), mais ce sont deux clés différentes. La clé serveur
n'est JAMAIS dans l'appli Flutter ni dans le code : elle reste côté
serveur. La clé carte n'est JAMAIS dans le code : elle arrive dans
`AndroidManifest.xml` via `${MAPS_API_KEY}` (`manifestPlaceholders`
dans `android/app/build.gradle.kts`).

## 2. Ce que l'utilisateur doit faire (compte Google, facturation)

Aucune clé n'est fournie dans ce livrable. Étapes :

1. Aller sur Google Cloud Console (compte Google).
2. Créer un projet (par exemple « MOTOSEC 237 »).
3. Activer la facturation sur le projet (obligatoire pour Google Maps —
   il y a un crédit gratuit mensuel de Google, vérifiez les conditions
   en vigueur au moment de l'activation ; aucun prix n'est affirmé ici).
4. Activer les API : **Maps SDK for Android** (obligatoire pour la
   carte) et **Directions API** (obligatoire pour l'itinéraire routier
   v0.2). Distance Matrix API : utile plus tard, pas nécessaire en v0.2.
5. Créer **deux** clés API (Identifiants → Créer une clé API) et les
   restreindre comme dans le tableau ci-dessus.
6. Clé carte : dans `app/android/local.properties` (fichier non
   versionné, à créer), ajouter : `MAPS_API_KEY=<votre clé carte>`
7. Clé serveur : dans le tableau de bord Render (ou autre hébergeur),
   variable d'environnement `GOOGLE_MAPS_API_KEY=<votre clé serveur>`.
8. Recompiler l'appli (`flutter run` / `flutter build apk`) et
   redéployer le serveur si la clé serveur a été ajoutée après.

## 3. Sans clé, que se passe-t-il ?

- Sans clé carte : Google Maps affiche une carte vide / un message
  d'erreur : c'est normal, il faut la clé. L'appli reste utilisable
  (commande, file d'attente, profils) mais sans carte.
- Sans clé serveur : l'itinéraire affiché est la **ligne droite**,
  avec la mention « Ligne droite — itinéraire routier indisponible ».
  Le reste fonctionne normalement. `/health` du serveur indique
  `"maps_route": "cle_non_configuree"`.

## 4. Sans réseau (Meiganga), que se passe-t-il ?

Google Maps exige internet. Sans réseau, l'écran **Suivre** bascule en
**mode dégradé** : dernière position connue + liste, sans carte, avec un
message clair. Une coupure réseau n'est **jamais** présentée comme un
incident, et ne déclenche aucune alerte.

## 5. Suivi live (v0.2)

Pendant une course active, l'écran Suivre interroge le serveur toutes
les 10 secondes (`GET /rides/{id}/track`) et déplace le marqueur orange
du conducteur sur la carte. La position du conducteur est publiée par
`POST /rides/{id}/position`. Le marqueur reste sur la dernière position
connue si le réseau coupe : ce n'est pas un incident.

## 6. Coûts

Google Maps est facturé à l'usage (crédit gratuit mensuel de Google).
Aucun prix définitif n'est affirmé ici : vérifiez la grille en vigueur
dans Google Cloud Console au moment de l'activation, et surveillez la
consommation (alertes de facturation à activer dans le projet).
