# DESIGN SYSTEM — MOTOSEC 237 v0.1

**Combiné vert émeraude + bleu ciel** (décision utilisateur, 2026-11-10).
Style applis Google : épuré, cartes très arrondies (16), beaucoup d'espace,
typographie système, pas de fond flouté, ne ressemble pas à PI Gestion
(ni noir/orange).

## Palette complète

| Nom | Hex | Usage |
|---|---|---|
| Vert profond | `#102B26` | Texte sur émeraude/bleu ciel, fonds sombres |
| Vert émeraude | `#39C99A` | Marque, logo, boutons principaux, succès, navigation active |
| Blanc cassé | `#F5F7F5` | Fond d'écrans |
| Graphite | `#202A29` | Texte principal |
| Or doux | `#E6B85C` | Accent ponctuel (filets, badges), jamais en fond dominant |
| Rouge alerte | `#D94B4B` | Urgences et incidents UNIQUEMENT (SOS) |
| Bleu ciel | `#38BDF8` | Deuxième couleur : carte, suivi, boutons secondaires, « en cours » |
| Bleu ciel clair | `#E0F2FE` | Fonds de cartes de suivi, indicateurs de navigation |
| Bleu ciel foncé | `#0284C7` | Textes et accents importants sur fond clair, bordures focus |

## Règles d'usage

- **Vert** : boutons principaux (« Commander », « Continuer »), succès,
  marque, navigation active.
- **Bleu ciel** : fonds de carte Google Maps, écrans de suivi / trajet,
  boutons secondaires, liens, états « en cours ».
- **Rouge** : SOS et incidents seulement.
- **Or** : accent ponctuel seulement.

## Contraste (vérifié)

Le blanc sur vert émeraude `#39C99A` est trop faible (~2,1:1) : les
boutons émeraude portent un texte **vert profond** `#102B26` (~7:1).
Même règle sur bleu ciel `#38BDF8`. Le blanc est réservé aux textes sur
vert profond, graphite et bleu ciel foncé. Le gris `#64748B` est réservé
aux textes secondaires, jamais aux textes principaux.

## Composants (voir `app/lib/theme.dart`, `app/lib/widgets.dart`)

- Cartes blanches, rayon 16, bordure fine `#E2E8F0`, ombre nulle.
- Champs : fond blanc, rayon 12, bordure focus bleu ciel foncé 2 px.
- Boutons principaux : émeraude, hauteur 48, rayon 12, texte vert profond gras.
- Boutons secondaires : contour bleu ciel foncé, texte bleu ciel foncé.
- Navigation basse : fond blanc, indicateur bleu ciel clair.
- Bouton SOS : rouge, flottant, toujours visible sur l'écran de suivi.

## Exemples d'écrans

- **Accueil** : logo, slogan, carte d'état du serveur (vert si en ligne,
  bleu si démo locale), carte « Commander », carte « Colis (Bientôt) ».
- **Commander** : carte Google Maps en haut (marqueurs vert/bleu),
  panneau bleu ciel clair en bas avec distance, tarif, bouton vert.
- **Suivre** : carte Google Maps plein écran ; hors ligne, panneau bleu
  clair « pas de réseau » + dernière position connue.
- **Profil** : liste, sélecteur de langue FR/EN, paiements « Bientôt ».

## Logo

Le logo choisi (M-route vert émeraude, petite moto) n'est **pas recoloré** :
`app/assets/icon/app_icon.png` (converti du WebP choisi). Le bleu ciel ne
s'applique pas au logo.
