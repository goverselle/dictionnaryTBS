#!/usr/bin/env python3
"""
Merge un ou plusieurs items JSON dans le dictionnaire TBS.

Usage:
    python merge_entry.py <dictionnaire.json> <nouvelles_entrees.json>

Le fichier d'entrées peut contenir :
- Un objet JSON unique (une entrée)
- Un tableau JSON (plusieurs entrées)

Si un mot existe déjà (même headword), il est mis à jour.
Sinon, il est ajouté.
"""

import json
import sys
from pathlib import Path


def load_json(path):
    """Charge un fichier JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """Sauvegarde un fichier JSON (trié par headword)."""
    sorted_data = sorted(data, key=lambda e: e["headword"].lower())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=2)


def validate_entry(entry):
    """Vérifie que l'entrée a les champs requis."""
    required = ["headword", "letter", "fondateur1", "fondateur2", "signification"]
    for field in required:
        if field not in entry:
            return False, f"champ manquant : {field}"
    if "interne" not in entry["signification"]:
        return False, "signification.interne manquant"
    if "externe" not in entry["signification"]:
        return False, "signification.externe manquant"
    return True, None


def main():
    if len(sys.argv) < 3:
        print("Usage: python merge_entry.py <dictionnaire.json> <nouvelles_entrees.json>")
        print()
        print("Exemple:")
        print("  python merge_entry.py data/dictionnaire.json nouvelles_entrees.json")
        sys.exit(1)
    
    dict_path = Path(sys.argv[1])
    entries_path = Path(sys.argv[2])
    
    if not dict_path.exists():
        print(f"Erreur : {dict_path} n'existe pas.")
        sys.exit(1)
    
    if not entries_path.exists():
        print(f"Erreur : {entries_path} n'existe pas.")
        sys.exit(1)
    
    # Charger
    dictionnaire = load_json(dict_path)
    new_data = load_json(entries_path)
    
    # Normaliser en liste
    if isinstance(new_data, dict):
        new_data = [new_data]
    
    print(f"Dictionnaire : {len(dictionnaire)} entrées")
    print(f"À intégrer : {len(new_data)} entrée(s)")
    print()
    
    # Index des headwords existants
    index = {e["headword"].upper(): i for i, e in enumerate(dictionnaire)}
    
    added = 0
    updated = 0
    errors = 0
    
    for entry in new_data:
        hw = entry.get("headword", "???").upper()
        entry["headword"] = hw
        
        valid, err = validate_entry(entry)
        if not valid:
            print(f"  ✗ {hw} : {err}")
            errors += 1
            continue
        
        if hw in index:
            dictionnaire[index[hw]] = entry
            print(f"  ↻ {hw} mis à jour")
            updated += 1
        else:
            dictionnaire.append(entry)
            index[hw] = len(dictionnaire) - 1
            print(f"  + {hw} ajouté")
            added += 1
    
    print()
    
    if added > 0 or updated > 0:
        save_json(dict_path, dictionnaire)
        print(f"Sauvegardé : {dict_path}")
        print(f"Résumé : {added} ajouté(s), {updated} mis à jour, {errors} erreur(s)")
        print(f"Total : {len(dictionnaire)} entrées")
    else:
        print("Aucune modification.")


if __name__ == "__main__":
    main()