# Dictionnaire TBS

Dictionnaire basé sur la **Théorie des Blocs Sémantiques** (Carel & Ducrot).

---

## Structure du projet

```
dictionaryTBS/
│
├── data/                       ← Données
│   ├── dictionnaire.json       ← Entrées du dictionnaire
│   └── types_criteres.json     ← Types de critères
│
├── templates/                  ← Mise en forme
│   ├── template.html           ← Structure HTML
│   └── style.css               ← Styles CSS
│
├── scripts/                    ← Outils
│   ├── generate_html.py        ← Génère le site
│   └── merge_entry.py          ← Ajoute une entrée
│
├── output/                     ← Fichiers générés
│   └── dictionnaire_tbs.html   ← Site généré
│
└── README.md
```

---

## Utilisation

### Générer le dictionnaire HTML

```bash
python scripts/generate_html.py
```

→ Crée `output/dictionnaire_tbs.html`

### Ajouter une nouvelle entrée

1. Créer un fichier JSON (voir structure ci-dessous)
2. Exécuter :

```bash
python scripts/merge_entry.py chemin/vers/mot.json
```

→ Ajoute ou met à jour l'entrée dans `data/dictionnaire.json`

---

## Structure d'une entrée

```json
{
  "headword": "MOT",
  "letter": "M",
  "fondateur1": "AVOIR",
  "fondateur2": "DIRE",
  "signification": {
    "interne": [
      {
        "aspect": "X AVOIR *Y* DC X DIRE Y",
        "exemples": [
          {
            "phrase": "Les mots me manquent.",
            "ea": "Je voudrais dire, pourtant je n'ai pas de mots."
          }
        ]
      }
    ],
    "externe": [
      {
        "quasibloc": "X DIRE (Z FAIRE)",
        "exemples": [
          {
            "phrase": "Ce ne sont que des mots.",
            "ea": "Il a dit, pourtant il n'a pas fait."
          }
        ]
      }
    ]
  },
  "criteres": [
    {
      "type": 1,
      "texte": "« le mot juste » (ATT-X DC REAL-Y)"
    }
  ]
}
```

### Champs obligatoires

| Champ | Description |
|-------|-------------|
| `headword` | Mot-vedette (majuscules) |
| `letter` | Lettre initiale |
| `fondateur1` | Premier terme fondateur |
| `fondateur2` | Second terme fondateur |
| `signification.interne` | Liste d'aspects |
| `signification.externe` | Liste de quasi-blocs |

### Champs optionnels

| Champ | Description |
|-------|-------------|
| `criteres` | Liste de critères de validation |

---

## Types de critères

| ID | Nom | Description |
|----|-----|-------------|
| 1 | renforcement | ATT-X DC REAL-Y |
| 2 | atténuation | REAL-X DC ATT-Y |
| 3 | CAL | Carte argumentative du lexique |
| 4 | doxalité | Aspect normatif (DC) |
| 5 | transgressif | Aspect transgressif (PT) |
| 6 | gradualité | Critère HGDC |

---

## Code couleur

| Élément | Signification |
|---------|---------------|
| 🔵 Bleu | Aspect (signification interne) |
| 🟤 Ocre | Quasi-bloc (signification externe) |
| ⚫ Gris | Critère |
| 🟡 Or | Bloc sémantique |

---

## Personnalisation

| Fichier | Rôle |
|---------|------|
| `templates/style.css` | Couleurs, typographie, mise en page |
| `templates/template.html` | Structure HTML |
| `data/types_criteres.json` | Ajouter des types de critères |

---

## Référence

Carel, M. & Ducrot, O. — *Théorie des Blocs Sémantiques*
