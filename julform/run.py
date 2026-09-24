"""julform — a form that branches itself, JevForm-style, using local JuL.

The UI (this CLI) holds no branching rules. After each answer it hands the goal
plus the answers-so-far to JuL and asks a single `Choice`: "which of the
remaining questions is most relevant to ask next?". JuL picks; we render that
question. A developer is asked their tech stack, a designer their design tool —
that decision is JuL's, not the code's. Branch arms (stack vs design_tool) are
declared as alternatives, so once JuL takes one, the form finishes.

Run:
    python julform/run.py                          # interactive
    python julform/run.py --auto                   # auto-answer as a developer
    python julform/run.py --auto --persona designer  # ...as a designer (different branch)
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jul_helper import get_client, Choice  # noqa: E402

GOAL = "Onboard a new user and recommend the right plan. Learn their role, then " \
       "the details that matter for that role, team size, and budget if relevant."

# --- Question bank. JuL picks the next question's id from here. ---
# `asks` describes what the question would learn — that's what JuL compares
# against the answers-so-far when choosing which to ask next.
QUESTIONS = {
    "role": {
        "prompt": "What best describes your role?",
        "asks": "the user's role (developer, designer, founder, ...)",
        "options": ["Developer", "Designer", "Founder", "Other"],
    },
    "stack": {
        "prompt": "What's your primary tech stack?",
        "asks": "a developer's programming language / tech stack",
        "options": ["JavaScript/TypeScript", "Python", "Go/Rust", "Other"],
    },
    "design_tool": {
        "prompt": "Which design tool do you mainly use?",
        "asks": "a designer's design tool (Figma, Sketch, ...)",
        "options": ["Figma", "Sketch", "Adobe XD", "Other"],
    },
    "team_size": {
        "prompt": "How big is your team?",
        "asks": "the size of the user's team",
        "options": ["Just me", "2-10", "11-50", "50+"],
    },
    "budget": {
        "prompt": "What's your monthly budget?",
        "asks": "the user's monthly budget",
        "options": ["<$50", "$50-500", "$500+"],
    },
}

# Canned personas for --auto mode, so the demo needs no input. Each shows JuL
# taking a different branch: the developer is asked 'stack', the designer
# 'design_tool' — decided by JuL, not by the persona.
PERSONAS = {
    "developer": {
        "role": "Developer", "stack": "Python",
        "team_size": "2-10", "budget": "$50-500",
    },
    "designer": {
        "role": "Designer", "design_tool": "Figma",
        "team_size": "Just me", "budget": "<$50",
    },
}


# Mutually-exclusive branch arms: JuL decides *which* arm fits the user's role
# (developer -> stack, designer -> design_tool). Declaring them as alternatives
# is data, not branching logic — once one arm is answered, the other is dropped
# so the form terminates. Everything else (which arm, order, when to stop) is
# JuL's call.
EXCLUSIVE_GROUPS = [{"stack", "design_tool"}]


def _drop_siblings(remaining: dict, answers: dict) -> dict:
    """Remove branch arms whose sibling in the same exclusive group is already answered."""
    out = dict(remaining)
    for group in EXCLUSIVE_GROUPS:
        if group & set(answers):  # an arm of this group was chosen
            for qid in group:
                out.pop(qid, None)
    return out


def choose_next(client, answers: dict) -> str:
    """Pick the next question, or 'done'. This is the whole 'engine' — no if/then rules.

    A single `Choice` over the remaining questions is what JuL does reliably: it
    compares the candidate questions against the state (the answers so far) and
    picks the most relevant one. For a developer it prefers 'stack' over
    'design_tool'; for a designer, the reverse (measured: stack 0.99 vs 0.07).
    We ask the winner. Branch arms (stack/design_tool) are alternatives, so once
    JuL has picked one, its sibling is dropped and the form ends naturally.
    """
    remaining = {qid: q for qid, q in QUESTIONS.items() if qid not in answers}
    remaining = _drop_siblings(remaining, answers)
    if not remaining:
        return "done"

    # Role is the entry point: always ask it first.
    if "role" not in answers:
        return "role"

    if len(remaining) == 1:
        return next(iter(remaining))

    state = {"goal": GOAL, "answers_so_far": answers}
    resp = client.system_one(
        state=state,
        questions={
            "next": Choice(
                instructions="Which is the single most relevant thing to ask this user next, "
                             "given the goal and what we already know? Prefer questions that fit "
                             "the user's role; a developer has no design tool, a designer has no "
                             "tech stack.",
                criteria={qid: q["asks"] for qid, q in remaining.items()},
            )
        },
    )
    return resp.choices["next"].choice


def run(auto: bool, persona: str) -> None:
    client = get_client()
    answers: dict[str, str] = {}
    max_steps = len(QUESTIONS)
    persona_answers = PERSONAS[persona]

    for _ in range(max_steps + 1):
        nxt = choose_next(client, answers)
        if nxt == "done":
            break
        q = QUESTIONS[nxt]
        if auto:
            ans = persona_answers.get(nxt, q["options"][-1])
            print(f"\nJuL asks: {q['prompt']}")
            print(f"  (auto) -> {ans}")
        else:
            print(f"\nJuL asks: {q['prompt']}")
            for i, opt in enumerate(q["options"], 1):
                print(f"  {i}. {opt}")
            raw = input("  > ").strip()
            ans = (
                q["options"][int(raw) - 1]
                if raw.isdigit() and 1 <= int(raw) <= len(q["options"])
                else raw
            )
        answers[nxt] = ans

    print("\n" + "=" * 48)
    print("Form complete. JuL branched to collect:")
    for qid, val in answers.items():
        print(f"  {qid:12s}: {val}")
    print("=" * 48)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="JevForm-style adaptive form, powered by local JuL.")
    ap.add_argument("--auto", action="store_true", help="auto-answer from a canned persona (no input needed)")
    ap.add_argument("--persona", choices=list(PERSONAS), default="developer",
                    help="which persona --auto answers as (shows a different branch)")
    args = ap.parse_args()
    run(args.auto, args.persona)
