#!/usr/bin/env python3
"""
Wrappe le fragment tbs_free_network_v2.html dans une page HTML autonome
utilisable comme iframe d'arrière-plan pour le dictionnaire.

Source : output/tbs_free_network_v2.html (fragment)
Sortie : templates/assets/bg_network.html (page complète)

Usage : python3 scripts/build_bg_network.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "output" / "tbs_free_network_v2.html"
OUTPUT = ROOT / "templates" / "assets" / "bg_network.html"

WRAPPER_HEAD = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Background network</title>
<style>
:root {
  --color-background-primary: transparent;
  --color-border-secondary: rgba(17,17,17,0.2);
  --color-border-tertiary: rgba(17,17,17,0.15);
  --color-text-primary: #444;
  --color-text-secondary: #666;
  --color-text-tertiary: #999;
  --border-radius-lg: 0;
  --border-radius-md: 0;
  --font-sans: 'JetBrains Mono', 'Courier New', monospace;
}
html, body {
  margin: 0;
  padding: 0;
  background: transparent;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}
#container {
  width: 100vw !important;
  height: 100vh !important;
  border-radius: 0 !important;
  overflow: visible !important;
}
#tooltip, #panel { display: none !important; }
</style>
</head>
<body>
"""

WRAPPER_FOOT = """
</body>
</html>
"""


def main():
    if not INPUT.exists():
        raise SystemExit(f"Source introuvable : {INPUT}")
    fragment = INPUT.read_text(encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(WRAPPER_HEAD + fragment + WRAPPER_FOOT, encoding="utf-8")
    print(f"✓ {OUTPUT}")


if __name__ == "__main__":
    main()
