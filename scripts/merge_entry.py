#!/usr/bin/env python3
"""
Merge un ou plusieurs items JSON dans le dictionnaire TBS.

Usage:
    python merge_entry.py                                          # défauts
    python merge_entry.py <dictionnaire.json> <nouvelles_entrees.json>

Sans argument, utilise :
    ../data/dictionnaire.json
    ../data/example_ajouter.json
(résolus par rapport à l'emplacement du script).

Le fichier d'entrées peut contenir :
- Un objet JSON unique (une entrée)
- Un tableau JSON (plusieurs entrées)

Si un mot existe déjà (même headword), il est mis à jour.
Sinon, il est ajouté.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat import parse_aspect, extract_predicates, ROLE_VARS  # noqa: E402
from extract_quasiblocs import (                                # noqa: E402
    build_quasibloc, collect_predicates, normalize_qb_key,
    create_stub,
)


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
    required = ["headword", "letter", "signification"]
    for field in required:
        if field not in entry:
            return False, f"champ manquant : {field}"
    if "interne" not in entry["signification"]:
        return False, "signification.interne manquant"
    if "externe" not in entry["signification"]:
        return False, "signification.externe manquant"
    return True, None


DEFAULT_DICT = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"
DEFAULT_ENTRIES = Path(__file__).resolve().parent.parent / "data" / "example_ajouter.json"


def _extract_quasiblocs(dictionnaire, new_entries):
    """Pour chaque entrée ajoutée/mise à jour, extrait les quasi-blocs
    de ses aspects internes et les dispatche dans les ``externe`` des
    mots cités. Crée un stub si le mot cité n'existe pas encore.

    Retourne le nombre de quasi-blocs effectivement ajoutés."""
    by_hw = {e["headword"]: e for e in dictionnaire}

    # Clés de dédup : qb déjà présents dans chaque entrée.
    existing = {}
    for hw, entry in by_hw.items():
        ext = entry.get("signification", {}).get("externe", []) or []
        existing[hw] = {normalize_qb_key(item.get("quasibloc", "")) for item in ext}

    qb_count = 0
    for entry in new_entries:
        hw = entry.get("headword", "").upper()
        asp_list = entry.get("signification", {}).get("interne", []) or []
        for item in asp_list:
            raw = item.get("aspect", "")
            parsed = parse_aspect(raw)
            if not parsed:
                continue
            qb = build_quasibloc(parsed, raw)
            exemples = item.get("exemples", []) or []
            preds = collect_predicates(parsed)
            for p in preds:
                if p not in by_hw:
                    stub = create_stub(p)
                    by_hw[p] = stub
                    dictionnaire.append(stub)
                    existing[p] = set()
                    print(f"  + {p} (stub créé pour quasi-bloc)")
                k = normalize_qb_key(qb)
                if k in existing[p]:
                    continue
                existing[p].add(k)
                qb_item = {"quasibloc": qb, "exemples": exemples}
                by_hw[p]["signification"].setdefault("externe", []).append(qb_item)
                qb_count += 1
    return qb_count


def main():
    if len(sys.argv) == 1:
        dict_path = DEFAULT_DICT
        entries_path = DEFAULT_ENTRIES
    elif len(sys.argv) == 3:
        dict_path = Path(sys.argv[1])
        entries_path = Path(sys.argv[2])
    else:
        print("Usage: python merge_entry.py [<dictionnaire.json> <nouvelles_entrees.json>]")
        print()
        print("Sans argument, utilise les défauts :")
        print(f"  {DEFAULT_DICT}")
        print(f"  {DEFAULT_ENTRIES}")
        sys.exit(1)
    
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
        letter = entry.get("letter", "")
        entry["letter"] = ''.join(
            c for c in unicodedata.normalize('NFD', letter)
            if unicodedata.category(c) != 'Mn'
        )
        
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
        # Extraction automatique des quasi-blocs pour les entrées touchées.
        qb_added = _extract_quasiblocs(dictionnaire, new_data)
        save_json(dict_path, dictionnaire)
        print(f"Sauvegardé : {dict_path}")
        print(f"Résumé : {added} ajouté(s), {updated} mis à jour, {errors} erreur(s), {qb_added} qb dispatché(s)")
        print(f"Total : {len(dictionnaire)} entrées")
    else:
        print("Aucune modification.")


if __name__ == "__main__":
    main()