#!/usr/bin/env python3
"""
Serveur local pour le dictionnaire TBS avec sauvegarde directe.

Usage :
    python3 scripts/serve.py

Ouvre ensuite : http://localhost:8080/output/dictionnaire_tbs.html

L'API POST /api/save reçoit une entrée JSON, la merge dans
data/dictionnaire.json et régénère le HTML automatiquement.
"""

import json
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DICT_PATH = ROOT / "data" / "dictionnaire.json"
GENERATE_SCRIPT = ROOT / "scripts" / "generate_html.py"
PORT = 8080


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path == "/api/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                entry = json.loads(body)

                # Charger le dictionnaire
                with open(DICT_PATH, "r", encoding="utf-8") as f:
                    dictionnaire = json.load(f)

                # Merge (mise à jour ou ajout)
                hw = entry["headword"].upper()
                entry["headword"] = hw
                index = {e["headword"].upper(): i for i, e in enumerate(dictionnaire)}
                if hw in index:
                    dictionnaire[index[hw]] = entry
                    action = "mis à jour"
                else:
                    dictionnaire.append(entry)
                    action = "ajouté"

                # Sauvegarder trié
                dictionnaire.sort(key=lambda e: e["headword"].lower())
                with open(DICT_PATH, "w", encoding="utf-8") as f:
                    json.dump(dictionnaire, f, ensure_ascii=False, indent=2)

                # Régénérer le HTML
                subprocess.run(
                    [sys.executable, str(GENERATE_SCRIPT)],
                    cwd=str(ROOT),
                    check=True,
                )

                print(f"  ✓ {hw} {action}")
                self._json_response(200, {"ok": True, "action": action, "headword": hw})

            except Exception as e:
                print(f"  ✗ Erreur : {e}")
                self._json_response(500, {"ok": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        if "POST" in str(args):
            super().log_message(format, *args)


def main():
    print(f"Dictionnaire TBS — serveur local")
    print(f"→ http://localhost:{PORT}/output/dictionnaire_tbs.html")
    print(f"Ctrl+C pour arrêter\n")
    HTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
