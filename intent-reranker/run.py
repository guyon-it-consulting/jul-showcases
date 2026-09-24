"""intent-reranker — rank a fixed list of items by a plain-language intent.

Inspired by "Upweight for Hacker News" and "Jev Search": you already have a list
(here, a batch of Hacker-News-style headlines). You type what you care about in
plain language; JuL gives each item a `Score` against that intent, and we sort by it.

No embeddings, no search API — just one Score per item, which is exactly the kind
of cheap decision JuL is built for.

Run:
    python intent-reranker/run.py
    python intent-reranker/run.py --intent "deep technical systems writing, no drama"
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jul_helper import get_client, Score  # noqa: E402

ITEMS = [
    "Show HN: I built a tiny Redis clone in 500 lines of Rust",
    "Why our startup failed after raising $40M (a painful retrospective)",
    "A deep dive into how Postgres implements MVCC and vacuum",
    "Ask HN: How do you stay motivated as a solo founder?",
    "The math behind fast inverse square root, explained from scratch",
    "Elon vs the board: the drama nobody saw coming",
    "Building a lock-free queue: memory ordering the hard way",
    "10 productivity hacks that changed my life (you won't believe #7)",
    "Formal verification of a distributed consensus protocol in TLA+",
    "My honest review of working from a beach for a year",
]

DEFAULT_INTENT = "deep technical engineering content; downweight drama and clickbait"


def rerank(client, items, intent):
    """Score every item against the intent, return list sorted high-to-low.

    JuL reads the *state* as the text being judged and compares the criteria
    (level descriptions) against it, guided by the instructions. So each item is
    its own state; the intent lives in the instructions. One call per item.
    """
    question = {
        "match": Score(
            instructions=(
                "The reader is looking for content matching this intent:\n"
                f"  {intent}\n"
                "Rate how well the following item matches that intent."
            ),
            criteria=[
                "not a match at all",
                "weak match",
                "decent match",
                "strong match",
                "perfect match",
            ],
        )
    }
    scored = []
    for text in items:
        resp = client.system_one(state=text, questions=question)
        s = resp.scores["match"]
        scored.append((text, s.score, s.confidence))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def run(intent: str) -> None:
    client = get_client()
    print(f"Intent: {intent!r}\n")
    ranked = rerank(client, ITEMS, intent)
    print("Re-ranked (best match first):\n")
    for rank, (text, score, conf) in enumerate(ranked, 1):
        bar = "#" * int(round(score))  # score is 0..4
        print(f"{rank:2d}. [{score:4.2f} {bar:<4}] {text}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rank a list by plain-language intent, powered by local JuL.")
    ap.add_argument("--intent", default=DEFAULT_INTENT, help="what you care about, in plain language")
    args = ap.parse_args()
    run(args.intent)
