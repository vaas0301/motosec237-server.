# LIVRAISON v0.1.1 — Réparation Android (2026-11-10, soir)

Correctif de la v0.1, même code Dart, même serveur, même base de données.
Seul le dossier Android change.

## Pourquoi une v0.1.1

La v0.1 livrée à 13:13 contenait une appli Flutter dont le dossier
`app/android/` était incomplet : pas de `MainActivity`, pas de
`settings.gradle`, pas de `gradle-wrapper`. Conséquence : `flutter run`
et `flutter build apk` échouaient immédiatement (« deleted Android v1
embedding »). Le code Dart, lui, était bon (`flutter analyze` sans
erreur, 12 tests sur 12).

## Ce qui a été réparé

- `app/android/` régénéré avec `flutter create` puis adapté à MOTOSEC :
  `MainActivity` en `com.motosec237.app`, `settings.gradle.kts`,
  `gradle-wrapper`, manifestes, ressources de lancement.
- Versions alignées sur le modèle Flutter : Gradle 8.14, AGP 8.11.1,
  Kotlin 2.4.0, `compileSdk` / `targetSdk` 34, `applicationId`
  `com.motosec237.app`.
- Clé Google Maps toujours par `app/android/local.properties`
  (`MAPS_API_KEY=...`, jamais dans le code, voir `docs/GOOGLE-MAPS.md`).
- `app/android/local.properties` n'est PAS dans le zip : Flutter le
  recrée sur la machine de l'utilisateur avec ses propres chemins SDK.

## Vérifié ici (2026-11-10)

- `flutter pub get` : OK.
- `flutter analyze` : aucun problème.
- `flutter test` : 12/12 réussis.
- `flutter build apk` : **non construit ici**. La construction a bloqué
  sur cette machine uniquement (versions Gradle/Kotlin et accès réseau
  via proxy propres à la VM, dernière erreur : conflit de variantes
  `kotlin-gradle-plugin-api:2.0.21` sous Gradle 8.14). Ce n'est pas un
  problème du code : sur un PC avec internet normal, Gradle télécharge
  ce qu'il faut. L'utilisateur lance `flutter run` sur son PC.

## Lancer sur son PC (VS Code, comme PI Gestion)

```bat
cd app
flutter pub get
flutter run
```

Sans serveur en ligne : mode démo locale (affiché sur l'accueil).
Avec serveur en ligne :
`flutter run --dart-define=MOTOSEC_BASE_URL=https://ton-serveur`
(voir `docs/DEPLOIEMENT-EN-LIGNE.md` et `docs/GOOGLE-MAPS.md`).

Premier lancement : choix de langue FR / EN, puis 4 onglets
Accueil / Commander / Suivre / Profil.
