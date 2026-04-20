#!/usr/bin/env python3
"""
Extracteur de quasi-blocs depuis les aspects internes du dictionnaire TBS.

Pour chaque aspect interne ``L conn R`` d'une entrée, on construit un
quasi-bloc unique ``L (R)`` (ou ``L (flip(R))`` si ``conn = PT``, d'après
le carré argumentatif ``A PT B ≡ A DC NEG B``). Ce qb est ajouté au
champ ``signification.externe`` de **chaque** mot atomique cité dans
les segments L et R. Si le mot cité n'a pas d'entrée, un stub minimal
est créé avec un ``interne`` vide.

Usage :
    python3 scripts/extract_quasiblocs.py          # dry-run
    python3 scripts/extract_quasiblocs.py --apply  # écriture effective
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat import parse_aspect, extract_predicates, ROLE_VARS  # noqa: E402

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.json"
BACKUP_PATH = Path(__file__).resolve().parent.parent / "data" / "dictionnaire.backup.json"

# Prédicats à ignorer pour la génération : variables de rôle et
# marqueurs qui ne sont pas des mots-entrées.
SKIP_PREDS = {"PERF", "NEG"}

# Modaux : quand un prédicat composé commence par l'un d'eux, le qb
# est indexé sous le verbe base (sans le modal). Ex. ``DEVOIR PAYER``
# contribue à l'entrée PAYER, ``POUVOIR ATTEINDRE`` à ATTEINDRE.
MODAL_PREFIXES = ("DEVOIR", "POUVOIR", "VOULOIR")


def strip_modal(pred: str) -> str:
    """Retire un préfixe modal (DEVOIR/POUVOIR/VOULOIR) s'il est présent
    en tête d'un prédicat composé. Si ne reste que le modal seul, on
    le garde tel quel (c'est un verbe autonome dans ce cas)."""
    for m in MODAL_PREFIXES:
        if pred.startswith(m + " "):
            return pred[len(m) + 1:].strip()
    return pred


def clean_pred_name(p: str) -> str:
    """Normalise un nom de prédicat extrait d'un segment :
    - retire les tokens ``NEG`` absorbés par ``extract_predicates`` quand
      ils ne sont pas au début d'un segment (ex. ``NEG ATTENDRE`` → ``ATTENDRE``) ;
    - remplace les traits d'union par des espaces (``VOULOIR-AVOIR`` →
      ``VOULOIR AVOIR``), pour dédupliquer les variantes d'écriture.
    """
    p = p.replace("-", " ")
    parts = [t for t in p.split() if t.upper() != "NEG"]
    cleaned = " ".join(parts).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def flip_segment(seg: str) -> str:
    """Inverse la polarité globale d'un segment.

    Ordre des opérateurs TBS :
      1. PERF entoure de parenthèses — on le préserve comme enveloppe.
      2. NEG opère à l'intérieur de PERF(...) si présent, sinon
         directement sur le segment nu.
      3. Deux NEG s'annulent.

    Ex. :
      ``PERF (X NEG ATTENDRE Y)`` → ``PERF (X ATTENDRE Y)``
      ``X APPRENDRE Y``           → ``NEG X APPRENDRE Y``
      ``NEG X FAIRE Y``           → ``X FAIRE Y``
    """
    seg = seg.strip()
    if not seg:
        return "NEG"
    # Cas PERF(...) : le flip opère à l'intérieur des parenthèses.
    m_perf = re.match(r"^PERF\s*\((.*)\)\s*$", seg, re.DOTALL)
    if m_perf:
        inner = m_perf.group(1).strip()
        flipped_inner = _flip_bare(inner)
        return f"PERF ({flipped_inner})"
    return _flip_bare(seg)


def _flip_bare(seg: str) -> str:
    """Flip la polarité d'un segment nu (sans enveloppe PERF).

    Forme canonique : NEG précède toujours la première variable.
      ``NEG X PRED …`` → ``X PRED …``  (retrait)
      ``X PRED …``     → ``NEG X PRED …`` (ajout)
    """
    seg = seg.strip()
    # Accepter les deux formes en entrée (``X NEG`` ou ``NEG X``)
    m = re.match(r"^([XYZW])\s+NEG\s+(.*)$", seg)
    if m:
        return f"{m.group(1)} {m.group(2)}".strip()
    if seg.startswith("NEG "):
        return seg[4:].strip()
    # Ajouter NEG devant la première variable
    m2 = re.match(r"^([XYZW])\s+(.*)$", seg)
    if m2:
        return f"NEG {m2.group(1)} {m2.group(2)}".strip()
    return f"NEG {seg}".strip()


def _apply_neg(seg: str) -> str:
    """Ajoute NEG à un segment en respectant la hiérarchie des opérateurs.

    PERF enveloppe d'abord, NEG va à l'intérieur. Deux NEG s'annulent.
    Forme canonique : NEG toujours devant la première variable.
      ``PERF (X ATTENDRE Y)`` → ``PERF (NEG X ATTENDRE Y)``
      ``X FAIRE Y``           → ``NEG X FAIRE Y``
    """
    seg = seg.strip()
    m_perf = re.match(r"^PERF\s*\((.*)\)\s*$", seg, re.DOTALL)
    if m_perf:
        inner = m_perf.group(1).strip()
        return f"PERF ({_flip_bare(inner)})"
    m = re.match(r"^([XYZW])\s+(.*)$", seg)
    if m:
        return f"NEG {m.group(1)} {m.group(2)}".strip()
    return f"NEG {seg}".strip()


def build_quasibloc(parsed_aspect, raw_aspect: str) -> str:
    """Construit la chaîne de quasi-bloc à partir d'un aspect parsé.

    La forme retournée suit la convention ``<seg_gauche> (<seg_droit>)``
    normalisée en forme DC : si le connecteur est PT, on flippe le
    segment droit (A PT B ≡ A DC NEG B, A PT NEG B ≡ A DC B).
    Cela garantit qu'un aspect normatif et son transgressif produisent
    le même quasi-bloc unique.
    """
    n1, seg1, conn, n2, seg2 = parsed_aspect
    left = seg1
    if n1:
        left = _apply_neg(left)
    right = seg2
    if n2:
        right = _apply_neg(right)
    if conn == "PT":
        right = flip_segment(right)
    left = re.sub(r"\s+", " ", left).strip()
    right = re.sub(r"\s+", " ", right).strip()
    return f"{left} ({right})"


def collect_predicates(parsed_aspect) -> List[str]:
    """Retourne la liste des prédicats atomiques mentionnés dans les deux
    segments d'un aspect, en excluant les marqueurs PERF et les
    variables de rôle. Les prédicats composés (ex. ``POUVOIR ATTEINDRE``)
    sont retournés tels quels, comme un seul prédicat."""
    _n1, seg1, _conn, _n2, seg2 = parsed_aspect
    preds = []
    for seg in (seg1, seg2):
        for (p, _sv, _ov, _rv, _perf) in extract_predicates(seg):
            p = clean_pred_name(p or "")
            if not p or p in SKIP_PREDS:
                continue
            if p in ROLE_VARS:
                continue
            p = strip_modal(p)
            if not p or p in preds:
                continue
            preds.append(p)
    return preds


def normalize_qb_key(qb: str) -> str:
    """Clé de déduplication : on retire les espaces redondants et on
    met en minuscules pour comparer les chaînes modulo style."""
    return re.sub(r"\s+", " ", qb).strip().lower()


def load_dict() -> List[dict]:
    with open(DICT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_dict(entries: List[dict]) -> None:
    BACKUP_PATH.write_text(DICT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    with open(DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")


def first_letter(word: str) -> str:
    for ch in word:
        if ch.isalpha():
            return ch.upper()
    return "?"


def create_stub(headword: str) -> dict:
    return {
        "headword": headword,
        "letter": first_letter(headword),
        "fondateur1": "",
        "fondateur2": "",
        "template_syntaxique": "",
        "signification": {"interne": [], "externe": []},
        "criteres": [],
    }


def main(apply: bool) -> int:
    entries = load_dict()
    by_hw: Dict[str, dict] = {e["headword"]: e for e in entries}

    # (target_hw, qb_string, exemples) à ajouter
    additions: List[Tuple[str, str, list]] = []
    # Dédup par (target_hw, clé qb normalisée)
    seen_keys: set = set()

    for entry in entries:
        src_hw = entry["headword"]
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
                key = (p, normalize_qb_key(qb))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                additions.append((p, qb, exemples))

    # Déterminer l'état actuel de chaque externe pour dédup avec ce qui
    # existe déjà dans le fichier.
    existing_keys: Dict[str, set] = {}
    for hw, entry in by_hw.items():
        ext = entry.get("signification", {}).get("externe", []) or []
        existing_keys[hw] = {
            normalize_qb_key(item.get("quasibloc", "")) for item in ext
        }

    # Appliquer
    stubs_created = 0
    qb_added = 0
    per_target: Dict[str, int] = {}
    for target, qb, exemples in additions:
        if target not in by_hw:
            stub = create_stub(target)
            by_hw[target] = stub
            entries.append(stub)
            existing_keys[target] = set()
            stubs_created += 1
        k = normalize_qb_key(qb)
        if k in existing_keys[target]:
            continue
        existing_keys[target].add(k)
        item = {"quasibloc": qb, "exemples": exemples}
        by_hw[target]["signification"].setdefault("externe", []).append(item)
        qb_added += 1
        per_target[target] = per_target.get(target, 0) + 1

    # Tri alphabétique des entrées (letter puis headword)
    entries.sort(key=lambda e: (e.get("letter", "?"), e.get("headword", "")))

    # Rapport
    print(f"Aspects sources traités : {sum(len((e.get('signification') or {}).get('interne') or []) for e in entries)}")
    print(f"Quasi-blocs candidats (après dédup inter-sources) : {len(additions)}")
    print(f"Quasi-blocs réellement ajoutés (après dédup vs. existant) : {qb_added}")
    print(f"Stubs créés : {stubs_created}")
    if stubs_created:
        stub_names = sorted(
            hw for hw in by_hw
            if not (by_hw[hw].get("signification") or {}).get("interne")
            and hw in {t for (t, _, _) in additions}
        )
        for name in stub_names:
            print(f"  · {name}")
    print()
    print("Top 15 mots les plus enrichis :")
    for hw, n in sorted(per_target.items(), key=lambda x: -x[1])[:15]:
        print(f"  {hw:30} +{n}")

    if apply:
        write_dict(entries)
        print()
        print(f"✓ Écrit : {DICT_PATH}")
        print(f"✓ Backup : {BACKUP_PATH}")
    else:
        print()
        print("(dry-run — ajoute --apply pour écrire)")
    return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    sys.exit(main(apply))
