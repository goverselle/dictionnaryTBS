# Dictionnaire TBS

Dictionnaire basé sur la **Théorie des Blocs Sémantiques** (Carel & Ducrot).

**Consultable en ligne : https://goverselle.github.io/dictionnaryTBS/**

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
├── docs/                       ← GitHub Pages (auto-généré)
│   ├── index.html
│   ├── style.css
│   └── tbs_free_network_v2.html
│
└── README.md
```

---

## Déploiement

Le site est hébergé sur **GitHub Pages** et servi depuis le dossier `docs/`.

Après toute modification du dictionnaire :

```bash
python scripts/generate_html.py   # régénère output/ et docs/
git add -A
git commit -m "mise à jour"
git push origin main              # le site se met à jour automatiquement
```

---

## Utilisation

### Générer le dictionnaire HTML

```bash
python scripts/generate_html.py
```

→ Crée `output/dictionnaire_tbs.html` et met à jour `docs/` pour GitHub Pages.

### Ajouter une nouvelle entrée

1. Créer un fichier JSON (voir structure ci-dessous)
2. Exécuter :

```bash
python scripts/merge_entry.py chemin/vers/mot.json
```

→ Ajoute ou met à jour l'entrée dans `data/dictionnaire.json`

---

## Structure d'une entrée

Les fondateurs et critères sont rattachés à chaque aspect interne individuellement.

```json
{
  "headword": "MOT",
  "letter": "M",
  "template_syntaxique": "X DIRE Y",
  "signification": {
    "interne": [
      {
        "aspect": "X AVOIR *Y* DC X DIRE Y",
        "fondateur1": "AVOIR",
        "fondateur2": "DIRE",
        "criteres": [
          {
            "type": 1,
            "texte": "« le mot juste » (ATT-X DC REAL-Y)"
          }
        ],
        "square_value": null,
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
  }
}
```

### Champs obligatoires

| Champ | Description |
|-------|-------------|
| `headword` | Mot-vedette (majuscules) |
| `letter` | Lettre initiale (sans accent) |
| `signification.interne` | Liste d'aspects |
| `signification.externe` | Liste de quasi-blocs |

### Champs par aspect interne

| Champ | Description |
|-------|-------------|
| `fondateur1` | Premier terme fondateur |
| `fondateur2` | Second terme fondateur |
| `criteres` | Liste de critères de validation |
| `square_value` | Position dans le carré argumentatif (1-4) |

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

## Référence

Carel, M. & Ducrot, O. — *Théorie des Blocs Sémantiques*
