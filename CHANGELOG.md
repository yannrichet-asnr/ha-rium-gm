# Changelog

## 0.3.0

- Publication optionnelle des mesures sur OpenRadiation (submit.openradiation.net) :
  agrégation sur une période ≥ 10 min, mode test par défaut, validation de la clé API
  à l'enregistrement des options, file de réémission bornée, capteur « dernier envoi ».
- Température exposée comme capteur standard (plus en diagnostic).
- Licence BSD 3-Clause.
- CI GitHub Actions : tests, hassfest, validation HACS ; publication des releases sur tag.

## 0.2.0

- Première version : lecture USB série du RiumGM (VID 03EB / PID 2404), trames v1
  (binaire) et v2 (ASCII) d'après OpenRadiation, découverte USB, capteurs débit de dose,
  taux de comptage, coups cumulés, température, batterie et connectivité.
