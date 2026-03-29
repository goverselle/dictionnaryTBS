#!/usr/bin/env python3
"""
Merge un item JSON dans le dictionnaire TBS.

Usage:
    python merge_entry.py nouveau_mot.json
    python merge_entry.py https://url/vers/mot.json

Si le mot existe déjà (même headword), il est mis à jour.
Sinon, il est ajouté.
"""

import json
import sys
import urllib.request
from pathlib import Path

# Chemins
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
DICTIONNAIRE_PATH = DATA_DIR / "dictionnaire.json"


def load_dictionnaire():
    """Charge le dictionnaire existant."""
    if not DICTIONNAIRE_PATH.exists():
        print(f"Erreur : {DICTIONNAIRE_PATH} n'existe pas.")
        sys.exit(1)
    
    with open(DICTIONNAIRE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_dictionnaire(entries):
    """Sauvegarde le dictionnaire (trié par headword)."""
    sorted_entries = sorted(entries, key=lambda e: e["headword"].lower())
    
    with open(DICTIONNAIRE_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted_entries, f, ensure_ascii=False, indent=2)
    
    print(f"Dictionnaire sauvegardé : {DICTIONNAIRE_PATH}")


def load_new_entry(source):
    """Charge un nouvel item depuis un fichier local ou une URL."""
    if source.startswith("http://") or source.startswith("https://"):
        print(f"Téléchargement depuis : {source}")
        try:
            with urllib.request.urlopen(source) as response:
                data = response.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            print(f"Erreur de téléchargement : {e}")
            sys.exit(1)
    else:
        path = Path(source)
        if not path.exists():
            print(f"Erreur : {source} n'existe pas.")
            sys.exit(1)
        
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def validate_entry(entry):
    """Vérifie que l'entrée a les champs requis."""
    required_fields = ["headword", "letter", "fondateur1", "fondateur2", "signification"]
    
    for field in required_fields:
        if field not in entry:
            print(f"Erreur : champ requis manquant : {field}")
            return False
    
    if "interne" not in entry["signification"]:
        print("Erreur : signification.interne manquant")
        return False
    
    if "externe" not in entry["signification"]:
        print("Erreur : signification.externe manquant")
        return False
    
    return True


def merge_entry(entries, new_entry):
    """Merge l'entrée dans le dictionnaire."""
    headword = new_entry["headword"].upper()
    new_entry["headword"] = headword
    
    for i, entry in enumerate(entries):
        if entry["headword"].upper() == headword:
            print(f"Mise à jour de : {headword}")
            entries[i] = new_entry
            return entries, "updated"
    
    print(f"Ajout de : {headword}")
    entries.append(new_entry)
    return entries, "added"


def main():
    if len(sys.argv) < 2:
        print("Usage: python merge_entry.py <fichier.json ou URL>")
        print()
        print("Exemples:")
        print("  python merge_entry.py silence.json")
        print("  python merge_entry.py https://example.com/mot.json")
        sys.exit(1)
    
    source = sys.argv[1]
    
    entries = load_dictionnaire()
    print(f"Dictionnaire chargé : {len(entries)} entrées")
    
    new_entry = load_new_entry(source)
    
    if not validate_entry(new_entry):
        sys.exit(1)
    
    entries, action = merge_entry(entries, new_entry)
    
    save_dictionnaire(entries)
    
    if action == "updated":
        print(f"✓ {new_entry['headword']} mis à jour.")
    else:
        print(f"✓ {new_entry['headword']} ajouté. Total : {len(entries)} entrées.")


if __name__ == "__main__":
    main()
