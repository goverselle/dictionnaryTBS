#!/usr/bin/env python3
"""
Audit du graphe TBS : identifie les fondateurs orphelins,
les cycles, et la profondeur de décomposition.

Usage : python3 scripts/audit_graph.py
"""

import json
from pathlib import Path
from collections import Counter

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"

def main():
    with open(DICT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = {e["headword"]: e for e in data}
    headwords = set(entries.keys())

    # Primitifs = entrées dont fondateur1 et fondateur2 sont vides
    primitifs = set()
    for e in data:
        f1 = e.get("fondateur1", "").strip()
        f2 = e.get("fondateur2", "").strip()
        if not f1 and not f2:
            primitifs.add(e["headword"])

    # Orphelins = fondateurs pas dans le dictionnaire
    orphans = Counter()
    for e in data:
        for f in ("fondateur1", "fondateur2"):
            v = e.get(f, "").strip()
            if v and v not in headwords:
                orphans[v] += 1

    # Profondeur : combien de niveaux de décomposition avant un primitif ou orphelin ?
    def depth(hw, visited=None):
        if visited is None:
            visited = set()
        if hw in visited or hw not in entries:
            return 0
        visited.add(hw)
        e = entries[hw]
        f1 = e.get("fondateur1", "").strip()
        f2 = e.get("fondateur2", "").strip()
        if not f1 and not f2:
            return 0  # primitif
        d1 = depth(f1, visited.copy()) if f1 else 0
        d2 = depth(f2, visited.copy()) if f2 else 0
        return 1 + max(d1, d2)

    print(f"=== AUDIT DU GRAPHE TBS ===\n")
    print(f"Entrées totales :      {len(data)}")
    print(f"Primitifs (f1=f2='') : {len(primitifs)}")
    if primitifs:
        print(f"  → {', '.join(sorted(primitifs))}")
    print(f"Orphelins :            {len(orphans)}")
    print(f"\nTop 20 orphelins :")
    for t, c in orphans.most_common(20):
        print(f"  {c:2d}×  {t}")

    print(f"\nProfondeur de décomposition (entrées avec AI) :")
    depths = {}
    for hw in headwords:
        e = entries[hw]
        if e.get("fondateur1", "").strip():
            depths[hw] = depth(hw)
    for d in sorted(set(depths.values())):
        words = [hw for hw, dd in depths.items() if dd == d]
        print(f"  Profondeur {d} : {len(words)} mots")
        if len(words) <= 10:
            print(f"    → {', '.join(sorted(words))}")

    # Suggestions
    print(f"\n=== À FAIRE ===")
    print(f"1. Marquer ~{min(10, len(orphans))} fondateurs fréquents comme PRIMITIFS")
    print(f"   (ajouter des entrées avec fondateur1=fondateur2='' )")
    print(f"   Candidats : ÊTRE, AVOIR, FAIRE, DIRE, SAVOIR, VOIR, AIMER")
    print(f"2. Décomposer les {len(orphans)} orphelins restants")
    print(f"   (les plus urgents : ceux à fréquence ≥ 3)")
    urgent = sum(1 for v in orphans.values() if v >= 3)
    print(f"   → {urgent} orphelins à fréquence ≥ 3")


if __name__ == "__main__":
    main()
