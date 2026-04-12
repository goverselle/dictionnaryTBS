#!/usr/bin/env python3
"""
TBS Inference Chatbot — raisonne à partir du graphe sémantique.

Comprend des phrases simples, active des faits via les blocs TBS,
et répond aux questions en cherchant dans les faits actifs.

Usage :
    python3 scripts/tbs_infer.py
    python3 scripts/tbs_infer.py --json chemin/vers/champ.json
"""

import json
import re
import sys
from pathlib import Path
from simplemma import lemmatize as _simplemma

DEFAULT_DICT = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"

# =====================================================================
# LEMMATISATION MANUELLE (champ commercial)
# =====================================================================

LEMMES = {
    # ACHETER
    "achète": "ACHETER", "achètes": "ACHETER", "acheté": "ACHETER",
    "achetée": "ACHETER", "achetés": "ACHETER", "achetées": "ACHETER",
    "acheter": "ACHETER", "achètent": "ACHETER", "achetait": "ACHETER",
    "achetera": "ACHETER", "a acheté": "ACHETER",
    # VENDRE
    "vend": "VENDRE", "vends": "VENDRE", "vendu": "VENDRE",
    "vendue": "VENDRE", "vendus": "VENDRE", "vendre": "VENDRE",
    "vendent": "VENDRE", "vendait": "VENDRE", "a vendu": "VENDRE",
    # VOLER
    "vole": "VOLER", "voles": "VOLER", "volé": "VOLER",
    "volée": "VOLER", "volés": "VOLER", "voler": "VOLER",
    "volent": "VOLER", "volait": "VOLER", "a volé": "VOLER",
    # COÛTER
    "coûte": "COÛTER", "coûtent": "COÛTER", "coûtait": "COÛTER",
    "coûter": "COÛTER",
    # PAYER
    "paye": "PAYER", "payes": "PAYER", "payé": "PAYER",
    "payée": "PAYER", "payer": "PAYER", "payent": "PAYER",
    "payait": "PAYER", "a payé": "PAYER",
    # DÉPENSER
    "dépense": "DÉPENSER", "dépensé": "DÉPENSER", "dépenser": "DÉPENSER",
    "dépensait": "DÉPENSER", "a dépensé": "DÉPENSER",
    # ÉCONOMISER
    "économise": "ÉCONOMISER", "économisé": "ÉCONOMISER",
    "économiser": "ÉCONOMISER", "a économisé": "ÉCONOMISER",
    # PRÊTER
    "prête": "PRÊTER", "prêté": "PRÊTER", "prêtée": "PRÊTER",
    "prêter": "PRÊTER", "prêtait": "PRÊTER", "a prêté": "PRÊTER",
    # EMPRUNTER
    "emprunte": "EMPRUNTER", "emprunté": "EMPRUNTER",
    "empruntée": "EMPRUNTER", "emprunter": "EMPRUNTER",
    "empruntait": "EMPRUNTER", "a emprunté": "EMPRUNTER",
    # REMBOURSER
    "rembourse": "REMBOURSER", "remboursé": "REMBOURSER",
    "rembourser": "REMBOURSER", "remboursait": "REMBOURSER",
    "a remboursé": "REMBOURSER",
    # DONNER
    "donne": "DONNER", "donné": "DONNER", "donnée": "DONNER",
    "donner": "DONNER", "donnait": "DONNER", "a donné": "DONNER",
    # PRENDRE
    "prend": "PRENDRE", "pris": "PRENDRE", "prise": "PRENDRE",
    "prendre": "PRENDRE", "prenait": "PRENDRE", "a pris": "PRENDRE",
    # CHER / BON MARCHÉ
    "cher": "CHER", "chère": "CHER", "chers": "CHER", "chères": "CHER",
    "bon marché": "BON MARCHÉ",
    # DETTE
    "dette": "DETTE", "dettes": "DETTE",
    # PRIX
    "prix": "PRIX",
    # RENDRE
    "rend": "RENDRE", "rendu": "RENDRE", "rendue": "RENDRE",
    "rendre": "RENDRE", "a rendu": "RENDRE",
}


# =====================================================================
# FAITS — ce que le bot sait sur le monde de la conversation
# =====================================================================

class Fait:
    """Un fait déduit : (sujet, prédicat, objet, négatif?)"""
    def __init__(self, sujet, predicat, objet=None, neg=False, source=None):
        self.sujet = sujet.lower() if sujet else None
        self.predicat = predicat.upper() if predicat else None
        self.objet = objet.lower() if objet else None
        self.neg = neg
        self.source = source  # le mot TBS qui a produit ce fait

    def match(self, sujet=None, predicat=None, objet=None):
        """Vérifie si ce fait correspond à une recherche."""
        if sujet and self.sujet and sujet.lower() != self.sujet:
            return False
        if predicat and self.predicat and predicat.upper() != self.predicat:
            return False
        if objet and self.objet and objet.lower() != self.objet:
            return False
        return True

    def __repr__(self):
        neg = "NEG " if self.neg else ""
        obj = f" {self.objet}" if self.objet else ""
        return f"{self.sujet} {neg}{self.predicat}{obj}"


# =====================================================================
# PARSEUR D'ASPECTS — découpe "X PAYER À Z DC X AVOIR Y"
# =====================================================================

def parse_aspect(aspect_str):
    """Découpe un aspect en (segment_gauche, connecteur, segment_droit)."""
    for conn in ("DC", "PT"):
        pattern = rf"^(.+?)\s+{conn}\s+(.+)$"
        m = re.match(pattern, aspect_str)
        if m:
            return m.group(1).strip(), conn, m.group(2).strip()
    return aspect_str, None, None


def extract_predicates(segment):
    """Extrait les prédicats d'un segment.
    'X PAYER À Z' → [('X', 'PAYER', 'Z', False)]
    'NEG X PAYER' → [('X', 'PAYER', None, True)]
    'X NEG PAYER À Z' → [('X', 'PAYER', 'Z', True)]
    '*X* AVOIR Y' → [('X', 'AVOIR', 'Y', False)]
    """
    # Nettoyer les astérisques (marqueurs d'application)
    seg = segment.replace("*", "")
    seg = re.sub(r"\s+", " ", seg).strip()

    # Détecter NEG n'importe où et le retirer
    neg = False
    if re.search(r"\bNEG\b", seg):
        neg = True
        seg = re.sub(r"\bNEG\s*", "", seg).strip()

    # Trouver les variables (lettres seules) et les prédicats (mots en majuscules)
    tokens = seg.split()
    variables = []
    predicates = []
    current_pred = []

    for t in tokens:
        if re.match(r"^[XYZW]$", t):
            if current_pred:
                predicates.append(" ".join(current_pred))
                current_pred = []
            variables.append(t)
        elif t in ("À", "DE"):
            continue  # prépositions, ignorer
        else:
            current_pred.append(t)

    if current_pred:
        predicates.append(" ".join(current_pred))

    results = []
    for pred in predicates:
        subj = variables[0] if variables else None
        obj_var = variables[1] if len(variables) > 1 else None
        results.append((subj, pred, obj_var, neg))

    return results


# =====================================================================
# MOTEUR D'INFÉRENCE
# =====================================================================

class TBSInference:
    def __init__(self, path=DEFAULT_DICT):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.entries = {e["headword"]: e for e in data}
        self.facts = []
        self.bindings = {}
        self.pronouns = {}
        self.last_word = None
        self.history = []
        self._build_auto_lemmes()

    def _build_auto_lemmes(self):
        """Construit l'index de lemmes : manual + headwords en lowercase."""
        self.manual_lemmes = dict(LEMMES)
        # Ajouter chaque headword sous sa forme brute
        for hw in self.entries:
            self.manual_lemmes.setdefault(hw.lower(), hw)

    def lemmatize(self, text):
        """Trouve un mot TBS dans le texte via simplemma + fallback manuel."""
        t = text.lower()

        # 1) Chercher les lemmes manuels composés (ex: "bon marché", "a acheté")
        for lemme in sorted(self.manual_lemmes.keys(), key=len, reverse=True):
            if len(lemme) > 2 and lemme in t:
                return self.manual_lemmes[lemme]

        # 2) Tokeniser et lemmatiser chaque mot avec simplemma
        tokens = re.findall(r"[a-zà-üœæ'-]+", t)
        for tok in tokens:
            # simplemma
            lemme = _simplemma(tok, lang="fr")
            hw = lemme.upper()
            if hw in self.entries:
                return hw
            # fallback : le token brut
            if tok.upper() in self.entries:
                return tok.upper()
            # fallback : lemmes manuels
            if tok in self.manual_lemmes:
                return self.manual_lemmes[tok]
            if lemme in self.manual_lemmes:
                return self.manual_lemmes[lemme]

        return None

    def extract_entities(self, text):
        """Extrait les noms propres et les objets de la phrase."""
        # Noms propres (majuscule au milieu de la phrase)
        noms = re.findall(r"\b([A-ZÀ-Ü][a-zà-ü]+)\b", text)
        # Filtrer les mots de début de phrase et les mots du dico
        noms = [n for n in noms if n.upper() not in self.entries
                and n.lower() not in ("oui", "non", "elle", "il", "est", "les",
                                       "des", "une", "quelle", "est")]

        # Objets : chercher après le verbe, articles + nom
        objets = re.findall(
            r"(?:le |la |l'|les |un |une |des |du |son |sa |ses |cet |cette )(\w+(?:\s+\w+)?)",
            text.lower(),
        )
        # Filtrer les verbes connus
        objets = [o for o in objets if o not in LEMMES and o + "é" not in LEMMES]

        return noms, objets

    def resolve_pronouns(self, text):
        """Remplace les pronoms par les entités connues."""
        t = text
        for pron, entity in self.pronouns.items():
            t = re.sub(r"\b" + pron + r"\b", entity, t, flags=re.IGNORECASE)
        # "l'" → dernier objet
        if "l'" in t.lower() and self.bindings.get("Y"):
            t = re.sub(r"\bl'", self.bindings["Y"] + " ", t, flags=re.IGNORECASE)
        return t

    def bind_variables(self, text, word):
        """Lie X, Y, Z aux entités de la phrase en lisant les *X*/*Z* de l'aspect."""
        noms, objets = self.extract_entities(text)
        entry = self.entries.get(word)
        if not entry:
            return

        # Lire l'aspect pour savoir quelle variable est le sujet (marquée *X* ou *Z*)
        aspect = ""
        if entry["signification"]["interne"]:
            aspect = entry["signification"]["interne"][0]["aspect"]

        # La première variable avec astérisques = le sujet de la phrase
        subject_var = "X"  # défaut
        m = re.search(r"\*([XYZW])\*", aspect)
        if m:
            subject_var = m.group(1)

        # L'autre variable présente = le destinataire
        all_vars = re.findall(r"\b([XYZW])\b", aspect.replace("*", ""))
        other_vars = [v for v in dict.fromkeys(all_vars) if v != subject_var and v != "Y" and v != "W"]
        dest_var = other_vars[0] if other_vars else None

        # Séparer sujet (avant verbe / premier nom) et destinataire (après "à" / second nom)
        text_lower = text.lower()
        sujet_noms = []
        dest_noms = []
        for n in noms:
            n_pos = text.find(n)
            if " à " in text_lower and n_pos > text_lower.find(" à "):
                dest_noms.append(n)
            elif not sujet_noms:
                sujet_noms.append(n)
            else:
                dest_noms.append(n)

        # Lier le sujet grammatical à la variable-sujet de l'aspect
        if sujet_noms:
            self.bindings[subject_var] = sujet_noms[0].lower()
            self.pronouns[self._pronoun(sujet_noms[0])] = sujet_noms[0]
        if dest_noms:
            if dest_var:
                self.bindings[dest_var] = dest_noms[0].lower()
            else:
                # Fallback : stocker le destinataire dans la première variable libre
                for v in ("X", "Z"):
                    if v != subject_var and v not in self.bindings:
                        self.bindings[v] = dest_noms[0].lower()
                        break
            self.pronouns[self._pronoun(dest_noms[0])] = dest_noms[0]

        if objets:
            self.bindings["Y"] = objets[0]

    def _pronoun(self, name):
        """Heuristique basique pour le pronom."""
        # Noms féminins courants
        fem = ("marie", "anne", "sophie", "claire", "julie", "emma", "alice",
               "lucie", "léa", "chloé", "sarah", "lisa", "nina", "laura")
        if name.lower() in fem:
            return "elle"
        return "il"

    def activate_facts(self, word, depth=0):
        """Active les faits déduits du bloc TBS du mot, avec chaînage."""
        if depth > 5:
            return  # éviter les boucles infinies
        entry = self.entries.get(word)
        if not entry or not entry["signification"]["interne"]:
            return

        aspect = entry["signification"]["interne"][0]["aspect"]
        left, conn, right = parse_aspect(aspect)

        if not conn:
            return

        # Extraire les prédicats de chaque segment
        new_facts = []
        for seg in (left, right):
            preds = extract_predicates(seg)
            for subj_var, pred, obj_var, neg in preds:
                subj = self.bindings.get(subj_var, subj_var)
                obj = self.bindings.get(obj_var) if obj_var else None
                fait = Fait(
                    sujet=subj,
                    predicat=pred,
                    objet=obj,
                    neg=neg,
                    source=word,
                )
                # Éviter les doublons
                already = any(
                    f.sujet == fait.sujet and f.predicat == fait.predicat
                    and f.objet == fait.objet and f.neg == fait.neg
                    for f in self.facts
                )
                if not already:
                    self.facts.append(fait)
                    new_facts.append(fait)

        self.last_word = word

        # Règle de transfert : PAYER/DONNER/RENDRE à qqn → le destinataire AVOIR
        recipient = self.bindings.get("Z") or self.bindings.get("X")
        for fait in new_facts:
            if fait.neg:
                continue
            if fait.predicat in ("PAYER", "DONNER", "RENDRE"):
                # Le sujet donne/paye → le destinataire reçoit
                dest = None
                for var in ("Z", "X"):
                    v = self.bindings.get(var, "").lower()
                    if v and v != fait.sujet:
                        dest = v
                        break
                if dest:
                    objet = fait.objet or self.bindings.get("Y")
                    transfer = Fait(
                        sujet=dest,
                        predicat="AVOIR",
                        objet=objet,
                        neg=False,
                        source=fait.source,
                    )
                    already = any(
                        f.sujet == transfer.sujet and f.predicat == transfer.predicat
                        and f.objet == transfer.objet
                        for f in self.facts
                    )
                    if not already:
                        self.facts.append(transfer)
                        new_facts.append(transfer)

        # Chaînage : si un fait positif correspond à un headword, activer aussi
        for fait in new_facts:
            if not fait.neg and fait.predicat in self.entries:
                self.activate_facts(fait.predicat, depth + 1)

    def search_fact(self, sujet=None, predicat=None, objet=None):
        """Cherche un fait correspondant."""
        for fact in reversed(self.facts):  # plus récent d'abord
            if fact.match(sujet, predicat, objet):
                return fact
        return None

    def search_fact_broad(self, text):
        """Cherche un fait qui correspond au texte, en respectant le sujet."""
        t = text.lower()

        # Identifier le sujet de la question
        question_subject = None
        for pron, entity in self.pronouns.items():
            if pron in t:
                question_subject = entity.lower()
                break
        if not question_subject:
            noms, _ = self.extract_entities(text)
            if noms:
                question_subject = noms[0].lower()

        best = None
        best_score = 0
        for fact in reversed(self.facts):
            score = 0

            # Si on a un sujet dans la question, le fait DOIT correspondre
            if question_subject:
                if fact.sujet and fact.sujet == question_subject:
                    score += 3
                elif fact.sujet and fact.sujet != question_subject:
                    continue  # sujet différent → ignorer ce fait

            if fact.objet and fact.objet in t:
                score += 2
            if fact.predicat:
                pred_lower = fact.predicat.lower()
                if pred_lower in t:
                    score += 3
                for lemme, hw in LEMMES.items():
                    if hw == fact.predicat and lemme in t:
                        score += 3
                        break

            if score > best_score:
                best_score = score
                best = fact
        return best if best_score >= 2 else None

    def generate_response_fact(self, fact):
        """Génère une réponse en langue naturelle à partir d'un fait."""
        sujet = fact.sujet.capitalize() if fact.sujet else "quelqu'un"
        pred = (fact.predicat or "").upper()
        objet = fact.objet or ""

        # Conjuguer le prédicat
        pred_phrases = {
            "PAYER": ("a payé", "n'a pas payé"),
            "AVOIR": ("a", "n'a pas"),
            "DONNER": ("a donné", "n'a pas donné"),
            "PRENDRE": ("a pris", "n'a pas pris"),
            "DEVOIR RENDRE": ("doit rendre", "ne doit pas rendre"),
            "DEVOIR PAYER": ("doit payer", "ne doit pas payer"),
            "ACHETER": ("a acheté", "n'a pas acheté"),
            "VENDRE": ("a vendu", "n'a pas vendu"),
            "VOLER": ("a volé", "n'a pas volé"),
            "DÉPENSER": ("a dépensé", "n'a pas dépensé"),
            "ÉCONOMISER": ("a économisé", "n'a pas économisé"),
            "REMBOURSER": ("a remboursé", "n'a pas remboursé"),
            "COÛTER": ("coûte quelque chose", "ne coûte rien"),
            "ÊTRE BEAUCOUP": ("c'est beaucoup", "ce n'est pas beaucoup"),
            "ÊTRE ARGENT": ("c'est de l'argent", "ce n'est pas de l'argent"),
            "AVOIR ARGENT": ("a de l'argent", "n'a pas d'argent"),
            "AVOIR DETTE": ("a une dette", "n'a pas de dette"),
            "VOULOIR AVOIR": ("veut", "ne veut pas"),
            "POUVOIR DONNER": ("peut donner", "ne peut pas donner"),
            "POUVOIR VENDRE": ("peut vendre", "ne peut pas vendre"),
        }

        pos, neg_form = pred_phrases.get(pred, (f"a {pred.lower()}", f"n'a pas {pred.lower()}"))

        if objet:
            # Pas d'article devant les noms propres
            is_name = objet[0].isupper() or objet in self.pronouns.values() or any(
                p.lower() == objet for p in self.pronouns.values()
            )
            phrase_obj = f" {objet}" if is_name else f" {self._article(objet)}"
        else:
            phrase_obj = ""

        if fact.neg:
            return f"Non. {sujet} {neg_form}{phrase_obj}."
        else:
            return f"Oui. {sujet} {pos}{phrase_obj}."

    def _conjugate(self, predicat, sujet, neg=False):
        """Conjugue un prédicat avec un sujet."""
        p = predicat.upper()
        s = sujet.strip().capitalize() if sujet else "quelqu'un"
        # Si c'est un pronom, minuscule sauf en début
        if s.lower() in ("elle", "il", "ils", "elles", "on"):
            s = s.lower()

        verbs = {
            "PAYER": ("a payé", "n'a pas payé"),
            "AVOIR": ("a", "n'a pas"),
            "DONNER": ("a donné", "n'a pas donné"),
            "PRENDRE": ("a pris", "n'a pas pris"),
            "DEVOIR RENDRE": ("doit rendre", "ne doit pas rendre"),
            "DEVOIR PAYER": ("doit payer", "ne doit pas payer"),
            "ACHETER": ("a acheté", "n'a pas acheté"),
            "VENDRE": ("a vendu", "n'a pas vendu"),
            "VOLER": ("a volé", "n'a pas volé"),
            "DÉPENSER": ("a dépensé", "n'a pas dépensé"),
            "ÉCONOMISER": ("a économisé", "n'a pas économisé"),
            "REMBOURSER": ("a remboursé", "n'a pas remboursé"),
            "COÛTER": ("coûte", "ne coûte pas"),
            "ÊTRE BEAUCOUP": ("c'est beaucoup", "ce n'est pas beaucoup"),
            "ÊTRE ARGENT": ("c'est de l'argent", "ce n'est pas de l'argent"),
            "AVOIR ARGENT": ("a de l'argent", "n'a pas d'argent"),
            "AVOIR DETTE": ("a une dette", "n'a pas de dette"),
            "VOULOIR AVOIR": ("veut", "ne veut pas"),
        }

        pos, neg_form = verbs.get(p, (f"a {p.lower()}", f"n'a pas {p.lower()}"))
        return f"{s} {neg_form}" if neg else f"{s} {pos}"

    def deploy_aspect(self, word):
        """Déploie l'aspect du mot en une phrase naturelle avec les variables liées."""
        entry = self.entries.get(word)
        if not entry or not entry["signification"]["interne"]:
            return None

        aspect = entry["signification"]["interne"][0]["aspect"]
        left, conn, right = parse_aspect(aspect)
        if not conn:
            return None

        conn_fr = "donc" if conn == "DC" else "pourtant"

        # Construire chaque segment
        parts = []
        for seg in (left, right):
            preds = extract_predicates(seg)
            for subj_var, pred, obj_var, neg in preds:
                subj = self.bindings.get(subj_var, subj_var)
                obj = self.bindings.get(obj_var) if obj_var else None
                phrase = self._conjugate(pred, subj, neg)
                if obj:
                    # Pas d'article devant les noms propres
                    if obj[0].isupper() or obj in self.pronouns.values() or any(
                        p.lower() == obj for p in self.pronouns.values()
                    ):
                        phrase += f" {obj}"
                    else:
                        phrase += f" {self._article(obj)}"
                parts.append(phrase)

        if len(parts) >= 2:
            return f"{parts[0]}, {conn_fr} {parts[1]}."
        elif parts:
            return f"{parts[0]}."
        return None

    def _article(self, obj):
        """Article défini simple pour un objet."""
        if not obj:
            return ""
        obj = obj.strip()
        # Déjà un article ?
        if re.match(r"^(le |la |l'|les |du |de l)", obj):
            return obj
        vowels = "aeiouyàâéèêëïîôùûü"
        if obj[0].lower() in vowels:
            return f"l'{obj}"
        # Heuristique féminin
        fem_words = ("pomme", "voiture", "maison", "dette", "chose", "table",
                     "pommes", "voitures", "maisons", "dettes", "choses")
        if obj.lower() in fem_words:
            return f"la {obj}"
        fem_endings = ("tion", "sion", "ée", "ette", "elle", "ine", "ure", "ance", "ence", "ude")
        if obj.lower().endswith(fem_endings):
            return f"la {obj}"
        if obj.lower().endswith("s") and len(obj) > 2:
            return f"les {obj}"
        return f"le {obj}"

    # =================================================================
    # BOUCLE PRINCIPALE
    # =================================================================

    def process(self, user_input):
        """Traite une entrée utilisateur et retourne une réponse."""
        text = user_input.strip()
        if not text:
            return "Dis-moi quelque chose."

        # Résoudre les pronoms
        text_resolved = self.resolve_pronouns(text)

        # Est-ce une question ?
        is_question = "?" in text

        # Trouver un mot TBS
        word = self.lemmatize(text_resolved)

        if is_question:
            return self._handle_question(text_resolved, word)
        elif word:
            return self._handle_statement(text_resolved, word)
        else:
            # Pas de mot TBS trouvé — chercher dans les faits
            fact = self.search_fact_broad(text_resolved)
            if fact:
                return self.generate_response_fact(fact)
            return "Je ne connais pas ces mots. Parle-moi d'acheter, vendre, payer, prêter..."

    def _get_aspects(self, entry):
        aspects = []
        for item in entry.get("signification", {}).get("interne", []):
            aspects.append(item.get("aspect", ""))
        for item in entry.get("signification", {}).get("externe", []):
            aspects.append(item.get("quasibloc", ""))
        return aspects

    # =================================================================
    # INITIATIVES — le graphe propose des observations
    # =================================================================

    def _initiative_lateral(self, word):
        """Move 1 : si un voisin a le même fondateur mais un connecteur opposé."""
        entry = self.entries.get(word)
        if not entry:
            return None
        f1 = entry.get("fondateur1", "").strip()
        f2 = entry.get("fondateur2", "").strip()
        has_dc = any(re.search(r"\bDC\b", a) for a in self._get_aspects(entry))
        has_pt = any(re.search(r"\bPT\b", a) for a in self._get_aspects(entry))

        for hw, other in self.entries.items():
            if hw == word:
                continue
            of1 = other.get("fondateur1", "").strip()
            of2 = other.get("fondateur2", "").strip()
            # Même paire de fondateurs ?
            same_pair = ({f1, f2} == {of1, of2}) and f1 and f2
            # Au moins un fondateur partagé ?
            shared = ({f1, f2} & {of1, of2}) - {""}
            if not same_pair and not shared:
                continue

            other_dc = any(re.search(r"\bDC\b", a) for a in self._get_aspects(other))
            other_pt = any(re.search(r"\bPT\b", a) for a in self._get_aspects(other))

            # Connecteur opposé sur les mêmes fondateurs
            if same_pair and ((has_dc and other_pt) or (has_pt and other_dc)):
                if has_dc:
                    return f"À ne pas confondre avec {hw.lower()} : mêmes fondateurs, mais en pourtant au lieu de donc."
                else:
                    return f"À ne pas confondre avec {hw.lower()} : mêmes fondateurs, mais en donc au lieu de pourtant."
            elif shared and ((has_dc and other_pt) or (has_pt and other_dc)):
                shared_str = ", ".join(shared)
                return f"{hw.lower()} est lié — ils partagent {shared_str.lower()}, mais le lien est inversé."

        return None

    def _initiative_chain(self, word):
        """Move 2 : si le mot actuel est fondateur d'un autre mot, anticiper la suite."""
        children = []
        for hw, other in self.entries.items():
            if hw == word:
                continue
            of1 = other.get("fondateur1", "").strip()
            of2 = other.get("fondateur2", "").strip()
            if word == of1 or word == of2:
                children.append(hw)

        if not children:
            return None

        # Prendre le plus pertinent (le premier qui a un aspect)
        for child in children:
            e = self.entries[child]
            if e.get("signification", {}).get("interne"):
                aspect = e["signification"]["interne"][0]["aspect"]
                deployed = self._deploy_aspect_generic(aspect)
                if deployed:
                    return f"Et ensuite, {child.lower()} : {deployed}"
        return None

    def _deploy_aspect_generic(self, aspect):
        """Déploie un aspect sans bindings, juste les mots bruts."""
        for conn, fr in [("DC", "donc"), ("PT", "pourtant")]:
            m = re.match(rf"(.+?)\s+{conn}\s+(.+)", aspect.replace("*", ""))
            if m:
                seg1 = m.group(1).strip().lower()
                seg2 = m.group(2).strip().lower()
                return f"{seg1}, {fr} {seg2}"
        return None

    def _initiative_question(self, word):
        """Move 3 : si une variable du bloc n'est pas liée, poser la question."""
        entry = self.entries.get(word)
        if not entry or not entry["signification"]["interne"]:
            return None

        aspect = entry["signification"]["interne"][0]["aspect"]
        # Trouver toutes les variables utilisées dans l'aspect
        all_vars = set(re.findall(r"\b([XYZW])\b", aspect.replace("*", "")))

        missing = []
        var_labels = {"X": "qui", "Z": "à qui", "Y": "quoi", "W": "combien"}

        for v in sorted(all_vars):
            if v not in self.bindings or not self.bindings[v]:
                if v in var_labels:
                    missing.append(var_labels[v])

        if missing:
            return " ".join(m.capitalize() + " ?" for m in missing)
        return None

    def _generate_initiatives(self, word):
        """Génère les initiatives du bot après un énoncé."""
        initiatives = []

        # Move 3 d'abord — question sur les trous (priorité haute)
        q = self._initiative_question(word)
        if q:
            initiatives.append(q)

        # Move 1 — suggestion latérale
        lat = self._initiative_lateral(word)
        if lat:
            initiatives.append(lat)

        # Move 2 — chaîne anticipative
        chain = self._initiative_chain(word)
        if chain:
            initiatives.append(chain)

        return initiatives

    # =================================================================

    def _handle_statement(self, text, word):
        """Traite un énoncé affirmatif."""
        # Garder les anciens faits, juste mettre à jour les bindings
        self.bindings = {}

        # Lier les variables
        self.bind_variables(text, word)

        # Activer les faits
        self.activate_facts(word)

        # Générer la réponse = déploiement du bloc
        deployed = self.deploy_aspect(word)
        parts = []
        if deployed:
            parts.append(f"D'accord. {deployed}")
        else:
            parts.append("D'accord.")

        # Ajouter les initiatives
        initiatives = self._generate_initiatives(word)
        for init in initiatives[:2]:  # max 2 initiatives par tour
            parts.append(init)

        return "\n".join(parts)

    def _handle_question(self, text, word):
        """Traite une question."""
        text_lower = text.lower()

        # "peut vendre ?" / "peut prêter ?" → vérifier les prérequis
        m = re.search(r"(?:peut|pourrait|capable de)\s+(\w+)", text_lower)
        if m:
            action_lemme = m.group(1)
            action_word = LEMMES.get(action_lemme, action_lemme.upper())
            return self._can_do(text, action_word)

        # Chercher dans les faits actifs
        fact = self.search_fact_broad(text)

        if fact:
            resp = self.generate_response_fact(fact)
            if fact.source:
                deployed = self.deploy_aspect(fact.source)
                if deployed:
                    resp += f" {deployed}"
            return resp

        return "Je ne sais pas. Dis-moi d'abord ce qui s'est passé."

    def _can_do(self, text, action_word):
        """Vérifie si un sujet peut faire une action en cherchant
        si les fondateurs de l'action sont satisfaits dans les faits."""
        # Trouver le sujet
        question_subject = None
        for pron, entity in self.pronouns.items():
            if pron in text.lower():
                question_subject = entity.lower()
                break
        if not question_subject:
            noms, _ = self.extract_entities(text)
            if noms:
                question_subject = noms[0].lower()

        entry = self.entries.get(action_word)
        if not entry:
            return "Je ne connais pas cette action."

        subj_cap = question_subject.capitalize() if question_subject else "Quelqu'un"

        # Chercher dans les faits si le sujet a quelque chose qui rend l'action possible
        # Stratégie : l'action est possible si le sujet AVOIR qqchose,
        # ou POUVOIR DONNER, ou tout fait positif lié aux fondateurs de l'action
        fondateurs = set()
        for f in ("fondateur1", "fondateur2"):
            v = entry.get(f, "").strip()
            if v:
                fondateurs.add(v)

        # Chercher des faits qui soutiennent la capacité
        supporting = []
        for fact in self.facts:
            if question_subject and fact.sujet != question_subject:
                continue
            if fact.neg:
                continue
            # Le fait est-il lié à un fondateur de l'action ?
            if fact.predicat in fondateurs:
                supporting.append(fact)
            # Ou le fait contient-il AVOIR/POUVOIR DONNER ?
            if fact.predicat in ("AVOIR", "POUVOIR DONNER", "PRENDRE"):
                supporting.append(fact)

        if supporting:
            reasons = []
            for fact in supporting[:2]:  # max 2 raisons
                r = self._conjugate(fact.predicat, fact.sujet, fact.neg)
                if fact.objet:
                    r += f" {self._article(fact.objet)}"
                reasons.append(r.strip())
            return f"Oui. {subj_cap} peut {action_word.lower()}, car {', '.join(reasons)}."
        else:
            return f"Non. {subj_cap} ne peut pas {action_word.lower()}."


# =====================================================================
# INTERFACE
# =====================================================================

def main():
    path = DEFAULT_DICT
    if "--json" in sys.argv:
        idx = sys.argv.index("--json")
        if idx + 1 < len(sys.argv):
            path = Path(sys.argv[idx + 1])

    engine = TBSInference(path)

    print()
    print("  ┌──────────────────────────────────────────┐")
    print("  │     TBS Chatbot — raisonnement lexical    │")
    print("  └──────────────────────────────────────────┘")
    print(f"  {len(engine.entries)} mots chargés depuis {path.name}")
    print("  Parle-moi. Tape 'q' pour quitter.\n")

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

        response = engine.process(user)
        for line in response.split("\n"):
            print(f"  bot > {line}")
        print()


if __name__ == "__main__":
    main()
