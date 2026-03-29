#!/usr/bin/env python3
"""
Génère un fichier HTML formaté à partir du dictionnaire TBS.

Usage:
    python scripts/generate_html.py

Produit : output/dictionnaire_tbs.html
"""

import json
from pathlib import Path
from datetime import datetime

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


def generate_blocs_index(by_bloc):
    html = ""
    for fondateurs in sorted(by_bloc.keys()):
        words = ", ".join(f'<a href="#entry-{e["headword"]}">{e["headword"]}</a>' for e in by_bloc[fondateurs])
        html += f'<div class="bloc-item"><strong>{fondateurs}</strong> : {words}</div>\n'
    return html


def generate_entries(by_letter, types_criteres):
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
            html += f'''
            <div class="entry" id="entry-{headword}">
                <div class="headword">{headword}</div>
                <div class="fondateurs">Termes fondateurs : <span>{entry["fondateur1"]} — {entry["fondateur2"]}</span></div>
            '''
            
            # Signification interne
            if entry["signification"]["interne"]:
                html += '<div class="section-title">Signification interne (aspects)</div>\n'
                for item in entry["signification"]["interne"]:
                    html += '<div class="aspect">\n'
                    html += f'<div class="formula">{item["aspect"]}</div>\n'
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
                    html += f'<div class="formula">{item["quasibloc"]}</div>\n'
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
    html = html.replace("{{TOC_LETTERS}}", generate_toc_letters(by_letter))
    html = html.replace("{{TOC_WORDS}}", generate_toc_words(sorted_entries))
    html = html.replace("{{BLOCS_INDEX}}", generate_blocs_index(by_bloc))
    html = html.replace("{{ENTRIES}}", generate_entries(by_letter, types_criteres))
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
