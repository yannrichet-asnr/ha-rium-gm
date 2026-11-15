# Rium GM (USB) pour Home Assistant

Intégration `custom_components/rium_gm` pour le compteur Geiger RiumGM (Icohup)
branché en USB sur la machine Home Assistant.

## Protocole (repris de l'application OpenRadiation, non garanti par le fabricant)
- USB CDC série, VID `03EB` / PID `2404`, 115200 bauds 8N1.
- v1 : trame binaire 12 octets toutes les ~2 s : `C1 00 | id u32 | coups u16 | délai u16 (1/10 s) | temp i16 (1/10 °C)` (big-endian).
- v2 : trame ASCII 32 octets toutes les ~1 s : `?,id,?,coups,temp×10,batterie×100,...`.
- Conversion : `µSv/h = (3,751e-8·(cpm−4)² + 0,00965·(cpm−4))·0,85` (étalonnage « groundLevel » d'OpenRadiation, tube J305).

## Entités
Débit de dose (μSv/h), taux de comptage (cps), coups cumulés, température, batterie (v2), connectivité.
Options : fenêtre glissante de calcul du taux (défaut 120 s), période de publication (défaut 10 s).

## Installation
1. Vérifier le flux hors HA : `pip install pyserial && python3 tools/rium_dump.py /dev/ttyACM0 --seconds 60`.
2. Copier `custom_components/rium_gm` dans `<config>/custom_components/`, redémarrer.
3. Paramètres → Appareils et services : le Rium est proposé automatiquement (découverte USB), sinon « Ajouter une intégration » → Rium GM.
4. HA en conteneur Docker : passer le périphérique (`--device /dev/serial/by-id/...`).

## Tests
`pip install pytest-homeassistant-custom-component && pytest tests`
