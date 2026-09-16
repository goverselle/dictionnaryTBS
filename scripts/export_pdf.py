# -*- coding: utf-8 -*-
"""Le dictionnaire TBS, en PDF — une mise en page faite pour le papier.

    python3 scripts/export_pdf.py                       # tout le dictionnaire
    python3 scripts/export_pdf.py LENT COMPRENDRE       # quelques entrées

L'écran et le papier ne demandent pas la même chose : le site est une
application, avec ses panneaux et son fond de couleur ; le PDF est un
livre, en une colonne, sur fond blanc, avec les formules en machine à
écrire et les variables aux couleurs de la thèse — X et Z en rouge,
Y et W en vert.
"""
import json, io, os, re, subprocess, sys, html

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DONNEES = os.path.join(RACINE, 'data', 'dictionnaire.json')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

CSS = """
@page { size: A4; margin: 22mm 20mm 20mm 20mm; }
* { box-sizing: border-box; }
body { font-family: 'Times New Roman', Georgia, serif; font-size: 11pt; line-height: 1.45;
       color: #111; margin: 0; }
.couverture { height: 250mm; display: flex; flex-direction: column; justify-content: center;
              text-align: center; page-break-after: always; }
.couverture h1 { font-size: 30pt; letter-spacing: .08em; margin: 0 0 6mm; font-weight: 700; }
.couverture .sous { font-size: 12pt; color: #444; }
.couverture .compte { margin-top: 24mm; font-size: 10pt; color: #666; }

.lettre { font-size: 22pt; font-weight: 700; letter-spacing: .12em; color: #444;
          border-bottom: 1.5pt solid #444; margin: 10mm 0 5mm; padding-bottom: 1mm;
          page-break-after: avoid; page-break-before: auto; }
.entree { page-break-inside: avoid; margin-bottom: 7mm; }
.mot { font-size: 13pt; font-weight: 700; letter-spacing: .06em; }
.maj { font-size: 8pt; color: #999; margin-left: 3mm; font-style: italic; }
.rubrique { font-size: 8.5pt; letter-spacing: .1em; text-transform: uppercase; color: #777;
            margin: 3mm 0 1mm; }
.formule { font-family: 'Courier New', monospace; font-size: 10.5pt; background: #f6f7f9;
           border-left: 2.5pt solid #444; padding: 1.6mm 3mm; margin: 1mm 0 2mm; }
.x { color: #c00000; font-weight: 700; }
.y { color: #008000; font-weight: 700; }
.conn { font-weight: 700; }
.exemple { margin: 0 0 1.5mm 5mm; }
.phrase { font-style: italic; }
.phrase::before { content: '« '; font-style: normal; }
.phrase::after { content: ' »'; font-style: normal; }
.ea { display: block; color: #444; font-size: 10pt; }
.ea::before { content: '→ '; color: #999; }
.critere { font-size: 10pt; color: #333; margin: 1mm 0 1mm 5mm; text-align: justify; }
.fondateurs { font-size: 9.5pt; color: #555; margin-top: 1mm; }
.fondateurs b { color: #333; }
.nb { font-size: 9.5pt; color: #444; margin-top: 1.5mm; border-top: .5pt dotted #bbb;
      padding-top: 1mm; }
"""

MOTS_CONN = {'DC', 'PT', 'NEG', 'PERF'}


def formule(texte):
    """Les variables en couleur, les connecteurs en gras."""
    out = []
    for bout in re.findall(r"[A-ZÀ-Ÿ']+|[^A-ZÀ-Ÿ']+", texte or ''):
        net = bout.strip('* ')
        if net in ('X', 'Z'):
            out.append('<span class="x">%s</span>' % html.escape(bout))
        elif net in ('Y', 'W'):
            out.append('<span class="y">%s</span>' % html.escape(bout))
        elif net in MOTS_CONN:
            out.append('<span class="conn">%s</span>' % html.escape(bout))
        else:
            out.append(html.escape(bout))
    return ''.join(out)


def exemples(liste):
    bouts = []
    for ex in liste or []:
        p = html.escape(ex.get('phrase') or '')
        e = html.escape(ex.get('ea') or '')
        bouts.append('<div class="exemple"><span class="phrase">%s</span>'
                     '<span class="ea">%s</span></div>' % (p, e))
    return ''.join(bouts)


def entree(e):
    h = ['<div class="entree">']
    maj = e.get('updated') or ''
    h.append('<div class="mot">%s<span class="maj">%s</span></div>'
             % (html.escape(e['headword']), maj))
    interne = e['signification'].get('interne') or []
    externe = e['signification'].get('externe') or []
    for i, a in enumerate(interne):
        h.append('<div class="rubrique">Signification interne%s</div>'
                 % (' — aspect %d' % (i + 1) if len(interne) > 1 else ''))
        h.append('<div class="formule">%s</div>' % formule(a.get('aspect')))
        h.append(exemples(a.get('exemples')))
        for c in a.get('criteres') or []:
            h.append('<div class="critere">%s</div>' % html.escape(c.get('texte') or ''))
        f1, f2 = a.get('fondateur1'), a.get('fondateur2')
        if f1 or f2:
            h.append('<div class="fondateurs">Fondateurs : <b>%s</b></div>'
                     % html.escape(' · '.join(x for x in (f1, f2) if x)))
    for i, q in enumerate(externe):
        h.append('<div class="rubrique">Signification externe%s</div>'
                 % (' — quasi-bloc %d' % (i + 1) if len(externe) > 1 else ''))
        h.append('<div class="formule">%s</div>' % formule(q.get('quasibloc') or q.get('aspect')))
        h.append(exemples(q.get('exemples')))
    if e.get('nb'):
        h.append('<div class="nb">N.B. %s</div>' % html.escape(e['nb']))
    h.append('</div>')
    return ''.join(h)


def construire(mots=None):
    d = json.load(io.open(DONNEES, encoding='utf-8'))
    if mots:
        voulus = {m.upper() for m in mots}
        d = [e for e in d if e['headword'].upper() in voulus]
    d.sort(key=lambda e: e['headword'])
    corps, lettre = [], None
    for e in d:
        initiale = e['headword'][0].upper()
        if initiale != lettre:
            lettre = initiale
            corps.append('<div class="lettre">%s</div>' % lettre)
        corps.append(entree(e))
    couverture = ('<div class="couverture"><h1>DICTIONNAIRE TBS</h1>'
                  '<div class="sous">Significations argumentatives, d’après la Théorie '
                  'des Blocs Sémantiques</div>'
                  '<div class="compte">%d entrées</div></div>' % len(d))
    return ('<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
            '<title>Dictionnaire TBS</title><style>%s</style></head><body>%s%s</body></html>'
            % (CSS, couverture if not mots else '', ''.join(corps)))


def exporter(mots=None, sortie=None):
    html_source = construire(mots)
    provisoire = os.path.join(RACINE, 'output', 'pour_pdf.html')
    os.makedirs(os.path.dirname(provisoire), exist_ok=True)
    io.open(provisoire, 'w', encoding='utf-8').write(html_source)
    sortie = sortie or os.path.join(RACINE, 'output',
                                    'dictionnaire_tbs%s.pdf' % ('_extrait' if mots else ''))
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                    '--print-to-pdf=' + sortie, 'file://' + provisoire],
                   capture_output=True, check=True)
    return sortie


if __name__ == '__main__':
    mots = sys.argv[1:] or None
    chemin = exporter(mots)
    print('écrit :', chemin, '(%.0f Ko)' % (os.path.getsize(chemin) / 1024))
