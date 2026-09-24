"""prompt-difficulty — decide fast-mode vs full-model before a prompt is sent.

Inspired by "A prompt difficulty classifier": before the user hits send, JuL
classifies the prompt as easy or hard with a single `Choice`. An easy prompt is
routed to a small "fast mode" model; a hard one to the big model. Cheap enough
to run on every prompt as the user finishes typing.

We use a Choice (easy vs hard) rather than a graded Score: on the embedding
model `wemm-4b-4bit` the two-way contrast is far sharper (easy prompts ~0.00
hard, expert prompts ~0.99 hard), and P(hard) is a clean routing score.

Run:
    python prompt-difficulty/run.py
    python prompt-difficulty/run.py --prompt "Prove that sqrt(2) is irrational."
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jul_helper import get_client, Choice  # noqa: E402

SAMPLE_PROMPTS = [
    "What's the capital of France?",
    "Translate 'good morning' into Spanish.",
    "Write a haiku about autumn.",
    "Explain how HTTPS certificate validation works, including the chain of trust.",
    "Design a distributed rate limiter that works across 20 regions with <5ms overhead.",
    "Summarize this email in one sentence.",
    "Derive the backpropagation equations for a two-layer MLP from first principles.",
    "What time is it in Tokyo right now?",
]


def classify(client, prompts, threshold):
    """One Choice per prompt. P(hard) drives routing; the prompt is the state."""
    question = {
        "difficulty": Choice(
            instructions="How difficult is this prompt to answer well?",
            criteria={
                "easy": "a simple question anyone could answer quickly",
                "hard": "a hard technical or expert problem requiring deep reasoning, "
                        "math, system design, or proof",
            },
        )
    }
    out = []
    for text in prompts:
        resp = client.system_one(state=text, questions=question)
        p_hard = resp.choices["difficulty"].probabilities["hard"]
        mode = "full model" if p_hard >= threshold else "fast mode"
        out.append((text, p_hard, mode))
    return out


def run(prompts, threshold) -> None:
    client = get_client()
    print(f"Routing to full model when P(hard) >= {threshold}:\n")
    for text, p_hard, mode in classify(client, prompts, threshold):
        tag = "🧠" if mode == "full model" else "⚡"
        short = text if len(text) <= 58 else text[:55] + "..."
        print(f"{tag} [hard {p_hard:4.2f}] {mode:11s} {short}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Classify prompt difficulty for fast/full routing, powered by local JuL.")
    ap.add_argument("--prompt", action="append", help="a prompt to classify (repeatable); overrides the samples")
    ap.add_argument("--threshold", type=float, default=0.5, help="route to full model when P(hard) >= threshold")
    args = ap.parse_args()
    run(args.prompt if args.prompt else SAMPLE_PROMPTS, args.threshold)
