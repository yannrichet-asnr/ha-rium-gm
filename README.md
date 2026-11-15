# Rium GM (USB) pour Home Assistant

[![CI](https://github.com/yannrichet-asnr/ha-rium-gm/actions/workflows/ci.yml/badge.svg)](https://github.com/yannrichet-asnr/ha-rium-gm/actions/workflows/ci.yml)

Intégration `custom_components/rium_gm` pour le compteur Geiger RiumGM (Icohup)
branché en USB sur la machine Home Assistant, avec publication optionnelle des
mesures sur [OpenRadiation](https://www.openradiation.org).

## Protocole (repris de l'application OpenRadiation, non garanti par le fabricant)
- USB CDC série, VID `03EB` / PID `2404`, 115200 bauds 8N1.
- v1 : trame binaire 12 octets toutes les ~2 s : `C1 00 | id u32 | coups u16 | délai u16 (1/10 s) | temp i16 (1/10 °C)` (big-endian).
- v2 : trame ASCII 32 octets toutes les ~1 s : `?,id,?,coups,temp×10,batterie×100,...`.
- Conversion : `µSv/h = (3,751e-8·(cpm−4)² + 0,00965·(cpm−4))·0,85` (étalonnage « groundLevel » d'OpenRadiation, tube J305).

## Entités
Débit de dose (μSv/h), taux de comptage (cps), coups cumulés, température,
batterie (v2), connectivité ; « OpenRadiation dernier envoi » si la publication est active.

## Installation
1. HACS → ⋮ → Dépôts personnalisés → `https://github.com/yannrichet-asnr/ha-rium-gm` (catégorie Intégration) → Télécharger, redémarrer.
2. Brancher le Rium : découverte USB automatique dans Paramètres → Appareils et services
   (sinon « Ajouter une intégration » → Rium GM).
3. HA en conteneur Docker : passer le périphérique (`--device /dev/serial/by-id/...`).

Diagnostic : `logger: logs: custom_components.rium_gm: debug` affiche les trames brutes.
Hors HA : `pip install pyserial && python3 tools/rium_dump.py /dev/ttyACM0 --seconds 60`.

## Publication OpenRadiation (optionnelle, désactivée par défaut)
Options de l'intégration → section « Publication OpenRadiation » :
- clé API à demander à dev@openradiation.net ;
- coordonnées (par défaut : domicile HA arrondi à 3 décimales, ~100 m) — **publiées sur une carte publique** ;
- environnement (intérieur, ville, campagne, route), hauteur, période d'agrégation (défaut 900 s, minimum 600 s) ;
- identifiant/mot de passe openradiation.org facultatifs (mot de passe stocké en clair dans `.storage/core.config_entries`, contrainte de l'API) ;
- mode production désactivé par défaut : `reportContext=test`, données acceptées mais non enregistrées.

À l'enregistrement, une mesure fictive est envoyée en mode test pour valider la clé.
Les envois échoués (réseau, 5xx) sont conservés en mémoire (96 au plus) et réémis à la période suivante ;
les rejets définitifs (4xx) sont abandonnés et signalés dans l'attribut `last_error`.

## Tests
`pip install -r requirements_test.txt && pytest tests`

## Licence
BSD 3-Clause, voir [LICENSE](LICENSE).
