#!/usr/bin/env python3
"""
TBS Chatbot — Conversationnel basé sur le graphe sémantique argumentatif.

Charge le dictionnaire TBS et peut :
- Expliquer le sens des mots via leurs blocs argumentatifs
- Comparer des mots structurellement
- Répondre à des questions simples sur le lexique
- Converser en s'appuyant sur les enchaînements DC/PT

Usage :
    python3 scripts/tbs_chat.py
    python3 scripts/tbs_chat.py --json chemin/vers/dictionnaire.json
"""

import json
import re
import sys
import random
from pathlib import Path

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"


class TBSChat:
    def __init__(self, path=DICT_PATH):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.entries = {e["headword"]: e for e in data}
        self.all_words = sorted(self.entries.keys())
        self.context = {"last_word": None, "last_words": []}
        self._build_indices()

    def _build_indices(self):
        self.fondateur_to_words = {}
        for hw, e in self.entries.items():
            for f in (e.get("fondateur1", ""), e.get("fondateur2", "")):
                f = f.strip()
                if f:
                    self.fondateur_to_words.setdefault(f, []).append(hw)

    def _get_aspects(self, entry):
        aspects = []
        for item in entry.get("signification", {}).get("interne", []):
            aspects.append(item.get("aspect", ""))
        for item in entry.get("signification", {}).get("externe", []):
            aspects.append(item.get("quasibloc", ""))
        return aspects

    def _has_dc(self, e):
        return any(re.search(r"\bDC\b", a) for a in self._get_aspects(e))

    def _has_pt(self, e):
        return any(re.search(r"\bPT\b", a) for a in self._get_aspects(e))

    def _find_words_in(self, text):
        """Trouve les mots du dictionnaire présents dans le texte."""
        text_upper = text.upper()
        found = []
        # Chercher du plus long au plus court pour éviter les sous-matches
        for hw in sorted(self.all_words, key=len, reverse=True):
            pattern = r"\b" + re.escape(hw) + r"\b"
            if re.search(pattern, text_upper):
                found.append(hw)
        return found

    def _find_voisins(self, hw):
        e = self.entries.get(hw)
        if not e:
            return []
        fondateurs = set()
        for f in (e.get("fondateur1", ""), e.get("fondateur2", "")):
            if f.strip():
                fondateurs.add(f.strip())
        voisins = []
        for f in fondateurs:
            for other in self.fondateur_to_words.get(f, []):
                if other != hw and other not in voisins:
                    voisins.append(other)
        return voisins

    def _deploy_aspect(self, aspect):
        """Transforme un aspect en phrase naturelle."""
        for conn, fr in [("DC", "donc"), ("PT", "pourtant")]:
            m = re.search(rf"(.+?)\s+{conn}\s+(.+)", aspect)
            if m:
                seg1 = m.group(1).strip().lower()
                seg2 = m.group(2).strip().lower()
                return f"{seg1}, {fr} {seg2}"
        return aspect.lower()

    def _explain_word(self, hw):
        e = self.entries[hw]
        f1 = e.get("fondateur1", "").strip()
        f2 = e.get("fondateur2", "").strip()
        has_dc = self._has_dc(e)
        has_pt = self._has_pt(e)
        is_paradoxal = e.get("paradoxal", False)

        lines = []
        lines.append(f"{hw} s'articule autour de {f1} et {f2}.")

        aspects = e.get("signification", {}).get("interne", [])
        if aspects:
            a = aspects[0]["aspect"]
            deployed = self._deploy_aspect(a)
            lines.append(f"Concrètement : {deployed}.")

            exemples = aspects[0].get("exemples", [])
            if exemples:
                ex = random.choice(exemples)
                lines.append(f'Par exemple : « {ex["phrase"]} »')
                if ex.get("ea"):
                    lines.append(f"C'est-à-dire : {ex['ea']}")

        if is_paradoxal:
            lines.append(f"C'est un mot paradoxal — il va contre la doxa.")
        if has_pt and not has_dc:
            lines.append(f"C'est un mot purement transgressif (PT) : on ne peut pas formuler la version en DC.")
        elif has_dc and has_pt:
            lines.append(f"Ce mot admet les deux connecteurs (DC et PT).")

        return "\n".join(lines)

    def _compare_words(self, hw1, hw2):
        e1, e2 = self.entries.get(hw1), self.entries.get(hw2)
        if not e1 or not e2:
            return None

        f1 = {e1.get("fondateur1", "").strip(), e1.get("fondateur2", "").strip()} - {""}
        f2 = {e2.get("fondateur1", "").strip(), e2.get("fondateur2", "").strip()} - {""}
        shared = f1 & f2

        lines = []
        if shared:
            lines.append(f"{hw1} et {hw2} partagent le fondateur {', '.join(shared)}.")
            dc1, pt1 = self._has_dc(e1), self._has_pt(e1)
            dc2, pt2 = self._has_dc(e2), self._has_pt(e2)
            if dc1 and pt2:
                lines.append(f"{hw1} est normatif (DC) tandis que {hw2} est transgressif (PT).")
                lines.append(f"On pourrait dire : « Il est {hw1.lower()} mais {hw2.lower()}. »")
            elif pt1 and dc2:
                lines.append(f"{hw1} est transgressif (PT) tandis que {hw2} est normatif (DC).")
                lines.append(f"On pourrait dire : « Il est {hw2.lower()} mais {hw1.lower()}. »")
            elif dc1 and dc2:
                lines.append("Tous les deux sont normatifs (DC) — proches sémantiquement.")
            elif pt1 and pt2:
                lines.append("Tous les deux sont transgressifs (PT) — proches sémantiquement.")
        else:
            lines.append(f"{hw1} et {hw2} n'ont aucun fondateur en commun.")
            a1 = e1.get("signification", {}).get("interne", [])
            a2 = e2.get("signification", {}).get("interne", [])
            if a1:
                lines.append(f"{hw1} : {self._deploy_aspect(a1[0]['aspect'])}.")
            if a2:
                lines.append(f"{hw2} : {self._deploy_aspect(a2[0]['aspect'])}.")

        return "\n".join(lines)

    # ==================== RÉPONDRE ====================

    def respond(self, user_input):
        text = user_input.strip()
        if not text:
            return "Dis-moi un mot ou pose-moi une question sur le lexique."

        text_lower = text.lower()
        text_upper = text.upper()

        # --- Salutations ---
        if re.match(r"^(salut|bonjour|hello|hey|coucou|hi)\b", text_lower):
            n = len(self.entries)
            return f"Bonjour ! Je connais {n} mots. Demande-moi le sens d'un mot, ou compare deux mots entre eux."

        # --- Aide ---
        if text_lower in ("aide", "help", "?", "commandes"):
            return (
                "Tu peux me demander :\n"
                "• Le sens d'un mot : « que signifie prudent ? »\n"
                "• Une comparaison : « compare prudent et courageux »\n"
                "• Les voisins : « quels mots sont proches de danger ? »\n"
                "• Un mot au hasard : « donne-moi un mot »\n"
                "• La liste des mots paradoxaux : « quels mots sont paradoxaux ? »\n"
                "• Ou simplement tape un mot pour que je l'analyse."
            )

        # --- Mot au hasard ---
        if re.search(r"hasard|aléatoire|random|donne.moi un mot", text_lower):
            hw = random.choice(self.all_words)
            self.context["last_word"] = hw
            return f"Au hasard : {hw}\n\n{self._explain_word(hw)}"

        # --- Liste paradoxaux ---
        if re.search(r"paradox", text_lower):
            paradox = [hw for hw, e in self.entries.items() if e.get("paradoxal")]
            pt_only = [hw for hw, e in self.entries.items()
                       if self._has_pt(e) and not self._has_dc(e)
                       and not e.get("paradoxal")]
            lines = []
            if paradox:
                lines.append(f"Mots paradoxaux : {', '.join(paradox)}")
            if pt_only:
                lines.append(f"\nMots purement transgressifs (PT, paradoxe incomplet) :")
                lines.append(", ".join(pt_only[:15]))
                if len(pt_only) > 15:
                    lines.append(f"... et {len(pt_only) - 15} autres.")
            return "\n".join(lines) if lines else "Aucun mot paradoxal trouvé."

        # --- Comparaison ---
        m = re.search(
            r"(?:compar|diff[ée]ren|rapport|relation|versus|vs)\w*\s+(\w[\w\s']*?)\s+(?:et|with|vs|\/)\s+(\w[\w\s']*)",
            text_lower,
        )
        if m:
            w1 = m.group(1).strip().upper()
            w2 = m.group(2).strip().upper()
            # Chercher le meilleur match
            w1 = self._best_match(w1)
            w2 = self._best_match(w2)
            if w1 and w2:
                self.context["last_words"] = [w1, w2]
                result = self._compare_words(w1, w2)
                if result:
                    return result
            return f"Je ne connais pas l'un de ces mots. Je connais : {', '.join(self.all_words[:10])}..."

        # --- Question sur un mot (que signifie, c'est quoi, définition) ---
        m = re.search(
            r"(?:signif|veut dire|c.est quoi|défin|explique|sens de|qu.est.ce que?)\w*\s+([\w\s'àâéèêëïîôùûüç-]+)",
            text_lower,
        )
        if m:
            candidate = m.group(1).strip().upper()
            hw = self._best_match(candidate)
            if hw:
                self.context["last_word"] = hw
                return self._explain_word(hw)

        # --- Voisins ---
        m = re.search(r"(?:voisin|proche|li[ée]|autour|famille)\w*\s+([\w\s'àâéèêëïîôùûüç-]+)", text_lower)
        if m:
            candidate = m.group(1).strip().upper()
            hw = self._best_match(candidate)
            if hw:
                voisins = self._find_voisins(hw)
                if voisins:
                    self.context["last_word"] = hw
                    return f"Mots proches de {hw} (fondateurs partagés) :\n• " + "\n• ".join(voisins)
                return f"{hw} n'a pas de voisins directs dans le dictionnaire."

        # --- Pronoms / contexte (il, elle, ce mot, celui-là) ---
        if re.search(r"\b(il|elle|ce mot|celui[- ]?l[àa])\b", text_lower) and self.context["last_word"]:
            hw = self.context["last_word"]
            # Essayer de comprendre la question sur le dernier mot
            if re.search(r"paradox", text_lower):
                e = self.entries[hw]
                if e.get("paradoxal"):
                    return f"Oui, {hw} est paradoxal."
                elif self._has_pt(e) and not self._has_dc(e):
                    return f"{hw} est un paradoxe incomplet (PT seul, DC bloqué)."
                else:
                    return f"Non, {hw} n'est pas paradoxal."
            if re.search(r"exemple|phrase", text_lower):
                e = self.entries[hw]
                for item in e.get("signification", {}).get("interne", []):
                    for ex in item.get("exemples", []):
                        return f'« {ex["phrase"]} »\n→ {ex["ea"]}'
            return self._explain_word(hw)

        # --- Mot seul ou mot dans une phrase ---
        found = self._find_words_in(text)
        if found:
            if len(found) == 1:
                hw = found[0]
                self.context["last_word"] = hw
                return self._explain_word(hw)
            elif len(found) == 2:
                self.context["last_words"] = found[:2]
                result = self._compare_words(found[0], found[1])
                if result:
                    return f"Je vois deux mots que je connais :\n\n{result}"
            else:
                self.context["last_words"] = found
                lines = [f"Je reconnais {len(found)} mots dans ta phrase :"]
                for hw in found[:5]:
                    e = self.entries[hw]
                    a = self._get_aspects(e)
                    if a:
                        lines.append(f"  • {hw} — {self._deploy_aspect(a[0])}")
                    else:
                        lines.append(f"  • {hw}")
                return "\n".join(lines)

        # --- Rien trouvé ---
        return (
            f"Je ne connais pas ce mot (ou ces mots). "
            f"J'ai {len(self.entries)} entrées dans mon dictionnaire.\n"
            f"Essaie par exemple : prudent, courageux, acheter, mégenrer, résilience..."
        )

    def _best_match(self, candidate):
        """Trouve le meilleur match pour un candidat dans le dictionnaire."""
        candidate = candidate.strip().upper()
        if candidate in self.entries:
            return candidate
        # Chercher un match partiel
        for hw in self.all_words:
            if candidate in hw or hw in candidate:
                return hw
        return None


def main():
    path = DICT_PATH
    if "--json" in sys.argv:
        idx = sys.argv.index("--json")
        if idx + 1 < len(sys.argv):
            path = Path(sys.argv[idx + 1])

    chat = TBSChat(path)

    print()
    print("  ┌──────────────────────────────────────┐")
    print("  │         TBS Chat — prototype          │")
    print("  │   Conversationnel sémantique-arg.     │")
    print("  └──────────────────────────────────────┘")
    print(f"\n  {len(chat.entries)} mots chargés depuis {path.name}")
    print("  Tape 'aide' pour les commandes, 'q' pour quitter.\n")

    while True:
        try:
            user = input("  toi > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  À bientôt !")
            break
        if not user:
            continue
        if user.lower() in ("q", "quit", "exit", "quitter"):
            print("  À bientôt !")
            break

        response = chat.respond(user)
        # Afficher la réponse avec indentation
        for line in response.split("\n"):
            print(f"  bot > {line}")
        print()


if __name__ == "__main__":
    main()
