#!/usr/bin/env python3
"""
Génère un fond SVG abstrait « technologique » TILABLE pour le dictionnaire.

Réseau de nœuds reliés par des lignes, sur une grille fine, avec quelques
cercles concentriques et carrés d'accent. Palette teal/aqua/sky.

La tile est conçue pour se répéter sans coutures : les nœuds sont dupliqués
sur les 8 cases voisines, les liens calculés sur l'ensemble étendu, puis
la viewBox crope la zone centrale.

Usage : python3 scripts/generate_bg.py
Sortie : templates/assets/bg.svg
"""

import math
import random
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "templates" / "assets" / "bg.svg"

W, H = 600, 600
N_NODES = 22
SEED = 11

# Palette
BG = "#026E81"
SKY = "#A1C7E0"
AQUA = "#00ABBD"
BLUE = "#0099DD"
ORANGE = "#FF9933"


def main():
    rnd = random.Random(SEED)

    # --- Nœuds dans la tile ---
    base_nodes = [
        (rnd.uniform(0, W), rnd.uniform(0, H)) for _ in range(N_NODES)
    ]

    # --- Étendre sur les 9 cases voisines (tiling) ---
    extended = []
    for dx in (-W, 0, W):
        for dy in (-H, 0, H):
            for x, y in base_nodes:
                extended.append((x + dx, y + dy))

    # --- Liens : 2 plus proches voisins, dans une fenêtre élargie ---
    threshold = 180
    seen = set()
    links = []
    for i, p in enumerate(extended):
        # ne traiter que les nœuds dont au moins une partie est visible
        if not (-100 <= p[0] <= W + 100 and -100 <= p[1] <= H + 100):
            continue
        dists = sorted(
            (
                (math.hypot(p[0] - q[0], p[1] - q[1]), j)
                for j, q in enumerate(extended)
                if j != i
            ),
            key=lambda t: t[0],
        )
        for d, j in dists[:2]:
            key = (min(i, j), max(i, j))
            if d < threshold and key not in seen:
                seen.add(key)
                links.append((i, j))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        'preserveAspectRatio="xMidYMid slice">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        # clip pour ne pas dépasser
        f'<clipPath id="clip"><rect width="{W}" height="{H}"/></clipPath>',
        '<g clip-path="url(#clip)">',
        # Grille fine
        f'<g stroke="{BLUE}" stroke-width="0.6" opacity="0.09">',
    ]
    for x in range(0, W + 1, 60):
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}"/>')
    for y in range(0, H + 1, 60):
        parts.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}"/>')
    parts.append('</g>')

    # Liens (réseau)
    parts.append(f'<g stroke="{SKY}" stroke-width="0.9" opacity="0.35">')
    for i, j in links:
        x1, y1 = extended[i]
        x2, y2 = extended[j]
        parts.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}"/>'
        )
    parts.append('</g>')

    # Quelques liens en pointillés pour varier
    parts.append(
        f'<g stroke="{AQUA}" stroke-width="0.8" stroke-dasharray="3 4" '
        'opacity="0.45" fill="none">'
    )
    rnd2 = random.Random(SEED + 1)
    for _ in range(10):
        i = rnd2.randrange(len(extended))
        j = rnd2.randrange(len(extended))
        if i == j:
            continue
        p = extended[i]
        q = extended[j]
        if not (-50 <= p[0] <= W + 50 and -50 <= p[1] <= H + 50):
            continue
        if math.hypot(p[0] - q[0], p[1] - q[1]) > threshold * 1.4:
            continue
        parts.append(
            f'<line x1="{p[0]:.0f}" y1="{p[1]:.0f}" x2="{q[0]:.0f}" y2="{q[1]:.0f}"/>'
        )
    parts.append('</g>')

    # Nœuds (sur l'ensemble étendu, le clip s'occupe du reste)
    rnd3 = random.Random(SEED + 2)
    for x, y in extended:
        if not (-20 <= x <= W + 20 and -20 <= y <= H + 20):
            continue
        r = rnd3.choice([2, 2.5, 3, 3.5, 4])
        color = rnd3.choices([SKY, AQUA, SKY, SKY], k=1)[0]
        parts.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{color}" opacity="0.78"/>'
        )

    # Cercles concentriques d'accent (placés dans la tile, dupliqués si près du bord)
    rnd4 = random.Random(SEED + 3)
    accents = [
        (rnd4.randint(80, W - 80), rnd4.randint(80, H - 80)) for _ in range(3)
    ]
    for cx, cy in accents:
        for dx in (-W, 0, W):
            for dy in (-H, 0, H):
                ax, ay = cx + dx, cy + dy
                if -100 <= ax <= W + 100 and -100 <= ay <= H + 100:
                    for r in (24, 38, 52):
                        parts.append(
                            f'<circle cx="{ax}" cy="{ay}" r="{r}" fill="none" '
                            f'stroke="{AQUA}" stroke-width="0.7" opacity="0.28"/>'
                        )

    # Quelques carrés rotatifs (accents techniques)
    rnd5 = random.Random(SEED + 4)
    for _ in range(5):
        cx = rnd5.randint(40, W - 40)
        cy = rnd5.randint(40, H - 40)
        s = rnd5.randint(7, 13)
        rot = rnd5.randint(0, 90)
        for dx in (-W, 0, W):
            for dy in (-H, 0, H):
                ax, ay = cx + dx, cy + dy
                if -30 <= ax <= W + 30 and -30 <= ay <= H + 30:
                    parts.append(
                        f'<rect x="{ax - s / 2:.0f}" y="{ay - s / 2:.0f}" '
                        f'width="{s}" height="{s}" fill="none" stroke="{SKY}" '
                        f'stroke-width="0.7" opacity="0.45" '
                        f'transform="rotate({rot} {ax} {ay})"/>'
                    )

    # Touches orange éparses, très discrètes
    rnd6 = random.Random(SEED + 5)
    for _ in range(4):
        x, y = rnd6.choice(base_nodes)
        for dx in (-W, 0, W):
            for dy in (-H, 0, H):
                ax, ay = x + dx, y + dy
                if -10 <= ax <= W + 10 and -10 <= ay <= H + 10:
                    parts.append(
                        f'<circle cx="{ax:.0f}" cy="{ay:.0f}" r="1.8" '
                        f'fill="{ORANGE}" opacity="0.9"/>'
                    )

    parts.append('</g>')  # fin clip
    parts.append('</svg>')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"✓ Généré : {OUTPUT}")


if __name__ == "__main__":
    main()
