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


def _entry_fondateurs(entry):
    aspects = entry.get("signification", {}).get("interne", [])
    if aspects:
        return aspects[0].get("fondateur1", ""), aspects[0].get("fondateur2", "")
    return "", ""


def _all_fondateur_pairs(entry):
    pairs = []
    for asp in entry.get("signification", {}).get("interne", []):
        f1, f2 = asp.get("fondateur1", ""), asp.get("fondateur2", "")
        if f1 or f2:
            if (f1, f2) not in pairs:
                pairs.append((f1, f2))
    return pairs


def main():
    with open(DICT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = {e["headword"]: e for e in data}
    headwords = set(entries.keys())

    primitifs = set()
    for e in data:
        pairs = _all_fondateur_pairs(e)
        if not pairs:
            primitifs.add(e["headword"])

    orphans = Counter()
    for e in data:
        for f1, f2 in _all_fondateur_pairs(e):
            for f in (f1, f2):
                if f and f not in headwords:
                    orphans[f] += 1

    def depth(hw, visited=None):
        if visited is None:
            visited = set()
        if hw in visited or hw not in entries:
            return 0
        visited.add(hw)
        e = entries[hw]
        f1, f2 = _entry_fondateurs(e)
        if not f1 and not f2:
            return 0
        d1 = depth(f1, visited.copy()) if f1 else 0
        d2 = depth(f2, visited.copy()) if f2 else 0
        return 1 + max(d1, d2)

    print(f"=== AUDIT DU GRAPHE TBS ===\n")
    print(f"Entrées totales :      {len(data)}")
    print(f"Primitifs (sans fondateurs) : {len(primitifs)}")
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
        f1, _ = _entry_fondateurs(e)
        if f1:
            depths[hw] = depth(hw)
    for d in sorted(set(depths.values())):
        words = [hw for hw, dd in depths.items() if dd == d]
        print(f"  Profondeur {d} : {len(words)} mots")
        if len(words) <= 10:
            print(f"    → {', '.join(sorted(words))}")

    print(f"\n=== À FAIRE ===")
    print(f"1. Marquer ~{min(10, len(orphans))} fondateurs fréquents comme PRIMITIFS")
    print(f"   (ajouter des entrées sans fondateurs)")
    print(f"   Candidats : ÊTRE, AVOIR, FAIRE, DIRE, SAVOIR, VOIR, AIMER")
    print(f"2. Décomposer les {len(orphans)} orphelins restants")
    print(f"   (les plus urgents : ceux à fréquence ≥ 3)")
    urgent = sum(1 for v in orphans.values() if v >= 3)
    print(f"   → {urgent} orphelins à fréquence ≥ 3")


if __name__ == "__main__":
    main()
