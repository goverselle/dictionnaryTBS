#!/usr/bin/env python3
"""
TBS Engine — Moteur sémantique argumentatif.

Prototype de compréhension et génération basé sur le graphe TBS.

Usage interactif :
    python3 scripts/tbs_engine.py

Usage comme module :
    from tbs_engine import TBSEngine
    engine = TBSEngine()
    engine.analyser("prudent")
    engine.paraphraser("prudent")
    engine.comparer("prudent", "courageux")
"""

import json
import re
from pathlib import Path

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"


class TBSEngine:
    def __init__(self, path=DICT_PATH):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.entries = {e["headword"]: e for e in data}
        self._build_indices()

    def _build_indices(self):
        """Construit les index pour la recherche inverse."""
        # Index fondateur → mots qui l'utilisent
        self.fondateur_to_words = {}
        for hw, e in self.entries.items():
            for f in (e.get("fondateur1", ""), e.get("fondateur2", "")):
                f = f.strip()
                if f:
                    self.fondateur_to_words.setdefault(f, []).append(hw)

        # Index connecteur → mots
        self.dc_words = []
        self.pt_words = []
        self.paradoxaux = []
        for hw, e in self.entries.items():
            aspects = self._get_aspects(e)
            has_dc = any(re.search(r"\bDC\b", a) for a in aspects)
            has_pt = any(re.search(r"\bPT\b", a) for a in aspects)
            if has_dc:
                self.dc_words.append(hw)
            if has_pt:
                self.pt_words.append(hw)
            if e.get("paradoxal"):
                self.paradoxaux.append(hw)

    def _get_aspects(self, entry):
        """Retourne toutes les formules d'aspects d'une entrée."""
        aspects = []
        for item in entry.get("signification", {}).get("interne", []):
            aspects.append(item.get("aspect", ""))
        for item in entry.get("signification", {}).get("externe", []):
            aspects.append(item.get("quasibloc", ""))
        return aspects

    # ==================== COMPRENDRE ====================

    def analyser(self, mot):
        """Analyse un mot : retourne sa structure TBS."""
        mot = mot.upper()
        e = self.entries.get(mot)
        if not e:
            return f"'{mot}' non trouvé dans le dictionnaire."

        lines = [f"\n  ══ {mot} ══\n"]
        lines.append(f"  Fondateurs : {e.get('fondateur1', '?')} — {e.get('fondateur2', '?')}")

        # Type
        is_paradoxal = e.get("paradoxal", False)
        aspects = self._get_aspects(e)
        has_dc = any(re.search(r"\bDC\b", a) for a in aspects)
        has_pt = any(re.search(r"\bPT\b", a) for a in aspects)

        types = []
        if is_paradoxal:
            types.append("paradoxal")
        if has_dc:
            types.append("normatif (DC)")
        if has_pt:
            types.append("transgressif (PT)")
        lines.append(f"  Type : {', '.join(types) if types else '?'}")

        # Paradoxe complet/incomplet
        if has_dc and has_pt:
            lines.append(f"  → Paradoxe COMPLET (DC et PT formulables)")
        elif has_pt and not has_dc:
            lines.append(f"  → Paradoxe INCOMPLET (PT seul, DC bloqué)")
        elif has_dc and not has_pt:
            lines.append(f"  → Normatif pur (DC seul)")

        # Aspects
        for item in e.get("signification", {}).get("interne", []):
            lines.append(f"\n  AI : {item['aspect']}")
            for ex in item.get("exemples", []):
                lines.append(f"      « {ex['phrase']} »")
                lines.append(f"        → {ex['ea']}")

        for item in e.get("signification", {}).get("externe", []):
            lines.append(f"\n  AE : {item['quasibloc']}")
            for ex in item.get("exemples", []):
                lines.append(f"      « {ex['phrase']} »")
                lines.append(f"        → {ex['ea']}")

        if e.get("nb"):
            lines.append(f"\n  NB : {e['nb']}")

        return "\n".join(lines)

    # ==================== PARAPHRASER ====================

    def paraphraser(self, mot):
        """Génère des paraphrases d'un mot en déployant ses blocs."""
        mot = mot.upper()
        e = self.entries.get(mot)
        if not e:
            return f"'{mot}' non trouvé."

        lines = [f"\n  Paraphrases de {mot} :\n"]

        for item in e.get("signification", {}).get("interne", []):
            aspect = item["aspect"]
            # Extraire les segments autour de DC/PT
            for conn_word, conn_fr in [("DC", "donc"), ("PT", "pourtant")]:
                match = re.search(rf"(.+?)\s+{conn_word}\s+(.+)", aspect)
                if match:
                    seg1 = match.group(1).strip()
                    seg2 = match.group(2).strip()
                    lines.append(f"  • {seg1}, {conn_fr} {seg2}")
                    lines.append(f"    (déploiement de : {aspect})")

        # Lexicalisation inverse : mots qui partagent les mêmes fondateurs
        f1 = e.get("fondateur1", "").strip()
        f2 = e.get("fondateur2", "").strip()
        synonymes = []
        for hw, other in self.entries.items():
            if hw == mot:
                continue
            of1 = other.get("fondateur1", "").strip()
            of2 = other.get("fondateur2", "").strip()
            if of1 == f1 and of2 == f2:
                synonymes.append(hw)
        if synonymes:
            lines.append(f"\n  Mots partageant les mêmes fondateurs ({f1} — {f2}) :")
            for s in synonymes:
                lines.append(f"    → {s}")

        return "\n".join(lines)

    # ==================== COMPARER ====================

    def comparer(self, mot1, mot2):
        """Compare deux mots structurellement."""
        mot1, mot2 = mot1.upper(), mot2.upper()
        e1 = self.entries.get(mot1)
        e2 = self.entries.get(mot2)
        if not e1:
            return f"'{mot1}' non trouvé."
        if not e2:
            return f"'{mot2}' non trouvé."

        lines = [f"\n  ══ {mot1} vs {mot2} ══\n"]

        # Fondateurs partagés
        f1_1, f1_2 = e1.get("fondateur1", ""), e1.get("fondateur2", "")
        f2_1, f2_2 = e2.get("fondateur1", ""), e2.get("fondateur2", "")
        shared = set()
        for f in (f1_1, f1_2):
            if f.strip() in (f2_1.strip(), f2_2.strip()):
                shared.add(f.strip())

        lines.append(f"  {mot1} : {f1_1} — {f1_2}")
        lines.append(f"  {mot2} : {f2_1} — {f2_2}")

        if shared:
            lines.append(f"\n  Fondateur(s) partagé(s) : {', '.join(shared)}")
        else:
            lines.append(f"\n  Aucun fondateur partagé.")

        # Comparer connecteurs
        a1 = self._get_aspects(e1)
        a2 = self._get_aspects(e2)
        dc1 = any(re.search(r"\bDC\b", a) for a in a1)
        pt1 = any(re.search(r"\bPT\b", a) for a in a1)
        dc2 = any(re.search(r"\bDC\b", a) for a in a2)
        pt2 = any(re.search(r"\bPT\b", a) for a in a2)

        if shared:
            if dc1 and pt2:
                lines.append(f"  → {mot1} (DC) vs {mot2} (PT) sur le même fondateur")
                lines.append(f"    Relation : opposition DC/PT — connecter par « mais »")
                lines.append(f"    Exemple : « X est {mot1.lower()} mais {mot2.lower()} »")
            elif pt1 and dc2:
                lines.append(f"  → {mot1} (PT) vs {mot2} (DC) sur le même fondateur")
                lines.append(f"    Relation : opposition PT/DC — connecter par « mais »")
            elif dc1 and dc2:
                lines.append(f"  → Les deux en DC — relation de synonymie ou gradualité")
            elif pt1 and pt2:
                lines.append(f"  → Les deux en PT — relation de synonymie transgressive")

        # Paradoxalité
        p1 = e1.get("paradoxal", False)
        p2 = e2.get("paradoxal", False)
        if p1 and not p2:
            lines.append(f"  → {mot1} est paradoxal, {mot2} ne l'est pas")
        elif p2 and not p1:
            lines.append(f"  → {mot2} est paradoxal, {mot1} ne l'est pas")
        elif p1 and p2:
            lines.append(f"  → Les deux sont paradoxaux")

        return "\n".join(lines)

    # ==================== VOISINS ====================

    def voisins(self, mot):
        """Trouve les mots qui partagent au moins un fondateur."""
        mot = mot.upper()
        e = self.entries.get(mot)
        if not e:
            return f"'{mot}' non trouvé."

        f1 = e.get("fondateur1", "").strip()
        f2 = e.get("fondateur2", "").strip()
        results = {}
        for f in (f1, f2):
            if f and f in self.fondateur_to_words:
                for hw in self.fondateur_to_words[f]:
                    if hw != mot:
                        results.setdefault(hw, []).append(f)

        lines = [f"\n  Voisins de {mot} :\n"]
        for hw, shared in sorted(results.items()):
            lines.append(f"  • {hw}  (via {', '.join(shared)})")
        if not results:
            lines.append("  (aucun voisin trouvé)")
        return "\n".join(lines)

    # ==================== COHÉRENCE ====================

    def est_coherent(self, mot, continuation):
        """Vérifie si une continuation est cohérente avec le mot."""
        mot = mot.upper()
        continuation = continuation.upper()
        e = self.entries.get(mot)
        c = self.entries.get(continuation)
        if not e or not c:
            return None, "Mot(s) non trouvé(s)."

        # Vérifier si les fondateurs sont compatibles
        f_mot = {e.get("fondateur1", "").strip(), e.get("fondateur2", "").strip()} - {""}
        f_cont = {c.get("fondateur1", "").strip(), c.get("fondateur2", "").strip()} - {""}

        shared = f_mot & f_cont
        if shared:
            return True, f"Cohérent : fondateur(s) partagé(s) {shared}"
        else:
            return False, f"Pas de lien structurel direct entre {mot} et {continuation}"

    # ==================== GÉNÉRER ====================

    def generer_definition(self, mot):
        """Génère une définition à partir de la structure TBS."""
        mot = mot.upper()
        e = self.entries.get(mot)
        if not e:
            return f"'{mot}' non trouvé."

        f1 = e.get("fondateur1", "").strip()
        f2 = e.get("fondateur2", "").strip()
        is_paradoxal = e.get("paradoxal", False)

        aspects = self._get_aspects(e)
        has_dc = any(re.search(r"\bDC\b", a) for a in aspects)
        has_pt = any(re.search(r"\bPT\b", a) for a in aspects)

        parts = [f"{mot} :"]

        if has_dc and not has_pt:
            parts.append(f"Mot normatif qui articule {f1} et {f2} par un lien de conséquence (DC).")
        elif has_pt and not has_dc:
            parts.append(f"Mot transgressif qui articule {f1} et {f2} par un lien d'opposition (PT).")
            parts.append("C'est un paradoxe incomplet : la version en DC n'est pas formulable.")
        elif has_dc and has_pt:
            parts.append(f"Mot qui articule {f1} et {f2} par les deux connecteurs (DC et PT).")
            if is_paradoxal:
                parts.append("Mot paradoxal complet.")

        # Ajouter les aspects
        for item in e.get("signification", {}).get("interne", []):
            aspect = item["aspect"]
            parts.append(f"AI : {aspect}")

        return " ".join(parts)


# ==================== MODE INTERACTIF ====================

def main():
    engine = TBSEngine()
    print("╔══════════════════════════════════════╗")
    print("║      TBS ENGINE — prototype v1       ║")
    print("║  Moteur sémantique argumentatif       ║")
    print("╚══════════════════════════════════════╝")
    print(f"\n  {len(engine.entries)} mots chargés.")
    print(f"  {len(engine.dc_words)} normatifs (DC)")
    print(f"  {len(engine.pt_words)} transgressifs (PT)")
    print(f"  {len(engine.paradoxaux)} paradoxaux\n")
    print("  Commandes :")
    print("    a <mot>          — analyser")
    print("    p <mot>          — paraphraser")
    print("    c <mot1> <mot2>  — comparer")
    print("    v <mot>          — voisins")
    print("    d <mot>          — générer définition")
    print("    q                — quitter\n")

    while True:
        try:
            line = input("  tbs> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split(None, 2)
        cmd = parts[0].lower()

        if cmd == "q":
            break
        elif cmd == "a" and len(parts) >= 2:
            print(engine.analyser(parts[1]))
        elif cmd == "p" and len(parts) >= 2:
            print(engine.paraphraser(parts[1]))
        elif cmd == "c" and len(parts) >= 3:
            print(engine.comparer(parts[1], parts[2]))
        elif cmd == "v" and len(parts) >= 2:
            print(engine.voisins(parts[1]))
        elif cmd == "d" and len(parts) >= 2:
            print(engine.generer_definition(parts[1]))
        else:
            print("  Commande non reconnue.")
        print()


if __name__ == "__main__":
    main()
