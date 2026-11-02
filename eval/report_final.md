# Rapport d'évaluation

Contrat: `mutuelle.pdf` · série `final` · k=6 · **18/50 questions évaluées** · ordre aléatoire (graine 0) · arrêt: quota du fournisseur atteint (429), même après attente

- **Récupération (hit@6)**: 12/18 (67%) des questions dont tous les articles attendus sont retrouvés
- **Verdict correct**: 11/18 (61%)
- **Erreurs assurées** (verdict ferme faux, le pire cas): 0/8 (0%) des verdicts fermes
- **Abstentions inutiles** (ambigu alors que le contrat tranche): 7/18 (39%)
- **Ambiguïtés bien détectées**: 3/3 (100%)
- **Verdicts fermes citant un bon article**: 7/8 (88%)
- **Garde-fous déclenchés**: 4

## Détail

| id | attendu | obtenu | citations | garde-fou | hit |
|---|---|---|---|---|---|
| 1 | non_couvert | ambigu | - | - | False |
| 2 | non_couvert | ambigu | - | citation_non_verifiee | True |
| 6 | non_couvert | non_couvert | Article 7 | - | True |
| 8 | non_couvert | ambigu | - | citation_non_verifiee | True |
| 12 | ambigu | ambigu | - | - | True |
| 13 | non_couvert | non_couvert | Article 7 | - | True |
| 15 | couvert | couvert | Article 7 | - | False |
| 21 | non_couvert | ambigu | - | citation_non_verifiee | True |
| 24 | ambigu | ambigu | Article 49 | - | True |
| 28 | couvert | couvert | Article 4 | - | True |
| 29 | couvert | ambigu | - | - | False |
| 34 | non_couvert | non_couvert | Article 8 | - | True |
| 35 | ambigu | ambigu | - | - | False |
| 37 | couvert | couvert | Article 9 | - | True |
| 39 | non_couvert | non_couvert | Article 9 | - | True |
| 44 | couvert | ambigu | - | - | False |
| 48 | non_couvert | non_couvert | Article 4 | - | False |
| 50 | couvert | ambigu | - | citation_non_verifiee | True |