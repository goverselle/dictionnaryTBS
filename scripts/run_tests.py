#!/usr/bin/env python3
"""
Runner de tests pour le chatbot TBS.

Parse ``tests/dialogues.txt`` et exécute chaque scénario contre une
instance de ``TBSChat``. Format du fichier :

    # …              commentaire
    @scenario: nom   début d'un scénario
    :reset           commande meta envoyée au bot
    > …              input utilisateur
    = …              sous-chaîne attendue dans la réponse au dernier `>`
    ≠ …              sous-chaîne interdite dans la réponse au dernier `>`

Sortie : rapport pass/fail par scénario. Code retour 0 si tous passent,
1 sinon.
"""

import sys
from pathlib import Path

# Charger TBSChat depuis le même dossier
sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat import TBSChat  # noqa: E402


TESTS_PATH = Path(__file__).resolve().parent.parent / "tests" / "dialogues.txt"


class Scenario:
    def __init__(self, name):
        self.name = name
        self.steps = []  # liste de tuples (kind, payload)

    def add(self, kind, payload):
        self.steps.append((kind, payload))


def parse(path: Path):
    """Parse le fichier de dialogues en une liste de Scenario."""
    scenarios = []
    current = None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("@scenario:"):
                name = stripped[len("@scenario:"):].strip()
                current = Scenario(name)
                scenarios.append(current)
                continue
            if current is None:
                continue
            if stripped.startswith(":"):
                current.add("meta", stripped)
            elif stripped.startswith(">"):
                current.add("in", stripped[1:].strip())
            elif stripped.startswith("="):
                current.add("expect", stripped[1:].strip())
            elif stripped.startswith("≠") or stripped.startswith("!="):
                if stripped.startswith("!="):
                    current.add("reject", stripped[2:].strip())
                else:
                    current.add("reject", stripped[1:].strip())
    return scenarios


def run_scenario(bot: TBSChat, scenario: Scenario):
    """Joue un scénario et retourne (nb_passed, nb_total, failures)."""
    passed = 0
    total = 0
    failures = []
    last_input = None
    last_reply = ""
    for kind, payload in scenario.steps:
        if kind == "meta":
            bot.process(payload)
        elif kind == "in":
            last_input = payload
            last_reply = bot.process(payload) or ""
        elif kind == "expect":
            total += 1
            if payload.lower() in last_reply.lower():
                passed += 1
            else:
                failures.append({
                    "input": last_input,
                    "expected": payload,
                    "reply": last_reply,
                    "kind": "expect",
                })
        elif kind == "reject":
            total += 1
            if payload.lower() not in last_reply.lower():
                passed += 1
            else:
                failures.append({
                    "input": last_input,
                    "rejected": payload,
                    "reply": last_reply,
                    "kind": "reject",
                })
    return passed, total, failures


def main():
    scenarios = parse(TESTS_PATH)
    if not scenarios:
        print("Aucun scénario trouvé dans", TESTS_PATH)
        return 1

    print(f"Chargement du bot…")
    bot = TBSChat()
    print()

    total_passed = 0
    total_checks = 0
    failed_scenarios = 0
    for sc in scenarios:
        bot.process(":reset")  # isolation systématique entre scénarios
        passed, total, failures = run_scenario(bot, sc)
        total_passed += passed
        total_checks += total
        mark = "✓" if not failures else "✗"
        print(f"{mark} {sc.name} ({passed}/{total})")
        if failures:
            failed_scenarios += 1
            for f in failures:
                print(f"    input    : {f['input']!r}")
                print(f"    reply    : {f['reply']!r}")
                if f["kind"] == "expect":
                    print(f"    attendu  : {f['expected']!r}")
                else:
                    print(f"    interdit : {f['rejected']!r}")
                print()

    print()
    print(f"{total_passed}/{total_checks} checks ok, "
          f"{len(scenarios) - failed_scenarios}/{len(scenarios)} scénarios ok")
    return 0 if failed_scenarios == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
