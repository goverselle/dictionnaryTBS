#!/usr/bin/env python3
"""
Génère un fichier HTML formaté à partir du dictionnaire TBS.

Usage:
    python scripts/generate_html.py

Produit : output/dictionnaire_tbs.html
"""

import json
import re
from pathlib import Path
from datetime import datetime


def colorize_formula(text):
    """Colore X/Z en rouge, Y/W en vert, DC/PT/NEG en gras."""
    def _repl(m):
        v = m.group(0)
        if v in ('X', 'Z'):
            return f'<span class="var-xz">{v}</span>'
        if v in ('Y', 'W'):
            return f'<span class="var-yw">{v}</span>'
        if v in ('DC', 'PT', 'NEG'):
            return f'<span class="conn">{v}</span>'
        return v
    return re.sub(r'\b(DC|PT|NEG|[XYZW])\b', _repl, text)

# Chemins
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
TEMPLATES_DIR = ROOT_DIR / "templates"
OUTPUT_DIR = ROOT_DIR / "output"

DICTIONNAIRE_PATH = DATA_DIR / "dictionnaire.json"
TYPES_PATH = DATA_DIR / "types_criteres.json"
TEMPLATE_PATH = TEMPLATES_DIR / "template.html"
OUTPUT_PATH = OUTPUT_DIR / "dictionnaire_tbs.html"


def load_data():
    with open(DICTIONNAIRE_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    with open(TYPES_PATH, "r", encoding="utf-8") as f:
        types_criteres = json.load(f)
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    return entries, types_criteres, template


def generate_toc_letters(by_letter):
    html = ""
    for letter in sorted(by_letter.keys()):
        html += f'<a href="#letter-{letter}">{letter}</a>\n'
    return html


def generate_toc_words(sorted_entries):
    html = ""
    for entry in sorted_entries:
        headword = entry["headword"]
        html += f'<a href="#entry-{headword}">{headword}</a>\n'
    return html


def generate_word_network(sorted_entries):
    tokens = []
    for entry in sorted_entries:
        tokens.append(entry["headword"])
    return "  ·  ".join(tokens * 6)


def _entry_tags(entry):
    """Détermine les tags d'un mot : paradoxal, normatif (DC), transgressif (PT)."""
    is_paradoxal = bool(entry.get("paradoxal"))
    aspects = []
    for item in entry.get("signification", {}).get("interne", []):
        aspects.append(item.get("aspect", ""))
    for item in entry.get("signification", {}).get("externe", []):
        aspects.append(item.get("quasibloc", ""))
    joined = " ".join(aspects)
    has_dc = bool(re.search(r'\bDC\b', joined))
    has_pt = bool(re.search(r'\bPT\b', joined))
    return is_paradoxal, has_dc, has_pt


def generate_sidebar(by_letter):
    """Liste cliquable des mots, groupés par lettre, pour le panneau gauche."""
    html = ""
    for letter in sorted(by_letter.keys()):
        html += f'<div class="sb-group" data-letter="{letter}">\n'
        html += f'  <div class="sb-letter">{letter}</div>\n'
        for entry in by_letter[letter]:
            hw = entry["headword"]
            f1 = entry.get("fondateur1", "")
            f2 = entry.get("fondateur2", "")
            hint = f"{f1} — {f2}" if f1 and f2 else ""
            is_paradoxal, has_dc, has_pt = _entry_tags(entry)
            paradox = ' <span class="sb-paradox">⇄</span>' if is_paradoxal else ""
            fondateurs_text = f"{f1} | {f2}"
            html += (
                f'  <a class="sb-word" data-entry="{hw}"'
                f' data-paradoxal="{str(is_paradoxal).lower()}"'
                f' data-normatif="{str(has_dc).lower()}"'
                f' data-transgressif="{str(has_pt).lower()}"'
                f' data-fondateurs="{fondateurs_text}">'
                f'<span class="sb-word-name">{hw}{paradox}</span>'
                f'<span class="sb-word-hint">{hint}</span>'
                f'</a>\n'
            )
        html += '</div>\n'
    return html


def _build_decomp_map(entries):
    return {e["headword"]: (e["fondateur1"], e["fondateur2"]) for e in entries}


_ASPECT_PREFIX_RE = re.compile(r'^\s*(PERF\s*\(\s*)?(NEG\s+)?(.*?)(\s*\))?\s*$')


def _parse_aspect(aspect):
    """Parse un aspect 'A [DC|PT] B' en (neg1, seg1, conn, neg2, seg2).
    Retourne None si non parsable (ex. aspect avec plusieurs connecteurs ou PERF complexe)."""
    if not aspect:
        return None
    # On cherche le premier connecteur DC ou PT au niveau top (pas imbriqué dans des parenthèses)
    depth = 0
    tokens = re.split(r'(\s+)', aspect.strip())
    parts = []
    conn = None
    conn_idx = -1
    i = 0
    raw = aspect.strip()
    # Approche simple : rechercher " DC " et " PT " et prendre la première occurrence hors parenthèses
    best = None
    for m in re.finditer(r'\s(DC|PT)\s', raw):
        # vérifier niveau de parenthèses avant la position
        d = 0
        for ch in raw[:m.start()]:
            if ch == '(':
                d += 1
            elif ch == ')':
                d -= 1
        if d == 0:
            best = m
            break
    if not best:
        return None
    left = raw[:best.start()].strip()
    conn = best.group(1)
    right = raw[best.end():].strip()

    def _strip_neg(s):
        s = s.strip()
        if s.startswith("NEG "):
            return True, s[4:].strip()
        return False, s

    neg1, seg1 = _strip_neg(left)
    neg2, seg2 = _strip_neg(right)
    return (neg1, seg1, conn, neg2, seg2)


def _format_aspect_parts(n1, seg1, conn, n2, seg2):
    p1 = ("NEG " + seg1) if n1 else seg1
    p2 = ("NEG " + seg2) if n2 else seg2
    return f"{p1} {conn} {p2}"


def _simplify_negation(formula):
    """Pousse NEG à l'intérieur des parenthèses PERF(...) et annule les doubles NEG.
    Ex. : NEG PERF (NEG X SAVOIR Y) → PERF (X SAVOIR Y)
         NEG PERF (X ÊTRE)         → PERF (NEG X ÊTRE)
         NEG NEG X SAVOIR Y        → X SAVOIR Y
    """
    def _push(match):
        inner = match.group(1).strip()
        if inner.startswith("NEG "):
            return f"PERF ({inner[4:]})"
        return f"PERF (NEG {inner})"

    prev = None
    while prev != formula:
        prev = formula
        formula = re.sub(r"\bNEG\s+PERF\s*\(\s*(.*?)\s*\)", _push, formula)
        formula = re.sub(r"\bNEG\s+NEG\s+", "", formula)
    return formula


def _normalize_aspect_for_match(aspect):
    """Normalise un aspect pour comparaison entre entrées : supprime astérisques et espaces multiples."""
    if not aspect:
        return ""
    s = aspect.replace("*", "")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def _compute_carre(aspect, square_value=None):
    """Retourne un dict avec les 4 coins du carré argumentatif : corner1..corner4.
    - square_value (1-4) : position imposée de l'entrée dans le carré (si fournie).
    - Sinon : heuristique (DC non-canonique → flip seg2 ; PT non-canonique → flip seg1)."""
    parsed = _parse_aspect(aspect)
    if not parsed:
        return None
    n1, seg1, conn, n2, seg2 = parsed

    # Layout d'après Carel, Parler (2023) p. 47-49 :
    #   PT en haut, DC en bas ; colonnes = converses ; diagonales = transposés.
    # square_value = position visuelle dans la grille 2×2 en ordre de lecture :
    #   1 = haut-gauche  (A PT NEG B)
    #   2 = haut-droite  (NEG A PT B)
    #   3 = bas-gauche   (A DC B)
    #   4 = bas-droite   (NEG A DC NEG B)
    # Correspondance avec la numérotation canonique utilisée en interne :
    VISUAL_TO_CANONICAL = {1: 4, 2: 3, 3: 1, 4: 2}

    if square_value in VISUAL_TO_CANONICAL:
        canonical = VISUAL_TO_CANONICAL[square_value]
        if canonical == 1:
            base_n1, base_n2 = n1, n2
        elif canonical == 2:
            base_n1, base_n2 = not n1, not n2
        elif canonical == 3:
            base_n1, base_n2 = not n1, n2
        else:  # 4
            base_n1, base_n2 = n1, not n2
        entry_corner_num = canonical
    else:
        # Heuristique
        aligned = (n1 == n2)
        canonical = (aligned and conn == "DC") or (not aligned and conn == "PT")
        if canonical:
            base_n1, base_n2 = False, False
            rel_n1, rel_n2 = n1, n2
        else:
            if conn == "DC":
                # flip seg2
                base_n1, base_n2 = False, True
                rel_n1, rel_n2 = n1, not n2
            else:
                # flip seg1
                base_n1, base_n2 = True, False
                rel_n1, rel_n2 = not n1, n2
        # (rel_n1, rel_n2) → corner number
        rel_pos = {
            (False, False): 1,
            (True, True): 2,
            (True, False): 3,
            (False, True): 4,
        }
        entry_corner_num = rel_pos[(rel_n1, rel_n2)]

    def _side(is_neg, bare):
        return ("NEG " + bare) if is_neg else bare

    # Pour chaque coin, on calcule (neg1_display, neg2_display) = base_neg XOR corner_offset
    corner_offsets = {
        1: (False, False),  # base
        2: (True, True),    # both flipped
        3: (True, False),   # neg1 flipped
        4: (False, True),   # neg2 flipped
    }
    corner_conns = {1: "DC", 2: "DC", 3: "PT", 4: "PT"}

    corners = {}
    for k in (1, 2, 3, 4):
        o1, o2 = corner_offsets[k]
        d1 = base_n1 ^ o1
        d2 = base_n2 ^ o2
        raw = _side(d1, seg1) + " " + corner_conns[k] + " " + _side(d2, seg2)
        corners[f"corner{k}"] = _simplify_negation(raw)
    corners["entry_corner"] = f"corner{entry_corner_num}"
    return corners


def _build_aspect_index(entries):
    """Index : aspect normalisé → liste de headwords qui l'ont dans leur signification interne."""
    idx = {}
    for e in entries:
        for item in e.get("signification", {}).get("interne", []):
            asp = item.get("aspect", "")
            key = _normalize_aspect_for_match(asp)
            if key:
                idx.setdefault(key, []).append(e["headword"])
    return idx


def _build_operator_map(entries):
    """Extrait DC/PT de l'aspect interne principal de chaque entrée."""
    m = {}
    for e in entries:
        for item in e.get("signification", {}).get("interne", []):
            aspect = item.get("aspect", "")
            if re.search(r'\bDC\b', aspect):
                m[e["headword"]] = "DC"
                break
            if re.search(r'\bPT\b', aspect):
                m[e["headword"]] = "PT"
                break
    return m


FR_STOP_WORDS = {
    "UN", "UNE", "DES", "DU", "LE", "LA", "LES",
    "DE", "À", "AU", "AUX", "EN", "ET", "OU", "QUE",
}


def _split_primitive(word):
    """Découpe une primitive composée en tokens sémantiques (DEVOIR RENDRE → [DEVOIR, RENDRE]).
    Les verbes pronominaux (SE …, S'…) et les compositions avec ÊTRE restent un seul token."""
    stripped = word.strip()
    if stripped.startswith("SE ") or stripped.startswith("S'"):
        return [stripped]
    if stripped.startswith("ÊTRE ") or stripped == "ÊTRE":
        return [stripped]
    tokens = [t for t in stripped.split() if t.upper() not in FR_STOP_WORDS]
    return tokens


def _render_decomp_node(word, decomp_map, op_map, visited, depth, max_depth=6):
    if not word:
        return ''
    is_entry = word in decomp_map
    classes = ["tree-label"]
    if is_entry:
        classes.append("tree-label--entry")
    else:
        classes.append("tree-label--primitive")
    attrs = f' class="{" ".join(classes)}"'
    if is_entry:
        attrs += f' data-entry="{word}"'
    label = f'<span{attrs}>{word}</span>'

    if is_entry and word not in visited and depth < max_depth:
        f1, f2 = decomp_map[word]
        v2 = visited | {word}
        op = op_map.get(word, "")
        op_attr = f' data-op="{op}"' if op else ''
        children = (
            f'<ul{op_attr}>'
            f'<li>{_render_decomp_node(f1, decomp_map, op_map, v2, depth + 1, max_depth)}</li>'
            f'<li>{_render_decomp_node(f2, decomp_map, op_map, v2, depth + 1, max_depth)}</li>'
            '</ul>'
        )
        return label + children

    # Primitive composée : décomposer en tokens (feuilles)
    if not is_entry and depth < max_depth:
        tokens = _split_primitive(word)
        if len(tokens) >= 2:
            parts = []
            for t in tokens:
                if t in decomp_map:
                    parts.append(
                        f'<li><span class="tree-label tree-label--entry" data-entry="{t}">{t}</span></li>'
                    )
                else:
                    parts.append(
                        f'<li><span class="tree-label tree-label--primitive">{t}</span></li>'
                    )
            return label + f'<ul>{"".join(parts)}</ul>'

    return label


def _render_carre(entry, aspect_index):
    """Rend le carré argumentatif pour l'aspect interne principal de l'entrée."""
    asp_list = entry.get("signification", {}).get("interne", [])
    if not asp_list:
        return ""
    aspect = asp_list[0].get("aspect", "")
    square_value = entry.get("square_value")
    carre = _compute_carre(aspect, square_value=square_value)
    if not carre:
        return ""

    entry_hw = entry["headword"]
    entry_corner_key = carre["entry_corner"]

    # Recherche des autres mots qui matchent chaque coin
    def _match_words(corner_text):
        key = _normalize_aspect_for_match(corner_text)
        matches = aspect_index.get(key, [])
        return [w for w in matches if w != entry_hw]

    def _cell(corner_key, corner_num):
        text = carre[corner_key]
        colored = colorize_formula(text)
        conn_class = "conn-dc" if " DC " in text else "conn-pt"
        matched = _match_words(text)
        word_links_html = ""
        if matched:
            links = " · ".join(
                f'<span class="carre-word" data-entry="{w}">{w}</span>' for w in matched
            )
            word_links_html = f'<div class="carre-words">{links}</div>'
        is_entry_cell = (corner_key == entry_corner_key)
        entry_mark = f'<div class="carre-entry-mark">→ {entry_hw}</div>' if is_entry_cell else ""
        cls = "carre-cell " + conn_class
        if is_entry_cell:
            cls += " carre-cell--entry"
        return (
            f'<div class="{cls}">'
            f'<div class="carre-num">({corner_num})</div>'
            f'<div class="carre-formula">{colored}</div>'
            f'{entry_mark}'
            f'{word_links_html}'
            f'</div>'
        )

    grid = (
        _cell("corner4", 1) + _cell("corner3", 2) +
        _cell("corner1", 3) + _cell("corner2", 4)
    )
    return (
        '<div class="section-title">Carré argumentatif'
        '<button class="section-info btn-carre-info" '
        'title="Rappel du layout (Carel, Parler 2023)">?</button>'
        '</div>\n'
        f'<div class="carre-argumentatif">{grid}</div>\n'
    )


def _render_decomp_tree(entry, decomp_map, op_map):
    f1, f2 = entry["fondateur1"], entry["fondateur2"]

    def _decomposable(w):
        return bool(w) and (w in decomp_map or len(_split_primitive(w)) >= 2)

    if not _decomposable(f1) and not _decomposable(f2):
        return ""
    inner = _render_decomp_node(entry["headword"], decomp_map, op_map, set(), 0)
    return (
        '<div class="section-title">Décomposition en fondateurs</div>\n'
        f'<div class="decomp-tree tree"><ul><li>{inner}</li></ul></div>\n'
    )


def generate_entries(by_letter, types_criteres, decomp_map, op_map, aspect_index):
    html = ""

    for letter in sorted(by_letter.keys()):
        html += f'''
        <div class="letter-header" id="letter-{letter}">
            <span class="letter">{letter}</span>
            <span class="letter-decoration"></span>
        </div>
        '''
        
        for entry in by_letter[letter]:
            headword = entry["headword"]
            paradox_badge = ' <span class="paradox-badge" title="Mot paradoxal">⇄</span>' if entry.get("paradoxal") else ""
            html += f'''
            <div class="entry" id="entry-{headword}">
                <div class="entry-toolbar">
                    <button class="btn-edit" data-hw="{headword}">Modifier</button>
                    <button class="btn-raw" data-hw="{headword}">{{ }} JSON</button>
                </div>
                <div class="headword">{headword}{paradox_badge}</div>
                <div class="fondateurs">Termes fondateurs : <span>{entry["fondateur1"]} — {entry["fondateur2"]}</span></div>
            '''
            if entry.get("template_syntaxique"):
                html += (
                    f'<div class="template-syntaxique">'
                    f'Template syntaxique : <span class="formula">'
                    f'{colorize_formula(entry["template_syntaxique"])}'
                    f'</span></div>\n'
                )
            # Signification interne
            if entry["signification"]["interne"]:
                html += '<div class="section-title">Signification interne (aspects)</div>\n'
                for item in entry["signification"]["interne"]:
                    html += '<div class="aspect">\n'
                    html += f'<div class="formula">{colorize_formula(item["aspect"])}</div>\n'
                    for ex in item["exemples"]:
                        html += f'''<div class="exemple">
                            <span class="phrase">{ex["phrase"]}</span>
                            <span class="ea">{ex["ea"]}</span>
                        </div>\n'''
                    html += '</div>\n'
            
            # Signification externe
            if entry["signification"]["externe"]:
                html += '<div class="section-title">Signification externe (quasi-blocs)</div>\n'
                for item in entry["signification"]["externe"]:
                    html += '<div class="quasibloc">\n'
                    html += f'<div class="formula">{colorize_formula(item["quasibloc"])}</div>\n'
                    for ex in item["exemples"]:
                        html += f'''<div class="exemple">
                            <span class="phrase">{ex["phrase"]}</span>
                            <span class="ea">{ex["ea"]}</span>
                        </div>\n'''
                    html += '</div>\n'
            
            # Critères
            if entry.get("criteres"):
                html += '<div class="criteres">\n'
                for c in entry["criteres"]:
                    type_name = types_criteres.get(str(c["type"]), f"type {c['type']}")
                    html += f'''<div class="critere">
                        <span class="critere-type">{type_name}</span>
                        <span>{c["texte"]}</span>
                    </div>\n'''
                html += '</div>\n'
            
            # Nota bene
            if entry.get("nb"):
                html += f'<div class="nb"><span class="nb-label">NB</span> {entry["nb"]}</div>\n'

            # Carré argumentatif
            html += _render_carre(entry, aspect_index)

            # Décomposition en fondateurs (tout en bas)
            html += _render_decomp_tree(entry, decomp_map, op_map)

            html += '</div>\n'
    
    return html


def generate_html(entries, types_criteres, template):
    # Trier par headword
    sorted_entries = sorted(entries, key=lambda e: e["headword"].lower())
    
    # Grouper par lettre
    by_letter = {}
    for entry in sorted_entries:
        letter = entry["letter"]
        if letter not in by_letter:
            by_letter[letter] = []
        by_letter[letter].append(entry)
    
    # Grouper par bloc
    by_bloc = {}
    for entry in sorted_entries:
        fondateurs = f"{entry['fondateur1']} — {entry['fondateur2']}"
        if fondateurs not in by_bloc:
            by_bloc[fondateurs] = []
        by_bloc[fondateurs].append(entry)
    
    # Remplacements
    html = template
    html = html.replace("{{ENTRIES_COUNT}}", str(len(entries)))
    html = html.replace("{{LETTERS_COUNT}}", str(len(by_letter)))
    html = html.replace("{{BLOCS_COUNT}}", str(len(by_bloc)))
    html = html.replace("{{SIDEBAR}}", generate_sidebar(by_letter))
    html = html.replace("{{SIDEBAR_LETTERS}}", generate_toc_letters(by_letter))
    decomp_map = _build_decomp_map(entries)
    op_map = _build_operator_map(entries)
    aspect_index = _build_aspect_index(entries)
    html = html.replace("{{ENTRIES}}", generate_entries(by_letter, types_criteres, decomp_map, op_map, aspect_index))
    html = html.replace("{{ENTRIES_JSON}}", json.dumps(
        {e["headword"]: e for e in sorted_entries}, ensure_ascii=False
    ))
    html = html.replace("{{DATE}}", datetime.now().strftime("%d/%m/%Y à %H:%M"))
    
    return html


def main():
    # Créer le dossier output s'il n'existe pas
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    entries, types_criteres, template = load_data()
    print(f"Chargé : {len(entries)} entrées")
    
    html = generate_html(entries, types_criteres, template)
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✓ Généré : {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
