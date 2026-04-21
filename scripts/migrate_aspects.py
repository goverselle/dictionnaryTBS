#!/usr/bin/env python3
"""
Migration : déplace fondateur1, fondateur2, criteres, square_value
du niveau entrée vers chaque aspect interne.

Usage :
    python3 scripts/migrate_aspects.py          # dry-run
    python3 scripts/migrate_aspects.py --apply  # écriture effective
"""

import json
import re
import sys
from pathlib import Path

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"
BACKUP_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.pre-migration.json"

OVERRIDES = {
    "RESPONSABLE": [
        {"fondateur1": "DEVOIR FAIRE", "fondateur2": "FAIRE"},
        {"fondateur1": "ÊTRE FAUTE", "fondateur2": "DEVOIR RÉPONDRE"},
    ],
    "TEMPS": [
        {"fondateur1": "AVOIR", "fondateur2": "POUVOIR FAIRE"},
        {"fondateur1": "PASSER", "fondateur2": "DONNER"},
        {"fondateur1": "PASSER", "fondateur2": "PRENDRE"},
        {"fondateur1": "PASSER", "fondateur2": "REVENIR"},
        {"fondateur1": "PASSER", "fondateur2": "CHANGER"},
        {"fondateur1": "AVOIR", "fondateur2": "DEVOIR FAIRE"},
    ],
}


def migrate(entries):
    warnings = []
    for entry in entries:
        hw = entry["headword"]
        f1 = entry.get("fondateur1", "")
        f2 = entry.get("fondateur2", "")
        criteres = entry.get("criteres", [])
        square_value = entry.get("square_value")
        aspects = entry.get("signification", {}).get("interne", [])

        if hw in OVERRIDES:
            overrides = OVERRIDES[hw]
            for i, asp in enumerate(aspects):
                if i < len(overrides):
                    asp["fondateur1"] = overrides[i]["fondateur1"]
                    asp["fondateur2"] = overrides[i]["fondateur2"]
                else:
                    asp["fondateur1"] = ""
                    asp["fondateur2"] = ""
                    warnings.append(f"{hw}: aspect {i+1} sans override")
                if i == 0:
                    asp["criteres"] = criteres
                    asp["square_value"] = square_value
                else:
                    asp.setdefault("criteres", [])
                    asp.setdefault("square_value", None)
        elif len(aspects) <= 1:
            for asp in aspects:
                asp["fondateur1"] = f1
                asp["fondateur2"] = f2
                asp["criteres"] = criteres
                asp["square_value"] = square_value
        else:
            for i, asp in enumerate(aspects):
                if i == 0:
                    asp["fondateur1"] = f1
                    asp["fondateur2"] = f2
                    asp["criteres"] = criteres
                    asp["square_value"] = square_value
                else:
                    asp["fondateur1"] = f1
                    asp["fondateur2"] = f2
                    asp["criteres"] = []
                    asp["square_value"] = None
            warnings.append(f"{hw}: {len(aspects)} aspects, mêmes fondateurs copiés partout")

        for key in ("fondateur1", "fondateur2", "criteres", "square_value"):
            entry.pop(key, None)

    return entries, warnings


def main():
    apply = "--apply" in sys.argv

    with open(DICT_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)

    already = any(
        "fondateur1" in asp
        for e in entries
        for asp in e.get("signification", {}).get("interne", [])
    )
    if already:
        print("Migration déjà effectuée (fondateur1 trouvé dans un aspect).")
        return

    print(f"Entrées à migrer : {len(entries)}")
    entries, warnings = migrate(entries)

    if warnings:
        print("\nAvertissements :")
        for w in warnings:
            print(f"  ! {w}")

    if apply:
        BACKUP_PATH.write_text(
            Path(DICT_PATH).read_text(encoding="utf-8"), encoding="utf-8"
        )
        with open(DICT_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Backup : {BACKUP_PATH}")
        print(f"✓ Migré : {DICT_PATH}")
    else:
        sample = next(
            (e for e in entries if e["headword"] == "AMÉLIORER"), entries[0]
        )
        print("\nExemple (AMÉLIORER) :")
        print(json.dumps(sample, ensure_ascii=False, indent=2))
        print("\n(dry-run — ajouter --apply pour écrire)")


if __name__ == "__main__":
    main()
