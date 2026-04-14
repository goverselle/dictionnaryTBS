#!/usr/bin/env python3
"""
Chatbot TBS — raisonne en français naturel à partir du dictionnaire TBS.

Architecture :
    - spaCy (fr_core_news_md) pour parsing et dépendances
    - mlconjug3 pour la conjugaison française
    - Base de faits temporelle (le plus récent fait foi pour les prédicats statifs)
    - Activation des aspects TBS + règle de transfert de propriété

Usage :
    python3 scripts/chat.py

Commandes meta :
    :facts    → affiche tous les faits
    :reset    → vide la base
    :debug    → active/désactive les traces
    :quit     → quitte
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict

import spacy
import mlconjug3

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"

# Base minimale de genres pour les prénoms français (proper nouns ont rarement
# une info de genre via spaCy morph).
PRENOMS_MASC = {
    "pierre", "paul", "luc", "marc", "jean", "jacques", "louis", "michel",
    "henri", "charles", "thomas", "hugo", "antoine", "françois", "nicolas",
    "alexandre", "julien", "david", "olivier", "simon", "bernard",
}
PRENOMS_FEM = {
    "marie", "anne", "julie", "sophie", "emma", "léa", "claire", "alice",
    "pauline", "camille", "chloé", "elena", "juliette", "laura", "lucie",
    "elise", "agnès", "hélène", "catherine", "isabelle", "caroline", "sarah",
}


def prenom_gender(name):
    low = name.strip().lower()
    if low in PRENOMS_MASC:
        return "masc"
    if low in PRENOMS_FEM:
        return "fem"
    return None

# =====================================================================
# STRUCTURES DE DONNÉES
# =====================================================================

@dataclass
class Entity:
    name: str
    gender: Optional[str] = None  # 'masc', 'fem'
    number: str = "sg"  # 'sg', 'pl'
    animate: bool = True

    def __hash__(self):
        return hash(self.name.lower())

    def __eq__(self, other):
        return isinstance(other, Entity) and self.name.lower() == other.name.lower()


@dataclass
class Fact:
    order: int
    predicate: str
    subject: Optional[str] = None
    obj: Optional[str] = None
    recipient: Optional[str] = None
    neg: bool = False
    source: Optional[str] = None  # verbe TBS qui a produit ce fait
    derived: bool = False

    def __repr__(self):
        neg = "NEG " if self.neg else ""
        parts = [p for p in (self.subject, f"{neg}{self.predicate}", self.obj, self.recipient) if p]
        src = f" (via {self.source})" if self.source else ""
        return f"[{self.order}] " + " ".join(parts) + src


# =====================================================================
# CHARGEMENT DU DICTIONNAIRE
# =====================================================================

def load_dict():
    with open(DICT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {e["headword"]: e for e in data}


def build_lemma_to_headword(entries: Dict[str, dict]) -> Dict[str, str]:
    """Map simple : lemme verbe/adjectif minuscule → headword du dict."""
    m = {}
    for hw in entries:
        # Heuristique : le premier mot minuscule du template ou du headword
        low = hw.lower().replace("'", "'")
        # On enlève les suffixes entre parenthèses et espaces
        m[low] = hw
        # Variantes courantes
        if low.endswith("er") or low.endswith("re") or low.endswith("ir"):
            m[low] = hw
    return m


# =====================================================================
# PARSING DES TEMPLATES SYNTAXIQUES
# =====================================================================

ROLE_VARS = {"X", "Y", "Z", "W"}

# Quantifieurs reconnus dans le parser. Ils deviennent partie intégrante
# du prédicat composé (ex. AVOIR BEAUCOUP), conformément à l'architecture
# TBS qui les traite comme des mots comme les autres.
QUANTIFIEURS = {
    "beaucoup": "BEAUCOUP",
    "peu": "PEU",
    "rien": "RIEN",
    "tout": "TOUT",
    "énormément": "BEAUCOUP",
    "plein": "BEAUCOUP",
}


def parse_template(template: str, headword: str) -> Dict[str, str]:
    """
    Extrait le rôle syntaxique de chaque variable depuis le template_syntaxique.

    Ex: 'X ACHETER Y À Z' → {'X': 'nsubj', 'Y': 'obj', 'Z': 'obl_à'}
        'Y ÊTRE BEAU'     → {'Y': 'nsubj'}

    Règles simples :
        - la variable avant le verbe (ou HW) = nsubj
        - la première après = obj
        - après « À » / « à » = obl_à
        - après « DE » / « de » = obl_de
        - après « AVEC » = obl_avec
    """
    if not template:
        return {}
    tokens = template.split()
    mapping = {}
    i = 0
    verb_seen = False
    # On considère "verbe" le premier token qui n'est pas une variable
    while i < len(tokens):
        t = tokens[i]
        if t in ROLE_VARS and not verb_seen:
            mapping[t] = "nsubj"
        elif t.upper() in {"À", "A"} and i + 1 < len(tokens) and tokens[i + 1] in ROLE_VARS:
            mapping[tokens[i + 1]] = "obl_à"
            i += 1
        elif t.upper() == "DE" and i + 1 < len(tokens) and tokens[i + 1] in ROLE_VARS:
            mapping[tokens[i + 1]] = "obl_de"
            i += 1
        elif t.upper() == "AVEC" and i + 1 < len(tokens) and tokens[i + 1] in ROLE_VARS:
            mapping[tokens[i + 1]] = "obl_avec"
            i += 1
        elif t in ROLE_VARS and verb_seen:
            if t not in mapping:
                mapping[t] = "obj"
        else:
            # Token verbe ou adjectif
            verb_seen = True
        i += 1
    return mapping


# =====================================================================
# PARSING DES ASPECTS
# =====================================================================

def parse_quasibloc(qb: str):
    """Parse un quasi-bloc ``A (B)`` en ``(seg_left, seg_right)``.
    Retourne ``None`` si le format ne match pas."""
    if not qb:
        return None
    qb = qb.replace("*", "").strip()
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", qb)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def parse_aspect(aspect: str):
    """Retourne (seg1_neg, seg1, conn, seg2_neg, seg2) ou None."""
    if not aspect:
        return None
    aspect = aspect.replace("*", "")  # astérisques TBS autour des args principaux
    aspect = re.sub(r"\s+", " ", aspect).strip()
    m = re.search(r"\s(DC|PT)\s", aspect)
    if not m:
        return None
    left = aspect[: m.start()].strip()
    right = aspect[m.end():].strip()
    conn = m.group(1)

    def strip_neg(s):
        s = s.strip()
        if s.startswith("NEG "):
            return True, s[4:].strip()
        m2 = re.match(r"^([XYZW])\s+NEG\s+(.*)$", s)
        if m2:
            return True, f"{m2.group(1)} {m2.group(2)}".strip()
        return False, s

    n1, s1 = strip_neg(left)
    n2, s2 = strip_neg(right)
    return n1, s1, conn, n2, s2


def extract_predicates(segment: str) -> List[tuple]:
    """
    Extrait les prédicats atomiques d'un segment.
    Ex: 'X PAYER À Z' → [('PAYER', 'X', None, 'Z')]
        'X AVOIR Y'   → [('AVOIR', 'X', 'Y', None)]
        'PERF (X AVOIR Y)' → [('AVOIR', 'X', 'Y', None, True)] (perf=True)
        'Y ÊTRE CHER' → [('CHER', 'Y', None, None, False)] (copule supprimée)
    Retourne liste de (predicate, subject_var, obj_var, recipient_var, perf)
    """
    out = []
    perf = False
    seg = segment.strip()
    m = re.match(r"^PERF\s*\((.*)\)\s*$", seg)
    if m:
        perf = True
        seg = m.group(1).strip()

    tokens = seg.split()
    if not tokens:
        return out

    # Recherche du prédicat (premier mot majuscule non-variable)
    i = 0
    subj = None
    # Premier token : souvent une variable = sujet
    if tokens[0] in ROLE_VARS:
        subj = tokens[0]
        i = 1

    # Collecte du prédicat (peut être multi-mots : "POUVOIR ATTEINDRE")
    pred_parts = []
    while i < len(tokens) and tokens[i] not in ROLE_VARS and tokens[i].upper() not in {"À", "DE", "AVEC"}:
        pred_parts.append(tokens[i])
        i += 1
    # Supprimer le ÊTRE initial (copule) pour aligner avec le nom du
    # headword : « ÊTRE CHER » → « CHER », « ÊTRE MALADE » → « MALADE ».
    if pred_parts and pred_parts[0] == "ÊTRE" and len(pred_parts) > 1:
        pred_parts = pred_parts[1:]
    predicate = " ".join(pred_parts) if pred_parts else ""

    # Reste : objet direct, objet indirect (À), etc.
    obj = None
    recipient = None
    while i < len(tokens):
        t = tokens[i]
        if t.upper() == "À" and i + 1 < len(tokens) and tokens[i + 1] in ROLE_VARS:
            recipient = tokens[i + 1]
            i += 2
        elif t in ROLE_VARS:
            if obj is None:
                obj = t
            i += 1
        else:
            i += 1

    if predicate:
        out.append((predicate, subj, obj, recipient, perf))
    return out


# =====================================================================
# MOTEUR
# =====================================================================

class TBSChat:
    def __init__(self):
        print("Chargement de spaCy (transformer)…")
        self.nlp = spacy.load("fr_dep_news_trf")
        print("Chargement du dictionnaire TBS…")
        self.entries = load_dict()
        self.lemma2hw = build_lemma_to_headword(self.entries)
        print("Chargement du conjugueur…")
        self.conj = mlconjug3.Conjugator(language="fr")

        self.facts: List[Fact] = []
        self.entities: Dict[str, Entity] = {}
        self.order = 0
        self.debug = False
        # Raison dernière : fait lexical ayant justifié la dernière
        # dérivation réussie de ``_prove``. Utilisé pour générer des
        # explications « parce que … ».
        self._last_reason: Optional[Fact] = None
        print(f"Prêt. {len(self.entries)} mots chargés.\n")

    # -----------------------------------------------------------------
    # Gestion des entités
    # -----------------------------------------------------------------
    def get_entity(self, name: str, gender: Optional[str] = None, animate: bool = True) -> Entity:
        key = name.strip()
        if key.lower() in self.entities:
            return self.entities[key.lower()]
        e = Entity(name=key, gender=gender, animate=animate)
        self.entities[key.lower()] = e
        return e

    def resolve_pronoun(self, pron: str, gender: Optional[str] = None) -> Optional[str]:
        """Retourne le nom de la dernière entité compatible mentionnée."""
        wanted_gender = None
        if pron in {"il", "lui", "le"}:
            wanted_gender = "masc"
        elif pron in {"elle", "la"}:
            wanted_gender = "fem"
        if gender:
            wanted_gender = gender

        # Parcours inverse des faits pour trouver la dernière mention.
        # On ignore le placeholder « on » (indéfini animé créé quand un
        # complément oblique est omis) : il ne doit jamais être la cible
        # d'une résolution de pronom.
        for f in reversed(self.facts):
            for candidate in (f.subject, f.obj, f.recipient):
                if not candidate:
                    continue
                if candidate.lower() == "on":
                    continue
                e = self.entities.get(candidate.lower())
                if not e:
                    continue
                if wanted_gender and e.gender and e.gender != wanted_gender:
                    continue
                if e.animate:
                    return candidate
        return None

    # -----------------------------------------------------------------
    # Extraction d'une phrase parsée
    # -----------------------------------------------------------------
    def extract_svo(self, sent):
        """
        Extrait (sujet, verbe_lemme, objet_direct, objet_à, neg, tense, headword, modal).
        Retourne un dict ou None.
        """
        # Cas spécial : question ouverte « Comment est X ? » — spaCy parse
        # mal et le root peut être « comment ». On détecte le pattern
        # avant toute chose.
        tokens = list(sent)
        has_comment = any(t.lemma_.lower() == "comment" for t in tokens)
        if has_comment:
            # Chercher le nom propre ou pronom sujet
            subj = None
            for t in tokens:
                if t.pos_ == "PROPN":
                    subj = t.text
                    break
                if t.pos_ == "PRON" and t.lemma_.lower() in {"il", "elle"}:
                    subj = self.resolve_pronoun(t.lemma_.lower()) or t.text
                    break
            return {
                "subject": subj,
                "verb_lemma": "être",
                "object": None,
                "recipient": None,
                "neg": False,
                "tense": "present",
                "headword": None,
                "root": None,
                "is_adj": False,
                "modal": None,
                "wh_slot": None,
                "quantifier": None,
                "is_comment_question": True,
            }

        root = None
        for tok in sent:
            if tok.dep_ == "ROOT":
                root = tok
                break
        if root is None:
            return None

        # Cas modal : « Marie peut vendre une pomme » → root=peut, xcomp=vendre
        # POUVOIR / DEVOIR : on déroule le xcomp et on traite comme
        # capacité / obligation (modal handling dans _answer).
        # VOULOIR : on garde VOULOIR comme verbe principal MAIS on
        # récupère l'objet du xcomp comme objet de vouloir — le désir
        # porte sur l'objet final (« veut acheter une voiture » = veut
        # la voiture).
        modal = None
        subj_anchor = root
        verb_node = root
        UNWRAP_MODALS = {"pouvoir", "devoir"}
        root_lemma = root.lemma_.lower()
        if root_lemma in UNWRAP_MODALS:
            xcomp = next((c for c in root.children if c.dep_ == "xcomp" and c.pos_ == "VERB"), None)
            if xcomp is not None:
                modal = root_lemma
                verb_node = xcomp
        elif root_lemma == "vouloir":
            xcomp = next((c for c in root.children if c.dep_ == "xcomp" and c.pos_ == "VERB"), None)
            if xcomp is not None:
                # « Pierre veut acheter une voiture » : le désir porte sur
                # l'action spécifique (acheter), pas juste sur l'objet.
                # On construit un prédicat composé « VOULOIR ACHETER » et
                # on garde la voiture comme objet du composé.
                self._vouloir_xcomp = xcomp
            else:
                self._vouloir_xcomp = None
        else:
            self._vouloir_xcomp = None

        verb_lemma = verb_node.lemma_.lower()
        pos = verb_node.pos_
        # Copule adjectivale : ROOT est l'adjectif (ex. "Pierre est prudent")
        is_adj_copula = False
        if pos == "ADJ":
            is_adj_copula = True

        # Résolution headword
        headword = None
        # Essais de candidats : lemme fourni par spaCy, texte brut, et
        # variantes inflectionnelles (-er, -ir, -re).
        candidates = [verb_lemma, verb_node.text.lower()]
        for base in list(candidates):
            for suf_to_remove, suf_to_add in (
                ("e", "er"), ("es", "er"), ("ent", "er"), ("ons", "er"),
                ("ez", "er"), ("é", "er"), ("is", "ir"), ("it", "ir"),
                ("issent", "ir"), ("s", "re"), ("t", "re"),
            ):
                if base.endswith(suf_to_remove):
                    root = base[: -len(suf_to_remove)]
                    candidates.append(root + suf_to_add)
            # Verbes -er via simple ajout sans retrait (pour lemmes
            # tronqués comme « prêt » → « prêter »)
            candidates.append(base + "er")
        for cand in candidates:
            if cand in self.lemma2hw:
                headword = self.lemma2hw[cand]
                verb_lemma = cand
                break
            if cand.upper() in self.entries:
                headword = cand.upper()
                verb_lemma = cand
                break

        # Sujet : rattaché au modal si présent, sinon au verbe
        subj_text = None
        wh_slot = None  # 'subject' / 'object' / 'recipient' pour wh-questions
        for child in subj_anchor.children:
            if child.dep_ in {"nsubj", "nsubj:pass"}:
                if child.lemma_.lower() == "qui":
                    wh_slot = "subject"
                else:
                    subj_text = self._span_text(child)
                break

        # Objet direct & obl (rattachés au verbe principal)
        obj_text = None
        recipient_text = None
        quantifier = None  # BEAUCOUP / PEU / RIEN / TOUT si détecté

        # Cas « veut acheter une voiture » : on construit le composé
        # « VOULOIR ACHETER » et on récupère l'objet de acheter.
        vouloir_xcomp = getattr(self, '_vouloir_xcomp', None)
        compound_vouloir = None
        if vouloir_xcomp is not None:
            inner_verb = vouloir_xcomp.lemma_.upper()
            compound_vouloir = f"VOULOIR {inner_verb}"
            for c in vouloir_xcomp.children:
                if c.dep_ == "obj":
                    obj_text = self._span_text(c)
                    break
            self._vouloir_xcomp = None

        for child in verb_node.children:
            if child.dep_ == "obj":
                if child.lemma_.lower() in {"que", "quoi"}:
                    wh_slot = wh_slot or "object"
                elif child.lemma_.lower() in QUANTIFIEURS:
                    # Pattern « beaucoup de X » : obj=beaucoup,
                    # obl:arg=X attaché via « de ». Le vrai objet est X,
                    # le prédicat devient « <VERBE> <QUANTIFIEUR> ».
                    quantifier = QUANTIFIEURS[child.lemma_.lower()]
                    for sub in child.children:
                        if sub.dep_ in {"obl:arg", "nmod"} and any(
                            s.dep_ == "case" and s.text.lower() == "de"
                            for s in sub.children
                        ):
                            obj_text = self._span_text(sub)
                            break
                else:
                    obj_text = self._span_text(child)
            elif child.dep_ in {"obl:arg", "obl", "obl:mod"}:
                has_a = any(
                    sub.dep_ == "case" and sub.text.lower() in {"à", "au", "aux"}
                    for sub in child.children
                )
                if has_a:
                    if child.lemma_.lower() == "qui":
                        wh_slot = wh_slot or "recipient"
                    else:
                        recipient_text = self._span_text(child)

        # Négation
        neg = any(c.dep_ == "advmod" and c.lemma_.lower() in {"ne", "pas", "plus"} for c in subj_anchor.children)

        # Temps
        tense = "present"
        has_aux_avoir = any(c.dep_ == "aux:tense" and c.lemma_ == "avoir" for c in subj_anchor.children)
        has_aux_être = any(c.dep_ == "aux:tense" and c.lemma_ == "être" for c in subj_anchor.children)
        if has_aux_avoir or has_aux_être:
            tense = "past"
        if subj_anchor.morph.get("Tense") == ["Fut"]:
            tense = "future"

        # Si un quantifieur a été détecté, enrichir le prédicat composé
        if quantifier:
            compound_hw = f"{verb_lemma.upper()} {quantifier}"
            if compound_hw in self.entries:
                headword = compound_hw
                verb_lemma = compound_hw.lower()

        # Si « veut + VERB » détecté, utiliser le prédicat composé
        if compound_vouloir:
            headword = compound_vouloir  # ex. "VOULOIR ACHETER"
            verb_lemma = compound_vouloir.lower()

        # Question ouverte « Comment est X ? » / « X est comment ? »
        is_comment_question = any(
            tok.lemma_.lower() == "comment" for tok in sent
        )

        return {
            "subject": subj_text,
            "verb_lemma": verb_lemma,
            "object": obj_text,
            "recipient": recipient_text,
            "neg": neg,
            "tense": tense,
            "headword": headword,
            "root": verb_node,
            "is_adj": is_adj_copula,
            "modal": modal,
            "wh_slot": wh_slot,
            "quantifier": quantifier,
            "is_comment_question": is_comment_question,
        }

    def _span_text(self, tok):
        """Retourne le texte d'un span nominal en incluant le noyau et enfants pertinents.
        Gère les pronoms en les résolvant."""
        txt = tok.text
        # Pronoms
        pron_map = {
            "il": ("il", "masc"), "elle": ("elle", "fem"),
            "lui": ("lui", "masc"), "le": ("le", "masc"),
            "la": ("la", "fem"),
        }
        low = txt.lower()
        if low in pron_map:
            resolved = self.resolve_pronoun(low)
            if resolved:
                return resolved
            return txt
        # Span noyau
        # Prendre le mot tête, sans articles
        return tok.text if tok.pos_ in {"PROPN"} else self._noun_phrase(tok)

    def _noun_phrase(self, tok):
        """Retourne le lemme du noyau nominal, en unifiant les possessifs avec le
        même nom mentionné récemment (ex. 'sa voiture' → 'voiture' si déjà connu)."""
        base = tok.lemma_
        # Enregistrer le genre depuis la morphologie spaCy
        gender = tok.morph.get("Gender")
        if gender:
            g = "masc" if gender[0] == "Masc" else "fem"
            self.get_entity(base, gender=g, animate=False)
        has_poss = any(
            c.dep_ == "det" and c.lemma_.lower() in {"son", "sa", "ses", "leur", "leurs"}
            for c in tok.children
        )
        if has_poss:
            # Unifier avec un nom identique déjà mentionné
            for f in reversed(self.facts):
                for val in (f.obj, f.subject, f.recipient):
                    if val and val.lower() == base.lower():
                        return val
        return base

    # -----------------------------------------------------------------
    # Activation des faits depuis un headword
    # -----------------------------------------------------------------
    def activate(self, headword: str, binding: Dict[str, str],
                 neg_stmt: bool = False):
        """Stocke le fait lexical complet pour ``headword`` avec les variables liées.

        On ne décompose jamais l'aspect : seule la phrase lexicale top-level
        est mise en base. Les implications (transgressions PT, transfert de
        possession, propagation, unicité) sont résolues dynamiquement par le
        prover au moment d'une requête, en rouvrant l'aspect avec le contexte
        utile.
        """
        entry = self.entries.get(headword)
        if not entry:
            return
        template = entry.get("template_syntaxique", "")
        mapping = parse_template(template, headword)
        direct_subj = direct_obj = direct_recip = None
        for var, role in mapping.items():
            val = binding.get(var)
            if val is None:
                continue
            if role == "nsubj":
                direct_subj = val
            elif role == "obj":
                direct_obj = val
            elif role == "obl_à":
                direct_recip = val
        if direct_subj:
            self.add_fact(
                headword,
                direct_subj,
                direct_obj,
                direct_recip,
                neg=neg_stmt,
                source=headword,
                derived=False,
            )

    # -----------------------------------------------------------------
    # Base de faits
    # -----------------------------------------------------------------
    def add_fact(self, pred, subj, obj=None, recip=None, neg=False, source=None, derived=False, perf=False):
        """Ajoute un fait brut à la base. Aucun fait dérivé n'est généré ici :
        la décomposition des aspects et les règles (transfert de possession,
        unicité, disposition) se font dynamiquement dans ``_prove``."""
        if perf:
            # PERF : l'état est passé, pas actuel. On n'ajoute pas.
            return
        self.order += 1
        f = Fact(
            order=self.order,
            predicate=pred,
            subject=subj,
            obj=obj,
            recipient=recip,
            neg=neg,
            source=source,
            derived=derived,
        )
        self.facts.append(f)
        if self.debug:
            print(f"  + {f}")

    # =================================================================
    # Scan temporel inversé — cœur du prover dynamique
    # =================================================================

    def _scan_facts_for(self, pred, subject, obj, negated):
        """Parcourt les faits en ordre temporel inversé et retourne :
            - True  si un fait affirme (pred, subject, obj) avec la
                    polarité demandée,
            - False si un fait affirme la polarité inverse,
            - None  si aucun fait ne se prononce sur la requête.

        Le premier fait rencontré qui se prononce gagne. La valeur
        ``self._last_reason`` est posée sur le fait racine (lexical) qui
        a fondé la dérivation, pour permettre à ``_append_because`` de
        générer une justification.

        Cas spécial AVOIR : on applique une règle d'unicité de possession
        en plus de la dérivation aspect-par-aspect. Concrètement, si un
        fait postérieur affirme qu'un autre sujet Z a (positivement)
        l'objet cherché, alors le sujet de la requête ne l'a plus.
        """
        # Cas spécial : AVOIR fait intervenir la règle d'unicité.
        # On cherche le dernier fait qui se prononce sur la possession
        # de l'objet ; le sujet qu'il identifie comme possesseur détermine
        # la réponse.
        if pred == "AVOIR" and obj is not None:
            verdict, reason = self._latest_possessor_verdict(subject, obj)
            if verdict is not None:
                if verdict == (not negated):
                    self._last_reason = reason
                return verdict == (not negated)

        for fact in reversed(self.facts):
            claim = self._fact_claim(fact, pred, subject, obj)
            if claim is None:
                continue
            claim_neg, source_fact = claim
            if claim_neg == negated:
                self._last_reason = source_fact
                return True
            return False
        return None

    def _latest_possessor_verdict(self, subject, obj):
        """Pour une requête ``AVOIR(subject, obj)``, détermine le dernier
        possesseur identifié par un fait de la base. Retourne
        ``(True/False, reason_fact)`` ou ``(None, None)``.

        On parcourt les faits en ordre temporel inversé et on prend le
        premier qui affirme une possession (positive ou négative) sur
        ``obj``. Ce fait peut être :
          - un AVOIR direct (stocké depuis « X a Y »),
          - un AVOIR dérivé d'un aspect lexical (ACHETER, DONNER,
            PRENDRE, VOLER, EMPRUNTER…), via expansion récursive.
        """
        if subject is None or obj is None:
            return None, None
        # Pour que l'unicité s'applique, il faut que le sujet cherché
        # ait été concrètement impliqué dans une revendication de
        # possession de l'objet (direct ou via un aspect lexical). Sinon
        # « Pierre a une pomme ? » après « Marie a une pomme » doit
        # retourner « aucune information » plutôt que « Non » par
        # application erronée de l'unicité.
        subject_has_history = False
        for fact in self.facts:
            if self._fact_mentions_possession(fact, subject, obj):
                subject_has_history = True
                break

        for fact in reversed(self.facts):
            possessor_info = self._fact_possessor_of(fact, obj)
            if possessor_info is None:
                continue
            holder, positive, source_fact = possessor_info
            if holder is None:
                if source_fact.subject and source_fact.subject.lower() == subject.lower():
                    return False, source_fact
                continue
            if holder.lower() == subject.lower():
                return positive, source_fact
            if positive and subject_has_history:
                # Un autre sujet a l'objet → unicité : le sujet cherché
                # ne l'a plus (seulement s'il avait été possesseur).
                return False, source_fact
        return None, None

    def _fact_mentions_possession(self, fact, subject, obj):
        """Vrai si ``fact`` a pu établir à un moment donné que ``subject``
        possédait ``obj`` (positivement ou négativement). Utilisé pour
        décider si l'unicité s'applique."""
        if fact.subject is None or fact.subject.lower() != subject.lower():
            return False
        if fact.predicate == "AVOIR":
            return fact.obj is not None and fact.obj.lower() == obj.lower()
        # Fait lexical : l'aspect parle-t-il d'AVOIR Y avec Y lié à obj ?
        entry = self.entries.get(fact.predicate)
        if not entry:
            return False
        binding = self._binding_from_fact(entry, fact)
        for item in entry.get("signification", {}).get("interne", []):
            parsed = parse_aspect(item.get("aspect", ""))
            if not parsed:
                continue
            _n1, seg1, _conn, _n2, seg2 = parsed
            for (p, sv, ov, rv, _perf) in extract_predicates(seg1) + extract_predicates(seg2):
                if p == "AVOIR" and ov and binding.get(ov, "").lower() == obj.lower():
                    if binding.get(sv, "").lower() == subject.lower():
                        return True
        return False

    def _fact_possessor_of(self, fact, obj):
        """Analyse ``fact`` pour déterminer qui est, après lui, possesseur
        de ``obj``. Retourne ``(holder_name, positive_bool, source_fact)``
        ou ``None`` si le fait ne dit rien sur cette possession.

        Pour un fait lexical (ex. DONNER(Marie, pomme, Pierre)), on
        instancie l'aspect et on cherche le claim positif courant (non-PERF)
        ``AVOIR Y`` dont Y se lie à ``obj``. Pour un fait AVOIR direct,
        c'est immédiat.
        """
        # Fait direct AVOIR
        if fact.predicate == "AVOIR":
            if fact.obj and fact.obj.lower() == obj.lower():
                if fact.neg:
                    return (fact.subject, False, fact)
                return (fact.subject, True, fact)
            return None

        # Fait lexical : expanser les aspects
        if fact.predicate not in self.entries:
            return None
        return self._expand_for_possession(fact, obj, depth=0, visited=set())

    def _expand_for_possession(self, fact, obj, depth, visited):
        """Recursivement étend un fait lexical pour trouver le possesseur
        courant de ``obj``. Limite de profondeur pour éviter les boucles."""
        if depth > 3:
            return None
        key = (fact.predicate, fact.subject, fact.obj, fact.recipient)
        if key in visited:
            return None
        visited.add(key)

        entry = self.entries.get(fact.predicate)
        if not entry:
            return None
        binding = self._binding_from_fact(entry, fact)
        # On cherche parmi toutes les aspects la première qui parle de
        # AVOIR sur un Y lié à ``obj``.
        for item in entry.get("signification", {}).get("interne", []):
            parsed = parse_aspect(item.get("aspect", ""))
            if not parsed:
                continue
            n1, seg1, conn, n2, seg2 = parsed
            preds1 = extract_predicates(seg1)
            preds2 = extract_predicates(seg2)
            # Détection de transfert PERF(AVOIR) + AVOIR : ancien
            # possesseur perd, nouveau possesseur gagne. On identifie
            # les deux sujets et on retourne le verdict au moment opportun.
            perf_avoir_claim = None
            now_avoir_claim = None
            for segment_preds, seg_neg in ((preds1, n1), (preds2, n2)):
                for (p, sv, ov, rv, perf) in segment_preds:
                    if p != "AVOIR":
                        continue
                    y_val = binding.get(ov) if ov else None
                    x_val = binding.get(sv) if sv else None
                    if y_val is None or y_val.lower() != obj.lower():
                        continue
                    effective_neg = seg_neg != fact.neg
                    if perf:
                        perf_avoir_claim = (x_val, not effective_neg)
                    else:
                        now_avoir_claim = (x_val, not effective_neg)
            if now_avoir_claim and perf_avoir_claim and now_avoir_claim[0] != perf_avoir_claim[0]:
                # Transfert : retourne le possesseur courant.
                return (now_avoir_claim[0], now_avoir_claim[1], fact)
            if now_avoir_claim:
                return (now_avoir_claim[0], now_avoir_claim[1], fact)
            if perf_avoir_claim and not now_avoir_claim:
                # État passé sans contrepartie : rien à dire du présent.
                pass

            # Recursion sur les sous-prédicats lexicaux (ex. VOLER → PRENDRE,
            # PRÊTER → DONNER → AVOIR transfer).
            for segment_preds, seg_neg in ((preds1, n1), (preds2, n2)):
                for (p, sv, ov, rv, perf) in segment_preds:
                    if perf:
                        continue
                    if p not in self.entries or p == fact.predicate:
                        continue
                    s = binding.get(sv) if sv else None
                    o = binding.get(ov) if ov else None
                    r = binding.get(rv) if rv else None
                    if s is None:
                        continue
                    sub_neg = seg_neg != fact.neg
                    mock = Fact(
                        order=fact.order, predicate=p,
                        subject=s, obj=o, recipient=r,
                        neg=sub_neg, source=fact.predicate,
                    )
                    sub_result = self._expand_for_possession(mock, obj, depth + 1, visited)
                    if sub_result is not None:
                        holder, positive, _src = sub_result
                        return (holder, positive, fact)
        return None

    def _fact_claim(self, fact, query_pred, query_subj, query_obj,
                    depth=0, visited=None):
        """Retourne ``(claim_neg, source_fact)`` si ``fact`` se prononce
        sur ``(query_pred, query_subj, query_obj)``, sinon ``None``.

        ``claim_neg`` est ``True`` si le fait affirme la polarité négative,
        ``False`` pour la polarité positive. ``source_fact`` pointe vers
        le fait racine (top-level) à attribuer comme cause.

        Fait direct : match exact du prédicat et des arguments.
        Fait lexical : instancie l'aspect avec le binding du fait et
        cherche, dans les segments non-PERF, un atome correspondant à
        la requête.  Si le prédicat d'un segment est lui-même lexical
        (ex. PRENDRE dans VOLER), on récurse sur un fait synthétique.
        """
        if visited is None:
            visited = set()
        if depth > 3:
            return None

        # Cas direct
        if fact.predicate not in self.entries:
            if fact.predicate != query_pred:
                return None
            if query_subj and (not fact.subject or fact.subject.lower() != query_subj.lower()):
                return None
            if query_obj and (not fact.obj or fact.obj.lower() != query_obj.lower()):
                return None
            return (fact.neg, fact)

        key = (fact.predicate, fact.subject, fact.obj, fact.recipient, query_pred,
               query_subj, query_obj)
        if key in visited:
            return None
        visited.add(key)

        # Cas lexical : ouvrir l'aspect et chercher un atome matchant.
        entry = self.entries[fact.predicate]
        binding = self._binding_from_fact(entry, fact)

        # Si la requête porte directement sur le prédicat racine
        # (ex. query VOLER Paul voiture), match direct.
        if fact.predicate == query_pred:
            s = fact.subject
            o = fact.obj
            if query_subj and (not s or s.lower() != query_subj.lower()):
                pass
            elif query_obj and (not o or o.lower() != query_obj.lower()):
                pass
            else:
                return (fact.neg, fact)

        for item in entry.get("signification", {}).get("interne", []):
            parsed = parse_aspect(item.get("aspect", ""))
            if not parsed:
                continue
            n1, seg1, conn, n2, seg2 = parsed
            for segment_preds, seg_neg in (
                (extract_predicates(seg1), n1),
                (extract_predicates(seg2), n2),
            ):
                for (p, sv, ov, rv, perf) in segment_preds:
                    if perf:
                        continue
                    s = binding.get(sv) if sv else None
                    o = binding.get(ov) if ov else None
                    r = binding.get(rv) if rv else None
                    effective_neg = seg_neg != fact.neg
                    # Match direct de l'atome sur la requête
                    if p == query_pred:
                        if query_subj and (not s or s.lower() != query_subj.lower()):
                            pass
                        elif query_obj and o and o.lower() != query_obj.lower():
                            pass
                        elif query_subj and s is None:
                            # Sujet non lié : on peut néanmoins valider si
                            # la requête ne fixe pas de sujet, mais ici
                            # elle en fixe un donc on ne matche pas.
                            pass
                        else:
                            return (effective_neg, fact)
                    # Recursion sur les sous-prédicats lexicaux
                    if p in self.entries and p != fact.predicate and s is not None:
                        mock = Fact(
                            order=fact.order, predicate=p,
                            subject=s, obj=o, recipient=r,
                            neg=effective_neg, source=fact.predicate,
                        )
                        sub = self._fact_claim(
                            mock, query_pred, query_subj, query_obj,
                            depth + 1, visited,
                        )
                        if sub is not None:
                            # Remplacer la source par le fait top-level
                            return (sub[0], fact)
        return None

    # =================================================================
    # Prover multi-sauts avec logique du carré (contrapositive)
    # =================================================================

    def _prove(self, pred, subject=None, obj=None, negated=False,
               depth=0, visited=None):
        """Essaie de démontrer le fait `(pred, subject, obj, negated)`.

        Retourne :
            True  si prouvé (fait connu ou dérivable),
            False si la polarité inverse est prouvée,
            None  si inconnu.

        Stratégie :
            1. Lookup direct dans la base de faits
            2. Backward chaining sur les aspects DC de toutes les entrées :
               pour prouver le côté droit d'une règle ``Lft DC Rgt``, il
               suffit de prouver le côté gauche. La contrapositive est
               intégrée via la gestion des polarités (XOR des NEGs).
        """
        if depth > 3:
            return None
        if visited is None:
            visited = set()
        key = (pred, subject and subject.lower(), obj and obj.lower(), negated)
        if key in visited:
            return None
        visited.add(key)

        # 1. Parcours temporel inversé des faits.
        #
        # Chaque fait stocké est lexical (top-level). Pour chaque fait, on
        # rouvre son aspect à la volée et on calcule ce qu'il affirme à
        # propos de la requête (pred, subject, obj). Le premier fait qui a
        # quelque chose à dire gagne — c'est la règle de temporalité : la
        # mention la plus récente écrase les précédentes. Cela encode
        # naturellement :
        #   - unicité de possession (la dernière affirmation d'AVOIR sur
        #     un objet fixe qui l'a désormais),
        #   - transfert de possession (PERF(X AVOIR Y) DC Z AVOIR Y),
        #   - écrasement statif (OUBLIER après APPRENDRE).
        scan_result = self._scan_facts_for(pred, subject, obj, negated)
        if scan_result is not None:
            return scan_result

        # Les composés comme VOULOIR ACHETER ne matchent PAS bare VOULOIR
        # (le désir porte sur l'action spécifique, pas abstraitement).
        # MAIS les dérivations VOULOIR AVOIR / VOULOIR FAIRE (générées
        # au stockage depuis VOULOIR ACHETER) peuvent elles-mêmes
        # satisfaire une recherche bare VOULOIR, car AVOIR est l'état
        # meta et FAIRE l'action meta.
        if subject and pred == "VOULOIR" and not negated:
            for fact in reversed(self.facts):
                if fact.neg:
                    continue
                if not fact.subject or fact.subject.lower() != subject.lower():
                    continue
                if fact.predicate not in {"VOULOIR AVOIR", "VOULOIR FAIRE"}:
                    continue
                if obj and fact.obj and fact.obj.lower() != obj.lower():
                    continue
                self._last_reason = fact
                return True

        # 1b. Fallback dispositionnel
        if subject:
            for fact in reversed(self.facts):
                if fact.predicate != pred:
                    continue
                if not fact.subject or fact.subject.lower() != subject.lower():
                    continue
                if fact.obj is not None:
                    continue
                if fact.neg == negated:
                    self._last_reason = fact
                return fact.neg == negated

        # 1b-bis. Décomposition dynamique d'une phrase lexicale adjective.
        if subject:
            for fact in reversed(self.facts):
                if not fact.subject or fact.subject.lower() != subject.lower():
                    continue
                if fact.predicate not in self.entries:
                    continue
                entry = self.entries[fact.predicate]
                for item in entry.get("signification", {}).get("interne", []):
                    parsed = parse_aspect(item.get("aspect", ""))
                    if not parsed:
                        continue
                    n1_a, seg1_a, conn_a, n2_a, seg2_a = parsed
                    if conn_a != "PT":
                        continue
                    for segment_preds, segment_neg in (
                        (extract_predicates(seg1_a), n1_a),
                        (extract_predicates(seg2_a), n2_a),
                    ):
                        for (p, sv, ov, rv, _perf) in segment_preds:
                            if p != pred:
                                continue
                            if segment_neg == negated:
                                self._last_reason = fact
                                return True

        # 1b-ter. Généralisation vers FAIRE : tout verbe d'action
        # spécifique asserté pour un sujet implique que ce sujet FAIT
        # quelque chose. Quand on cherche à prouver ``FAIRE(subject, *)``,
        # on accepte n'importe quel fait d'action pour ce sujet.
        # Symétriquement pour NEG FAIRE via la règle méta.
        if subject and pred == "FAIRE" and not negated:
            for fact in reversed(self.facts):
                if fact.neg:
                    continue
                if not fact.subject or fact.subject.lower() != subject.lower():
                    continue
                if fact.predicate in {"AVOIR", "SAVOIR", "ÊTRE",
                                      "POUVOIR", "VOULOIR", "DEVOIR", "FAIRE"}:
                    continue
                # Seul un verbe connu du dictionnaire est accepté comme
                # preuve d'une action (pas de fallback sur les verbes
                # inconnus : ils ne sont pas stockés).
                if fact.predicate not in self.entries:
                    continue
                template = self.entries[fact.predicate].get("template_syntaxique", "") or ""
                if "ÊTRE" in template:
                    continue
                self._last_reason = fact
                return True

        # 1c. Propagation dispositionnelle restreinte : une disposition
        # générique `NEG P` ne se propage à une action V que s'il y a un
        # rapport sémantique entre V et P. Concrètement : P doit apparaître
        # dans l'aspect de V. Ex. :
        #   - AVARE stocke NEG DONNER (générique)
        #     → propagation vers PAYER (aspect contient DONNER) ✓
        #     → PAS vers SAVOIR (aspect ne contient pas DONNER)
        #   - IRRESPONSABLE stocke NEG FAIRE (générique)
        #     → propagation vers FACILE/OBTENIR (aspect contient FAIRE) ✓
        # Asymétrique : seules les dispositions NEG se propagent
        # (FAIRE générique ≠ faire cette chose-ci).
        if subject and negated and self._is_action_verb(pred):
            entry = self.entries[pred]
            target_sub_preds = set()
            for item in entry.get("signification", {}).get("interne", []):
                parsed = parse_aspect(item.get("aspect", ""))
                if not parsed:
                    continue
                _, seg1, _, _, seg2 = parsed
                for (p, *_rest) in extract_predicates(seg1) + extract_predicates(seg2):
                    target_sub_preds.add(p)
            for sub_pred in target_sub_preds:
                if sub_pred == pred:
                    continue
                for fact in reversed(self.facts):
                    if fact.predicate != sub_pred:
                        continue
                    if not fact.subject or fact.subject.lower() != subject.lower():
                        continue
                    if fact.obj is not None:
                        continue
                    if fact.neg:
                        self._last_reason = fact
                        return True
                    break

        # 2. Quasi-blocs externes de toutes les entrées. Les quasi-blocs
        # (`A (B)`) sont des ponts argumentatifs entre prédicats : ils
        # s'appliquent comme règles doxales générales, indépendamment
        # du headword qui les porte. On parcourt donc chaque entrée et
        # chaque quasi-bloc externe.
        for qb_entry_hw, qb_entry in self.entries.items():
            ext_list = qb_entry.get("signification", {}).get("externe", [])
            for item in ext_list:
                qb = item.get("quasibloc", "")
                parsed_qb = parse_quasibloc(qb)
                if not parsed_qb:
                    continue
                left, right = parsed_qb

                def _strip_neg(s):
                    s = s.strip()
                    if s.startswith("NEG "):
                        return True, s[4:].strip()
                    m2 = re.match(r"^([XYZW])\s+NEG\s+(.*)$", s)
                    if m2:
                        return True, f"{m2.group(1)} {m2.group(2)}".strip()
                    return False, s
                qb_n1, qb_l = _strip_neg(left)
                qb_n2, qb_r = _strip_neg(right)
                if self._try_backward_rule(
                    pred, subject, obj, negated,
                    qb_l, qb_n1, qb_r, qb_n2, depth, visited,
                ):
                    return True

        return None

    def _binding_from_fact(self, entry, fact):
        """À partir d'une entrée et d'un fait asserté, construit le binding
        des variables du template (X, Y, Z, W) vers les valeurs concrètes."""
        template = entry.get("template_syntaxique", "")
        mapping = parse_template(template, entry.get("headword", ""))
        binding = {}
        for var, role in mapping.items():
            if role == "nsubj" and fact.subject:
                binding[var] = fact.subject
            elif role == "obj" and fact.obj:
                binding[var] = fact.obj
            elif role == "obl_à" and fact.recipient:
                binding[var] = fact.recipient
        return binding

    def _try_backward_rule(self, pred, subject, obj, negated,
                           seg1, n1, seg2, n2, depth, visited):
        """Applique une règle TBS en backward.

        Règle : ``(NEG-si-n1 L) → (NEG-si-n2 R)``. On essaie deux directions :

        1. **Directe** — match du target dans Rgt : la règle conclut
           (pred) avec polarité ``n2``. Utile ssi ``n2 == negated``.
           Pour activer la règle, prouver Lft avec polarité ``n1``.

        2. **Contrapositive** — match du target dans Lft : par la
           contrapositive, ``¬(NEG-si-n2 R) → ¬(NEG-si-n1 L)``, ce qui
           conclut (pred) avec polarité ``not n1``. Utile ssi
           ``not n1 == negated``, soit ``n1 != negated``. Pour activer,
           prouver Rgt avec polarité ``not n2``.
        """
        preds_l = extract_predicates(seg1)
        preds_r = extract_predicates(seg2)

        # Direction 1 — match dans Rgt
        if n2 == negated:
            for (p, sv, ov, rv, _perf) in preds_r:
                if p != pred:
                    continue
                binding = {}
                if sv and subject:
                    binding[sv] = subject
                if ov and obj:
                    binding[ov] = obj
                if rv and subject and not sv:
                    binding[rv] = subject
                if self._prove_all(preds_l, binding, n1, depth, visited):
                    return True

        # Direction 2 — contrapositive, match dans Lft
        if n1 != negated:
            for (p, sv, ov, rv, _perf) in preds_l:
                if p != pred:
                    continue
                binding = {}
                if sv and subject:
                    binding[sv] = subject
                if ov and obj:
                    binding[ov] = obj
                if rv and subject and not sv:
                    binding[rv] = subject
                if self._prove_all(preds_r, binding, not n2, depth, visited):
                    return True
        return False

    _STATIVE_PREDICATES = {
        "AVOIR", "ÊTRE", "SAVOIR", "POUVOIR", "VOULOIR", "DEVOIR",
        "PENSER", "AIMER", "CROIRE", "DIRE", "VOIR",
    }

    def _is_action_verb(self, pred):
        """Retourne True si pred est un verbe d'action (spécialisation de FAIRE).
        Heuristique : c'est un headword du dictionnaire, pas un prédicat statif."""
        if pred in self._STATIVE_PREDICATES:
            return False
        return pred in self.entries

    def _prove_all(self, preds, binding, polarity_neg, depth, visited):
        """Essaie de prouver tous les prédicats d'un segment avec le binding donné."""
        for (p, sv, ov, rv, _perf) in preds:
            s = binding.get(sv) if sv else None
            o = binding.get(ov) if ov else None
            if not s:
                return False  # pas de sujet à interroger
            result = self._prove(p, subject=s, obj=o,
                                 negated=polarity_neg,
                                 depth=depth + 1, visited=visited)
            if result is not True:
                return False
        return True

    def search_all(self, pred, subject=None, obj=None, recipient=None):
        """Retourne tous les faits positifs matchant, en respectant l'écrasement
        temporel : pour chaque triplet (subject, object, recipient), on garde
        le statut le plus récent. Les faits dont le statut final est négatif
        sont écartés."""
        latest = {}  # clé → fact le plus récent
        for f in self.facts:
            if f.predicate != pred:
                continue
            if subject and (not f.subject or f.subject.lower() != subject.lower()):
                continue
            if obj and (not f.obj or f.obj.lower() != obj.lower()):
                continue
            if recipient and (not f.recipient or f.recipient.lower() != recipient.lower()):
                continue
            key = (
                f.subject.lower() if f.subject else None,
                f.obj.lower() if f.obj else None,
                f.recipient.lower() if f.recipient else None,
            )
            latest[key] = f  # l'itération étant linéaire, le dernier gagne
        # Ne retenir que les faits positifs à l'état final
        return [f for f in latest.values() if not f.neg]

    def search_latest(self, pred, subject=None, obj=None) -> Optional[Fact]:
        """Retourne le fait le plus récent matchant (sujet, prédicat, objet).
        Matching strict : si un critère est donné, le fait doit avoir cette valeur."""
        for f in reversed(self.facts):
            if f.predicate != pred:
                continue
            if subject:
                if not f.subject or f.subject.lower() != subject.lower():
                    continue
            if obj:
                if not f.obj or f.obj.lower() != obj.lower():
                    continue
            return f
        return None

    # -----------------------------------------------------------------
    # Traitement d'une entrée utilisateur
    # -----------------------------------------------------------------
    def process(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""

        # Commandes meta
        if text.startswith(":"):
            return self._meta(text)

        doc = self.nlp(text)

        # Détecter la présence d'une question ouverte « Comment est X ? »
        # et mettre de côté la dernière phrase qui la contient pour
        # qu'elle soit traitée après tous les énoncés factuels.
        sents = list(doc.sents)
        comment_sentences = []
        regular_sentences = []
        for idx, sent in enumerate(sents):
            if any(t.lemma_.lower() == "comment" for t in sent):
                # Vérifier si la phrase précédente est une copule
                # incomplète (« Pierre est ») que spaCy aurait
                # maladroitement séparée. Si oui, la retirer des
                # régulières : elle fait partie de cette question.
                if regular_sentences:
                    prev = regular_sentences[-1]
                    prev_text = prev.text.strip().rstrip(".")
                    if prev_text.split() and prev_text.split()[-1].lower() in {
                        "est", "était", "a", "avait", "sera", "serait"
                    }:
                        regular_sentences.pop()
                comment_sentences.append(sent)
            else:
                regular_sentences.append(sent)

        responses = []
        for sent in regular_sentences:
            is_question = "?" in sent.text
            svo = self.extract_svo(sent)
            if self.debug:
                print(f"  [svo] {svo}")
            if svo is None:
                continue

            # Enregistrer les entités présentes.
            # Pour les noms propres, on tente une détection de genre par prénom.
            for role in ("subject", "object", "recipient"):
                val = svo.get(role)
                if val and not val.startswith("_"):
                    g = prenom_gender(val)
                    self.get_entity(val, gender=g)

            if is_question:
                responses.append(self._answer(svo))
            else:
                msg = self._register_statement(svo)
                responses.append(msg if msg else "OK.")

        # Traiter les questions ouvertes « Comment est X ? » après
        # que tous les énoncés factuels précédents aient été digérés.
        for sent in comment_sentences:
            subj = None
            for t in sent:
                if t.pos_ == "PROPN":
                    subj = t.text
                    break
                if t.pos_ == "PRON" and t.lemma_.lower() in {"il", "elle"}:
                    subj = self.resolve_pronoun(t.lemma_.lower()) or t.text
                    break
            if subj is None:
                for t in doc:
                    if t.pos_ == "PROPN":
                        subj = t.text
                        break
            if subj:
                responses.append(self._answer_comment_question(subj))
            else:
                responses.append("De qui tu parles ?")

        return "\n".join(r for r in responses if r)

    def _register_statement(self, svo):
        """Enregistre une assertion dans la base de faits.
        Retourne ``None`` pour un ``OK.`` muet, ou un message si le
        mot est inconnu du dictionnaire TBS."""
        hw = svo["headword"]
        # Cas particulier : verbe "avoir" simple sans quantifieur
        if (svo["verb_lemma"] == "avoir"
                and svo.get("object")
                and not svo.get("quantifier")):
            self.add_fact("AVOIR", svo["subject"], svo["object"], None, neg=svo["neg"])
            return None

        # Idiome « coûter cher » / « coûter bon marché » : l'adverbe
        # adjectival attaché à coûter lexicalise l'adjectif CHER ou
        # BON MARCHÉ. On active directement l'adjectif sur le sujet.
        if svo["verb_lemma"] == "coûter" and svo.get("object"):
            obj_lemma = svo["object"].lower()
            if obj_lemma in {"cher", "chère"}:
                self.activate("CHER", {"Y": svo["subject"]}, neg_stmt=svo["neg"])
                return None
            if obj_lemma in {"bon marché", "bas"}:
                if "BON MARCHÉ" in self.entries:
                    self.activate("BON MARCHÉ", {"Y": svo["subject"]}, neg_stmt=svo["neg"])
                    return None
        if not hw:
            verb_lemma = svo.get("verb_lemma")
            if verb_lemma:
                return f"Le mot « {verb_lemma} » est inconnu du dictionnaire TBS."
            return None

        # Cas prédicat composé « VOULOIR <VERB> » construit à la volée
        # pour « veut acheter une voiture ». On stocke le composé et
        # on dérive sémantiquement :
        #   · VOULOIR FAIRE (si V est un verbe d'action) — le désir
        #     porte sur l'action abstraite
        #   · VOULOIR AVOIR Y (si V a `X AVOIR Y` dans son aspect) —
        #     le désir porte sur l'état final
        # Ainsi « vouloir acheter » ≡ vouloir faire + vouloir avoir,
        # mais PAS « vouloir » tout court.
        if hw.startswith("VOULOIR ") and hw not in self.entries:
            subj = svo["subject"]
            obj = svo.get("object")
            recip = svo.get("recipient")
            neg = svo["neg"]
            self.add_fact(hw, subj, obj, recip, neg=neg, source=hw)
            # Dérivation des deux sens
            inner_verb = hw.split(" ", 1)[1]  # ex. "ACHETER"
            inner_entry = self.entries.get(inner_verb)
            if inner_entry:
                template = inner_entry.get("template_syntaxique", "") or ""
                is_action = "ÊTRE" not in template
                if is_action:
                    # VOULOIR FAIRE (proforme de l'action)
                    self.add_fact("VOULOIR FAIRE", subj, obj, None,
                                  neg=neg, source=hw)
                # Chercher X AVOIR Y dans les aspects du verbe interne
                for item in inner_entry.get("signification", {}).get("interne", []):
                    parsed = parse_aspect(item.get("aspect", ""))
                    if not parsed:
                        continue
                    _, seg1, _, _, seg2 = parsed
                    for seg_preds in (extract_predicates(seg1), extract_predicates(seg2)):
                        for (p, sv, ov, rv, perf) in seg_preds:
                            if p == "AVOIR" and not perf:
                                self.add_fact("VOULOIR AVOIR", subj, obj, None,
                                              neg=neg, source=hw)
                                break
            return None
        # Construire binding via le template
        entry = self.entries[hw]
        template = entry.get("template_syntaxique", "")
        mapping = parse_template(template, hw)
        binding = {}
        used_indef = False
        for var, role in mapping.items():
            if role == "nsubj":
                binding[var] = svo.get("subject")
            elif role == "obj":
                binding[var] = svo.get("object")
            elif role == "obl_à":
                val = svo.get("recipient")
                if val is None:
                    val = "on"
                    used_indef = True
                binding[var] = val
        binding = {k: v for k, v in binding.items() if v is not None}
        if used_indef:
            self.get_entity("on", animate=True)

        self.activate(hw, binding, neg_stmt=svo["neg"])

    # Mapping lemme français → prédicat atomique TBS
    VERB_TO_PREDICATE = {
        "avoir": "AVOIR",
        "être": "ÊTRE",
        "savoir": "SAVOIR",
        "connaître": "SAVOIR",
        "faire": "FAIRE",
        "donner": "DONNER",
        "payer": "PAYER",
        "prendre": "PRENDRE",
        "voir": "VOIR",
        "dire": "DIRE",
        "penser": "PENSER",
        "aimer": "AIMER",
        "vouloir": "VOULOIR",
        "devoir": "DEVOIR",
    }

    def _answer(self, svo):
        hw = svo["headword"]
        subj = svo.get("subject")
        obj = svo.get("object")
        modal = svo.get("modal")
        verb_lemma = svo["verb_lemma"]
        wh_slot = svo.get("wh_slot")

        # Question ouverte « Comment est X ? » / « X est comment ? »
        if svo.get("is_comment_question") and subj:
            return self._answer_comment_question(subj)

        # Cas modal : « X peut V Y ? »
        if modal == "pouvoir":
            return self._answer_modal_pouvoir(svo, subj, obj, hw)

        # Déterminer le prédicat
        pred = None
        if verb_lemma in self.VERB_TO_PREDICATE:
            pred = self.VERB_TO_PREDICATE[verb_lemma]
        elif hw and hw in self.entries:
            pred = hw
        else:
            pred = verb_lemma.upper() if verb_lemma else None

        # Modaux hors pouvoir : reconstruire un prédicat composé
        # « <MODAL> <VERB> » (ex. DEVOIR RENDRE) et essayer le prover.
        if modal and modal != "pouvoir" and pred:
            compound = f"{modal.upper()} {pred}"
            self._last_reason = None
            pos = self._prove(compound, subject=subj, obj=obj, negated=False)
            if pos is True:
                mock = Fact(order=0, predicate=compound, subject=subj, obj=obj, neg=False)
                base = self._format_answer(compound, mock, subj, obj)
                return self._append_because(base, self._last_reason, compound, subj, obj)
            self._last_reason = None
            neg = self._prove(compound, subject=subj, obj=obj, negated=True)
            if neg is True:
                mock = Fact(order=0, predicate=compound, subject=subj, obj=obj, neg=True)
                base = self._format_answer(compound, mock, subj, obj)
                return self._append_because(base, self._last_reason, compound, subj, obj)

        if not pred:
            return "Je ne sais pas répondre à cette question."

        # Questions wh- : le slot wildcard est à trouver dans la base
        if wh_slot:
            return self._answer_wh(pred, wh_slot, subj, obj, svo.get("recipient"))

        if not subj:
            return "Je ne sais pas répondre à cette question."

        # Prover dynamique : toute la logique (lookup direct, dérivation
        # d'aspect, transfert, unicité, disposition) vit dans ``_prove``.
        self._last_reason = None
        pos_result = self._prove(pred, subject=subj, obj=obj, negated=False)
        if pos_result is True:
            mock = Fact(order=0, predicate=pred, subject=subj, obj=obj, neg=False)
            base = self._format_answer(pred, mock, subj, obj)
            return self._append_because(base, self._last_reason, pred, subj, obj)
        self._last_reason = None
        neg_result = self._prove(pred, subject=subj, obj=obj, negated=True)
        if neg_result is True:
            mock = Fact(order=0, predicate=pred, subject=subj, obj=obj, neg=True)
            base = self._format_answer(pred, mock, subj, obj)
            return self._append_because(base, self._last_reason, pred, subj, obj)

        if obj:
            return f"Je n'ai aucune information sur {subj} et {obj}."
        return f"Je n'ai aucune information sur {subj}."

    def _answer_wh(self, pred, wh_slot, subj, obj, recipient):
        """Répond à une question wh- en cherchant le slot manquant.

        Pour ``qui`` (wh_slot=subject), on énumère les entités animées
        connues et on teste ``_prove(pred, subj=candidate, obj=obj)`` sur
        chacune — cela fait transiter la question par le prover dynamique
        et prend en compte la temporalité et les transferts de possession.
        Les autres cas ``wh`` restent basés sur ``search_all``.
        """
        if wh_slot == "subject":
            values = []
            for name, entity in self.entities.items():
                if not entity.animate:
                    continue
                if name == "on":
                    continue
                cand = entity.name
                self._last_reason = None
                r = self._prove(pred, subject=cand, obj=obj, negated=False)
                if r is True:
                    if cand not in values:
                        values.append(cand)
            if not values:
                return "Je ne sais pas."
            if len(values) == 1:
                return f"{values[0]}."
            return ", ".join(values) + "."

        kwargs = {}
        if wh_slot != "object" and obj:
            kwargs["obj"] = obj
        if wh_slot != "recipient" and recipient:
            kwargs["recipient"] = recipient
        if subj:
            kwargs["subject"] = subj

        results = self.search_all(pred, **kwargs)
        if not results:
            return "Je ne sais pas."

        values = []
        for f in results:
            val = getattr(f, {"subject": "subject", "object": "obj", "recipient": "recipient"}[wh_slot])
            if val and val not in values:
                values.append(val)
        if not values:
            return "Je ne sais pas."

        # Formuler la réponse
        if wh_slot == "subject":
            if len(values) == 1:
                return f"{values[0]}."
            return ", ".join(values) + "."
        if wh_slot == "object":
            joined = ", ".join(self._with_article(v) for v in values)
            return f"{subj or 'Il'} {self._verb_in_fr(pred)} {joined}."
        if wh_slot == "recipient":
            joined = ", ".join(values)
            return f"À {joined}."
        return ", ".join(values) + "."

    _CONJ_CACHE = {}

    def _verb_in_fr(self, pred):
        """Conjugue le verbe au présent 3ᵉ personne du singulier.
        Utilise mlconjug3 avec cache, avec fallback sur un petit mapping.
        Les prédicats composés (``DEVOIR AVOIR``) sont traités en
        conjuguant le premier mot et gardant la suite à l'infinitif."""
        if pred in self._CONJ_CACHE:
            return self._CONJ_CACHE[pred]
        if " " in pred:
            head, rest = pred.split(" ", 1)
            result = f"{self._verb_in_fr(head)} {rest.lower()}"
            self._CONJ_CACHE[pred] = result
            return result
        mapping = {
            "AVOIR": "a",
            "ÊTRE": "est",
            "SAVOIR": "sait",
            "FAIRE": "fait",
            "DONNER": "donne",
            "PAYER": "paie",
            "PRENDRE": "prend",
            "DIRE": "dit",
            "VOIR": "voit",
            "PENSER": "pense",
            "ACHETER": "achète",
            "VENDRE": "vend",
            "PRÊTER": "prête",
            "EMPRUNTER": "emprunte",
            "DONNER": "donne",
            "VOLER": "vole",
            "OUBLIER": "oublie",
            "APPRENDRE": "apprend",
            "DEVOIR RENDRE": "doit rendre",
            "DEVOIR DONNER": "doit donner",
            "DEVOIR PAYER": "doit payer",
            "DEVOIR FAIRE": "doit faire",
            "POUVOIR FAIRE": "peut faire",
            "VOULOIR DÉPENSER": "veut dépenser",
            "POUVOIR AMÉLIORER": "peut améliorer",
        }
        result = mapping.get(pred)
        if result is None:
            try:
                v = self.conj.conjugate(pred.lower())
                result = v.conjug_info["Indicatif"]["Présent"].get("il (elle, on)", pred.lower())
            except Exception:
                result = pred.lower()
        self._CONJ_CACHE[pred] = result
        return result

    def _append_because(self, answer: str, reason_fact: Optional[Fact],
                        queried_pred: str, queried_subj: Optional[str],
                        queried_obj: Optional[str]) -> str:
        """Ajoute « parce que … » si la raison est distincte de la question.

        On remonte toujours au **fait lexical racine** de la chaîne de
        sources (ex. ACHETER, VOLER, AVARE). C'est le mot le plus haut
        qui contient implicitement toutes les sous-conséquences de son
        aspect. Plus naturel que de citer un sous-prédicat.
        """
        if reason_fact is None:
            return answer

        lexical_fact = self._find_ultimate_cause(reason_fact)

        if (lexical_fact.predicate == queried_pred
                and lexical_fact.subject
                and queried_subj
                and lexical_fact.subject.lower() == queried_subj.lower()
                and ((lexical_fact.obj or None) == (queried_obj or None))):
            return answer

        phrase = self._reason_phrase(lexical_fact)
        if not phrase:
            return answer
        if answer.endswith("."):
            answer = answer[:-1]
        return f"{answer} parce que {phrase}."

    def _find_ultimate_cause(self, fact: Fact) -> Fact:
        """Remonte la chaîne ``source → headword`` jusqu'au fait lexical
        originel (celui dont le ``source`` est son propre prédicat ou
        absent). Permet à l'explication de pointer vers l'événement
        racine (ex. VOLER) plutôt qu'un intermédiaire (PRENDRE)."""
        seen = {id(fact)}
        current = fact
        while True:
            src = (current.source or "").split("/")[0]
            if not src or src not in self.entries or src == current.predicate:
                return current
            next_fact = None
            for f in reversed(self.facts):
                if f.predicate == src:
                    next_fact = f
                    break
            if next_fact is None or id(next_fact) in seen:
                return current
            seen.add(id(next_fact))
            current = next_fact

    def _causal_explanation(self, reason_fact: Fact, queried_pred: str,
                             queried_subj: Optional[str],
                             queried_obj: Optional[str]) -> Optional[str]:
        """Cherche une explication causale via l'aspect source du fait."""
        src = reason_fact.source or ""
        src_hw = src.split("/")[0]
        if not src_hw or src_hw not in self.entries:
            return None
        if src_hw == reason_fact.predicate:
            return None

        # Remonter jusqu'au fait racine (ex. PRENDRE → VOLER)
        top_fact = None
        for f in reversed(self.facts):
            if f.predicate == src_hw:
                top_fact = f
                break
        if top_fact is None:
            return None
        top_fact = self._find_ultimate_cause(top_fact)
        src_hw = top_fact.predicate

        entry = self.entries[src_hw]
        binding = self._binding_from_fact(entry, top_fact)

        asp_list = entry.get("signification", {}).get("interne", [])
        if not asp_list:
            return None
        parsed = parse_aspect(asp_list[0].get("aspect", ""))
        if not parsed:
            return None
        n1, seg1, conn, n2, seg2 = parsed

        preds1 = extract_predicates(seg1)
        preds2 = extract_predicates(seg2)
        target = reason_fact.predicate
        target_in_seg2 = any(p == target for p, *_ in preds2)
        target_in_seg1 = any(p == target for p, *_ in preds1)

        if target_in_seg2:
            cause_preds, cause_neg = preds1, n1
        elif target_in_seg1:
            # Target est la cause primitive. Pas de sous-cause à citer.
            return None
        else:
            return None

        # Si tous les prédicats de la cause sont PERF (état passé),
        # l'explication causale serait maladroite. Fallback top-level.
        if all(perf for (_, _, _, _, perf) in cause_preds):
            return None

        phrases = []
        for (p, sv, ov, rv, perf) in cause_preds:
            if perf:
                continue
            s = binding.get(sv) if sv else None
            o = binding.get(ov) if ov else None
            r = binding.get(rv) if rv else None
            if not s:
                continue
            mock = Fact(
                order=0, predicate=p, subject=s, obj=o,
                recipient=r, neg=cause_neg,
            )
            phrase = self._reason_phrase(mock)
            if phrase:
                phrases.append(phrase)
        if phrases:
            return " et ".join(phrases)
        return None

    def _reason_phrase(self, fact: Optional[Fact]) -> str:
        """Transforme un fait-source en proposition « parce que … ».
        Les verbes d'action sont conjugués au passé composé pour un
        rendu naturel en contexte d'explication."""
        if fact is None:
            return ""
        subj = fact.subject or ""
        pred = fact.predicate
        obj = fact.obj
        recipient = fact.recipient
        neg = fact.neg
        # Cas prédicat composé AVOIR + quantifieur (beaucoup, peu, tout, rien)
        if pred.startswith("AVOIR ") and pred.split(" ", 1)[1] in {"BEAUCOUP", "PEU", "TOUT", "RIEN"}:
            qty = pred.split(" ", 1)[1].lower()
            if not obj:
                return f"{subj} a {qty}"
            plural_obj = obj + "s" if not obj.endswith("s") else obj
            if neg:
                return f"{subj} n'a pas {qty} de {plural_obj}"
            return f"{subj} a {qty} de {plural_obj}"
        # Cas adjectif : le template est « X ÊTRE ADJ »
        entry = self.entries.get(pred)
        if entry and "ÊTRE" in (entry.get("template_syntaxique") or ""):
            return f"{subj} est {pred.lower()}"
        # AVOIR en présent simple (pas d'auxiliaire doublé)
        if pred == "AVOIR":
            if neg:
                return f"{subj} n'a pas {self._with_article(obj)}"
            return f"{subj} a {self._with_article(obj)}"
        # Verbes d'action : passé composé
        participe = self._past_participle(pred)
        parts = [subj]
        if neg:
            parts.append("n'a pas" if participe[0].lower() in self.VOWELS else "n'a pas")
        else:
            parts.append("a")
        parts.append(participe)
        if obj:
            parts.append(self._with_article(obj))
        if recipient:
            parts.append(f"à {recipient}")
        return " ".join(parts)

    _PARTICIPE_CACHE: Dict[str, str] = {}

    _PARTICIPE_OVERRIDES = {
        "ACHETER": "acheté",
        "VENDRE": "vendu",
        "DONNER": "donné",
        "PAYER": "payé",
        "PRENDRE": "pris",
        "VOLER": "volé",
        "PRÊTER": "prêté",
        "EMPRUNTER": "emprunté",
        "RENDRE": "rendu",
        "OUBLIER": "oublié",
        "APPRENDRE": "appris",
        "FAIRE": "fait",
        "DIRE": "dit",
        "VOIR": "vu",
        "SAVOIR": "su",
        "DEVOIR RENDRE": "dû rendre",
        "DEVOIR PAYER": "dû payer",
        "DEVOIR DONNER": "dû donner",
        "DEVOIR FAIRE": "dû faire",
    }

    def _past_participle(self, pred: str) -> str:
        """Retourne le participe passé (masculin singulier) d'un prédicat."""
        if pred in self._PARTICIPE_OVERRIDES:
            return self._PARTICIPE_OVERRIDES[pred]
        if pred in self._PARTICIPE_CACHE:
            return self._PARTICIPE_CACHE[pred]
        try:
            v = self.conj.conjugate(pred.lower())
            pp = v.conjug_info["Participe"]["Participe Passé"]
            result = pp.get("masculin singulier") or next(iter(pp.values()))
        except Exception:
            result = pred.lower() + "é"
        self._PARTICIPE_CACHE[pred] = result
        return result

    def _format_answer(self, pred, fact, subj, obj):
        """Formate une réponse oui/non à partir d'un fait trouvé.
        L'objet déjà connu prend naturellement l'article défini."""
        obj_def = self._with_article(obj, definite=True) if obj else "cela"
        if pred == "AVOIR":
            if fact.neg:
                return f"Non, {subj} n'a pas {obj_def}."
            return f"Oui, {subj} a {obj_def}."
        if pred == "SAVOIR":
            if fact.neg:
                return f"Non, {subj} ne sait pas {obj_def}."
            return f"Oui, {subj} sait {obj_def}."
        if pred == "ÊTRE":
            if fact.neg:
                return f"Non, {subj} n'est pas {obj or 'cela'}."
            return f"Oui, {subj} est {obj or 'cela'}."
        verb_fr = self._verb_in_fr(pred)
        if fact.neg:
            elision = "n'" if verb_fr and verb_fr[0].lower() in self.VOWELS else "ne "
            return f"Non, {subj} {elision}{verb_fr} pas {obj_def if obj else ''}.".strip()
        return f"Oui, {subj} {verb_fr} {obj_def if obj else ''}.".strip()

    def _answer_comment_question(self, subject: str) -> str:
        """Répond à « Comment est X ? » en cherchant dans le dictionnaire
        quelles entrées adjectivales matchent les faits stockés pour X.
        Seules les entrées dont le template est du type « V ÊTRE ADJ »
        sont considérées — les verbes ne sont pas admis pour éviter
        des rendus comme « Pierre est acheté ».
        """
        candidates = []
        for hw, entry in self.entries.items():
            template = entry.get("template_syntaxique", "") or ""
            if "ÊTRE" not in template:
                continue
            # Identifier la variable-sujet de l'adjectif
            adj_subject_var = None
            tokens = template.split()
            for i, t in enumerate(tokens):
                if t == "ÊTRE" and i > 0 and tokens[i - 1] in ROLE_VARS:
                    adj_subject_var = tokens[i - 1]
                    break
            if adj_subject_var is None:
                adj_subject_var = "X"
            asp_list = entry.get("signification", {}).get("interne", [])
            if not asp_list:
                continue
            for item in asp_list:
                parsed = parse_aspect(item.get("aspect", ""))
                if not parsed:
                    continue
                score, matched_segs, total_segs = self._score_aspect_match(
                    parsed, subject, adj_subject_var
                )
                if total_segs == 0:
                    continue
                if matched_segs == total_segs and matched_segs > 0:
                    trace_line = (
                        f"{hw} ({item.get('aspect','')}) : "
                        f"{matched_segs}/{total_segs} segments"
                    )
                    candidates.append((score, hw, trace_line))
                    break

        if not candidates:
            return f"Je ne sais pas comment est {subject}."

        lines = [f"Je cherche à caractériser {subject}…"]
        for _, word, trace in candidates[:5]:
            lines.append(f"  · {trace}")
        lines.append("")
        if len(candidates) == 1:
            lines.append(f"{subject} est {candidates[0][1].lower()}.")
        else:
            noms = ", ".join(c[1].lower() for c in candidates)
            lines.append(f"{subject} est {noms}.")
        return "\n".join(lines)

    def _score_aspect_match(self, parsed_aspect, subject: str,
                            adj_subject_var: str = "X"):
        """Évalue si un aspect est satisfait par les faits stockés.

        Stratégie : trouver un binding cohérent des variables (X, Y, Z, W)
        à travers les deux segments. On commence par essayer tous les
        faits pour le sujet et on construit des bindings candidats à
        partir du segment le plus concret, puis on vérifie l'autre
        segment avec la même binding.
        """
        n1, seg1, conn, n2, seg2 = parsed_aspect
        preds1 = extract_predicates(seg1)
        preds2 = extract_predicates(seg2)

        # Total de segments non-PERF à valider
        total = sum(1 for (_, _, _, _, perf) in preds1 + preds2 if not perf)
        if total == 0:
            return 0.0, 0, 0

        # Énumérer des bindings candidats à partir des faits du sujet
        # qui matchent structurellement un des segments.
        candidate_bindings = self._candidate_bindings(
            subject, adj_subject_var, preds1, preds2, n1, n2
        )

        best_matched = 0
        for binding in candidate_bindings:
            matched = 0
            for preds, seg_neg in ((preds1, n1), (preds2, n2)):
                for (p, sv, ov, rv, perf) in preds:
                    if perf:
                        continue
                    s = binding.get(sv) if sv else None
                    o = binding.get(ov) if ov else None
                    if not s:
                        continue
                    self._last_reason = None
                    result = self._prove(p, subject=s, obj=o, negated=seg_neg)
                    if result is True:
                        matched += 1
            if matched > best_matched:
                best_matched = matched
                if matched == total:
                    break

        return best_matched / total, best_matched, total

    def _candidate_bindings(self, subject, adj_subject_var, preds1, preds2, n1, n2):
        """Construit une liste de bindings candidats en énumérant les
        faits du sujet qui satisfont un des prédicats de l'aspect,
        pour ancrer les variables (notamment Y).

        En plus des bindings extraits de faits direct-match, on énumère
        les objets (et recipients) connus de la base comme candidats
        pour chaque variable non-liée. Cela permet aux aspects dont
        les segments ne produisent jamais de fait direct — mais sont
        vérifiables via le prover dynamique — d'être correctement
        évalués (ex. PAUVRE Y=voiture via NÉCESSAIRE + NEG ACHETER)."""
        bindings = [{adj_subject_var: subject}]  # binding minimal
        # Collecte d'objets candidats depuis la base (inanimés connus).
        known_objs = []
        for name, entity in self.entities.items():
            if entity.animate:
                continue
            if entity.name not in known_objs:
                known_objs.append(entity.name)
        # Variables à énumérer : toutes celles présentes dans l'aspect
        # sauf adj_subject_var.
        all_vars = set()
        for preds in (preds1, preds2):
            for (p, sv, ov, rv, _perf) in preds:
                for v in (sv, ov, rv):
                    if v and v != adj_subject_var:
                        all_vars.add(v)
        for var in all_vars:
            for obj_name in known_objs:
                bindings.append({adj_subject_var: subject, var: obj_name})
        # Pour chaque segment, chaque prédicat, chercher les faits qui
        # matchent et produire des bindings enrichis.
        for preds, seg_neg in ((preds1, n1), (preds2, n2)):
            for (p, sv, ov, rv, perf) in preds:
                if perf:
                    continue
                # Chercher des faits avec pred=p et subject=subject (si sv=adj_subject_var)
                for fact in reversed(self.facts):
                    if fact.predicate != p:
                        continue
                    if fact.neg != seg_neg:
                        continue
                    # Le sujet du fait doit correspondre à adj_subject_var
                    if sv == adj_subject_var:
                        if not fact.subject or fact.subject.lower() != subject.lower():
                            continue
                    else:
                        continue  # cas non géré pour simplifier
                    b = {adj_subject_var: subject}
                    if sv:
                        b[sv] = fact.subject
                    if ov and fact.obj:
                        b[ov] = fact.obj
                    if rv and fact.recipient:
                        b[rv] = fact.recipient
                    bindings.append(b)
        return bindings

    def _answer_modal_pouvoir(self, svo, subj, obj, hw):
        """Traite « X peut V Y ? » de façon générique via le prover.

        On interroge deux fois le prover :
        - positivement, pour établir la capacité (via AVOIR et son
          quasi-bloc externe POUVOIR FAIRE) ;
        - négativement, pour détecter une disposition contraire
          (via n'importe quel aspect générant un NEG V sur le sujet).
        Si les deux arrivent, la réponse est nuancée (il peut, mais
        ne voudra probablement pas).
        """
        verb = svo.get("verb_lemma", "")
        verb_pred = self.VERB_TO_PREDICATE.get(verb) or verb.upper()
        if not subj or not obj:
            return "Je ne sais pas répondre à cette question."

        # Pour les verbes de transfert sortant (DONNER, VENDRE, PRÊTER), il
        # faut posséder. Pour ACHETER, ne pas posséder est la précondition.
        TRANSFER_OUT = {"DONNER", "VENDRE", "PRÊTER"}
        if verb_pred in TRANSFER_OUT:
            has_it = self._prove("AVOIR", subject=subj, obj=obj, negated=False)
            if has_it is None:
                return f"Je ne sais pas si {subj} a {self._with_article(obj)}."
            if has_it is False:
                return f"Non, {subj} ne peut pas {verb} {self._with_article(obj)} — {subj} ne l'a pas."

        # Disposition contraire : le prover cherche-t-il NEG V sur le sujet ?
        will_not = self._prove(verb_pred, subject=subj, obj=obj, negated=True)
        if will_not is True:
            return (
                f"Oui, {subj} peut {verb} {self._with_article(obj)}, "
                f"mais {subj} ne le voudra probablement pas."
            )

        # Scalarité a fortiori — blocage de l'acquisition via la chaîne
        # lexicale (ex. PAUVRE → NÉCESSAIRE → BON MARCHÉ ↔ CHER).
        if self._aspect_rhs_has(verb_pred, "AVOIR"):
            blocked = self._scalar_blocked_acquisition(subj, obj)
            if blocked:
                blocker, obj_prop = blocked
                return (
                    f"Non, {subj} ne peut pas {verb} {self._with_article(obj)} — "
                    f"{subj} est {blocker.lower()}, {self._with_article(obj)} "
                    f"est {obj_prop.lower()}."
                )

        return f"Oui, {subj} peut {verb} {self._with_article(obj)}."

    # -----------------------------------------------------------------
    # Accès structurés aux entrées (helpers sans hardcode)
    # -----------------------------------------------------------------
    def _first_aspect(self, hw: str):
        """Parse la première aspect interne d'une entrée, ou ``None``."""
        entry = self.entries.get(hw)
        if not entry:
            return None
        items = entry.get("signification", {}).get("interne", [])
        if not items:
            return None
        return parse_aspect(items[0].get("aspect", ""))

    def _iter_aspects(self, hw: str):
        """Itère les aspects internes parsés d'une entrée."""
        entry = self.entries.get(hw)
        if not entry:
            return
        for item in entry.get("signification", {}).get("interne", []):
            parsed = parse_aspect(item.get("aspect", ""))
            if parsed:
                yield parsed

    def _iter_external_qbs(self, hw: str):
        """Itère les qb externes parsés ``(left, right)`` d'une entrée."""
        entry = self.entries.get(hw)
        if not entry:
            return
        for item in entry.get("signification", {}).get("externe", []):
            parsed_qb = parse_quasibloc(item.get("quasibloc", ""))
            if parsed_qb:
                yield parsed_qb

    def _aspect_rhs_has(self, hw: str, target_pred: str) -> bool:
        """True si une aspect DC de ``hw`` conclut positivement sur
        ``target_pred`` (droite du DC, non niée)."""
        for _n1, _s1, conn, n2, seg2 in self._iter_aspects(hw):
            if conn != "DC" or n2:
                continue
            if any(p == target_pred for (p, *_r) in extract_predicates(seg2)):
                return True
        return False

    def _lack_target(self, hw: str):
        """Si ``hw`` est de forme PAUVRE-like (aspect PT avec un segment
        positif ``Q`` et l'autre ``NEG AVOIR``), retourne ``Q``. Sinon ``None``."""
        for n1, seg1, conn, n2, seg2 in self._iter_aspects(hw):
            if conn != "PT":
                continue
            q_pred = None
            lacks_avoir = False
            for neg_s, seg in ((n1, seg1), (n2, seg2)):
                preds = extract_predicates(seg)
                if not preds:
                    continue
                p = preds[0][0]
                if p == "AVOIR" and neg_s:
                    lacks_avoir = True
                elif not neg_s:
                    q_pred = p
            if lacks_avoir and q_pred and q_pred in self.entries:
                return q_pred
        return None

    def _qb_right_predicate(self, hw: str):
        """Premier prédicat du côté droit du premier qb externe de ``hw``."""
        for _left, right in self._iter_external_qbs(hw):
            preds = extract_predicates(right)
            if preds:
                return preds[0][0]
        return None

    def _block_converse(self, hw: str):
        """Headword partageant le même bloc (mêmes fondateurs) que ``hw``
        mais avec le connecteur aspectuel opposé (DC↔PT). Ex. BON MARCHÉ ↔ CHER."""
        src = self.entries.get(hw)
        parsed_src = self._first_aspect(hw)
        if not src or not parsed_src:
            return None
        f1, f2 = src.get("fondateur1"), src.get("fondateur2")
        if not (f1 and f2):
            return None
        opposite = "DC" if parsed_src[2] == "PT" else "PT"
        for hw2, entry in self.entries.items():
            if hw2 == hw:
                continue
            if entry.get("fondateur1") != f1 or entry.get("fondateur2") != f2:
                continue
            parsed = self._first_aspect(hw2)
            if parsed and parsed[2] == opposite:
                return hw2
        return None

    def _subject_facts(self, subj: str):
        """Itère les faits lexicaux positifs portés par ``subj``."""
        if not subj:
            return
        for f in self.facts:
            if f.neg or not f.subject or f.subject.lower() != subj.lower():
                continue
            if f.predicate in self.entries:
                yield f

    def _scalar_blocked_acquisition(self, subj: str, obj: str):
        """A fortiori scalaire. Retourne ``(adj_sujet, adj_objet)`` ou ``None``.

        Chaîne :
        1. ``subj`` porte un adjectif ``A`` exprimant « manque ce qui est ``Q`` »
           (aspect PT + NEG AVOIR) ;
        2. ``Q`` a un qb externe ``(Y ÊTRE Q')`` ;
        3. ``Q'`` a une converse de bloc ``Q''`` (connecteur opposé) ;
        4. ``obj`` porte ``Q''`` → blocage a fortiori.
        """
        if not (subj and obj):
            return None
        for fact in self._subject_facts(subj):
            A = fact.predicate
            Q = self._lack_target(A)
            if not Q:
                continue
            Q_prime = self._qb_right_predicate(Q)
            if not Q_prime:
                continue
            Q_pp = self._block_converse(Q_prime)
            if not Q_pp:
                continue
            obj_fact = self.search_latest(Q_pp, subject=obj)
            if obj_fact and not obj_fact.neg:
                return (A, Q_pp)
        return None

    VOWELS = "aeiouéèêàâîïùûh"

    PRONOUNS_NO_ARTICLE = {"cela", "ceci", "ça", "tout", "rien", "quelque chose"}

    def _with_article(self, noun: Optional[str], definite: bool = True) -> str:
        """Préfixe un nom avec l'article approprié.

        Règle défini/indéfini :
        - Si ``definite=True`` (défaut) ou si le nom est déjà mentionné dans
          un fait antérieur → article défini (« le / la / l' / les »).
        - Sinon → article indéfini (« un / une / des »).
        - Les pronoms (cela, ceci, ça…) ne prennent pas d'article.
        """
        if not noun:
            return ""
        if noun.lower() in self.PRONOUNS_NO_ARTICLE:
            return noun
        if "_de_" in noun:
            base, _, owner = noun.partition("_de_")
            return f"{self._article(base, definite=True)}{base} de {owner}"
        already_mentioned = self._is_known(noun)
        use_def = definite or already_mentioned
        return f"{self._article(noun, definite=use_def)}{noun}"

    def _is_known(self, noun: str) -> bool:
        """True si le nom apparaît déjà dans la base de faits."""
        low = noun.lower()
        for f in self.facts:
            for v in (f.subject, f.obj, f.recipient):
                if v and v.lower() == low:
                    return True
        return False

    def _article(self, noun: str, definite: bool = True) -> str:
        if not noun:
            return ""
        first = noun[0].lower()
        gender = self._guess_gender(noun)
        is_plural = noun.lower().endswith("s") and len(noun) > 2  # heuristique
        if definite:
            if is_plural:
                return "les "
            if first in self.VOWELS:
                return "l'"
            return "la " if gender == "fem" else "le "
        # indéfini
        if is_plural:
            return "des "
        return "une " if gender == "fem" else "un "

    def _guess_gender(self, noun: str) -> str:
        # D'abord chercher dans les entités enregistrées (avec info spaCy)
        ent = self.entities.get(noun.lower())
        if ent and ent.gender:
            return ent.gender
        # Heuristique de fallback
        feminine_endings = ("té", "ion", "ance", "ence", "ure", "aine")
        low = noun.lower()
        if any(low.endswith(s) for s in feminine_endings):
            return "fem"
        return "masc"

    # -----------------------------------------------------------------
    # Meta
    # -----------------------------------------------------------------
    def _meta(self, cmd):
        raw = cmd.strip()
        lo = raw.lower()
        if lo == ":facts":
            if not self.facts:
                return "(base de faits vide)"
            return "\n".join(repr(f) for f in self.facts)
        if lo == ":reset":
            self.facts = []
            self.entities = {}
            self.order = 0
            return "Base vidée."
        if lo == ":debug":
            self.debug = not self.debug
            return f"debug = {self.debug}"
        if lo.startswith(":raisonne"):
            arg = raw[len(":raisonne"):].strip()
            return self._reason_around(arg or None)
        if lo in (":quit", ":exit", ":q"):
            raise SystemExit(0)
        return "Commande inconnue. (:facts :reset :debug :raisonne :quit)"

    # -----------------------------------------------------------------
    # Déploiement argumentatif (`:raisonne`)
    # -----------------------------------------------------------------
    def _reason_around(self, arg):
        """Déploie les inférences de voisinage autour d'un fait lexical.

        Sans argument : utilise le dernier fait stocké.
        Avec un nom : utilise le dernier fait concernant ce sujet.
        """
        fact = None
        if arg:
            for f in reversed(self.facts):
                if f.subject and f.subject.lower() == arg.lower():
                    fact = f
                    break
            if fact is None:
                return f"Aucun fait connu pour « {arg} »."
        else:
            for f in reversed(self.facts):
                if f.predicate in self.entries:
                    fact = f
                    break
            if fact is None:
                return "Aucun fait lexical récent à déployer."

        hw = fact.predicate
        entry = self.entries.get(hw)
        if not entry:
            return f"« {hw} » n'est pas dans le dictionnaire."

        binding = self._binding_from_fact(entry, fact)
        lines = []
        head_clause = self._render_headword_clause(hw, binding, fact.neg)
        lines.append(f"{head_clause.capitalize()}.")

        visited = {hw}
        self._deploy_entry(hw, binding, lines, visited, depth=0, max_depth=2)
        return "\n".join(lines)

    def _deploy_entry(self, hw, binding, lines, visited, depth, max_depth):
        indent = "  " * (depth + 1)
        for parsed in self._iter_aspects(hw):
            sentence = self._render_aspect(parsed, binding)
            lines.append(f"{indent}- {sentence}.")
        for left_seg, right_seg in self._iter_external_qbs(hw):
            sentence = self._render_qb(left_seg, right_seg, binding)
            lines.append(f"{indent}- (doxal) {sentence}.")
        if depth >= max_depth:
            return
        next_hws = []
        for parsed in self._iter_aspects(hw):
            for seg in (parsed[1], parsed[4]):
                for (p, *_r) in extract_predicates(seg):
                    if p and p not in visited and p in self.entries:
                        next_hws.append(p)
                        visited.add(p)
        for left_seg, right_seg in self._iter_external_qbs(hw):
            for seg in (left_seg, right_seg):
                for (p, *_r) in extract_predicates(seg):
                    if p and p not in visited and p in self.entries:
                        next_hws.append(p)
                        visited.add(p)
        for p in next_hws:
            lines.append(f"{indent}→ {p.lower()} :")
            self._deploy_entry(p, {}, lines, visited, depth + 1, max_depth)

    # -----------------------------------------------------------------
    # Rendu en français des segments TBS
    # -----------------------------------------------------------------
    VAR_FALLBACK = {
        "X": "quelqu'un",
        "Y": "quelque chose",
        "Z": "quelque chose",
        "W": "quelque chose",
    }

    def _is_adjectival(self, hw: str) -> bool:
        """Adjectival si le headword a un template ``… ÊTRE …``. Pour les
        prédicats non-headword rencontrés en aspect (ex. BEAUCOUP après
        strip de ÊTRE), on considère adjectival par défaut — ils ne sont
        pas conjugables."""
        entry = self.entries.get(hw)
        if entry:
            return "ÊTRE" in entry.get("template_syntaxique", "")
        # Pas un headword : si mlconjug3 ne reconnaît pas comme verbe,
        # on traite comme adjectival/nominal.
        return not self._is_verb(hw)

    _VERB_ENDINGS = ("er", "ir", "re", "oir", "aître", "oître")

    def _is_verb(self, pred: str) -> bool:
        """Heuristique : vrai si le premier mot du prédicat se termine
        par une désinence infinitive française."""
        head = pred.split(" ", 1)[0].lower()
        return head.endswith(self._VERB_ENDINGS)

    def _resolve_var(self, var, binding):
        if not var:
            return ""
        return binding.get(var) or self.VAR_FALLBACK.get(var, var)

    def _render_headword_clause(self, hw: str, binding: dict, negated: bool) -> str:
        entry = self.entries.get(hw, {})
        template = entry.get("template_syntaxique", "") or ""
        subj_var = None
        for tok in template.split():
            if tok in ("X", "Y", "Z", "W"):
                subj_var = tok
                break
        subj = self._resolve_var(subj_var, binding)
        if self._is_adjectival(hw):
            ne = "n'est pas " if negated else "est "
            return f"{subj} {ne}{hw.lower()}"
        verb = self._verb_in_fr(hw)
        return self._clause(subj, verb, "", negated)

    def _clause(self, subj: str, verb: str, obj: str, negated: bool) -> str:
        if negated:
            ne = "n'" if verb and verb[0].lower() in "aeiouéèêàâîïùûh" else "ne "
            core = f"{ne}{verb} pas"
        else:
            core = verb
        parts = [p for p in (subj, core, obj) if p]
        return " ".join(parts).strip()

    def _render_segment(self, seg: str, negated: bool, binding: dict,
                         var_override: dict = None) -> str:
        preds = extract_predicates(seg)
        if not preds:
            return seg.lower()
        p, sv, ov, rv, _perf = preds[0]
        ov_eff = var_override or {}
        subj = ov_eff.get(sv) if sv in ov_eff else (self._resolve_var(sv, binding) if sv else "")
        obj = ov_eff.get(ov) if ov in ov_eff else (self._resolve_var(ov, binding) if ov else "")
        if self._is_adjectival(p):
            ne = "n'est pas " if negated else "est "
            return f"{subj} {ne}{p.lower()}".strip()
        verb = self._verb_in_fr(p)
        return self._clause(subj, verb, obj, negated)

    def _segment_vars(self, seg: str):
        """Retourne l'ensemble des variables X/Y/Z/W du segment."""
        preds = extract_predicates(seg)
        if not preds:
            return set()
        p, sv, ov, rv, _ = preds[0]
        return {v for v in (sv, ov, rv) if v}

    def _render_aspect(self, parsed, binding: dict) -> str:
        """Rend un aspect en phrase. Détecte le cas ``Y ÊTRE Q ⟨DC|PT⟩
        X … AVOIR Y`` pour produire une relative (« ce qui est Q »)
        quand Y est non lié."""
        n1, s1, conn, n2, s2 = parsed
        connector = "donc" if conn == "DC" else "pourtant"
        # Cas particulier : variable partagée non-liée entre segments.
        shared = (self._segment_vars(s1) & self._segment_vars(s2)) - set(binding)
        if len(shared) == 1:
            pivot = next(iter(shared))
            preds1 = extract_predicates(s1)
            preds2 = extract_predicates(s2)
            # Gauche « pivot ÊTRE Q » devient « ce qui est Q »
            if preds1 and preds1[0][1] == pivot and self._is_adjectival(preds1[0][0]):
                q = preds1[0][0].lower()
                left = f"ce qui est {q}"
                # Droite : remplacer le pivot par « le » / « l' » si objet
                p2, sv2, ov2, rv2, _ = preds2[0]
                if ov2 == pivot:
                    verb = self._verb_in_fr(p2)
                    subj2 = self._resolve_var(sv2, binding)
                    pron = "l'" if verb and verb[0].lower() in "aeiouéèêàâîïùûh" else "le "
                    if n2:
                        ne = "n'" if pron == "l'" else "ne "
                        right = f"{subj2} {ne}{pron if ne == 'ne ' else pron}{verb} pas".replace("  ", " ")
                        # Simpler: {subj} ne l'{verb} pas / {subj} ne le {verb} pas
                        if pron == "l'":
                            right = f"{subj2} ne l'{verb} pas"
                        else:
                            right = f"{subj2} ne le {verb} pas"
                    else:
                        if pron == "l'":
                            right = f"{subj2} l'{verb}"
                        else:
                            right = f"{subj2} le {verb}"
                    return f"{left}, {connector} {right}"
        left = self._render_segment(s1, n1, binding)
        right = self._render_segment(s2, n2, binding)
        return f"{left}, {connector} {right}"

    @staticmethod
    def _strip_segment_neg(seg: str):
        """Extrait le NEG (préfixe ou infixe ``X NEG …``) d'un segment."""
        s = seg.strip()
        if s.startswith("NEG "):
            return True, s[4:].strip()
        m = re.match(r"^([XYZW])\s+NEG\s+(.*)$", s)
        if m:
            return True, f"{m.group(1)} {m.group(2)}".strip()
        return False, s

    def _render_qb(self, left_seg: str, right_seg: str, binding: dict) -> str:
        """Rend un quasi-bloc ``A (B)`` comme « A, donc par défaut B »."""
        n_l, s_l = self._strip_segment_neg(left_seg)
        n_r, s_r = self._strip_segment_neg(right_seg)
        left = self._render_segment(s_l, n_l, binding)
        right = self._render_segment(s_r, n_r, binding)
        return f"{left}, donc par défaut {right}"


# =====================================================================
# REPL
# =====================================================================

def main():
    bot = TBSChat()
    print("Chatbot TBS — tape :quit pour sortir.\n")
    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue
            try:
                reply = bot.process(line)
            except SystemExit:
                break
            except Exception as e:
                reply = f"Erreur : {e}"
            if reply:
                print(reply)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
