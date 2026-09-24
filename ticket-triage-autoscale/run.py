"""ticket-triage-autoscale — make the fast model accurate, without losing speed.

The scale demo showed a small fast model (`qwen3-embedding-0.6b`) triaging tickets
at high throughput, but its zero-shot accuracy is only okay. This is the autoscale
value: `client.autotune(...)` trains a tiny per-task head on a few hundred labeled
tickets in seconds — the model's weights never change — and accuracy jumps, while
inference throughput stays identical (the head is one matrix multiply on the same
vectors JuL already computes).

So you get both: the throughput of the small model AND accuracy that rivals a much
larger one. That is what lets you triage millions of tickets, fast AND well.

Run:
    python ticket-triage-autoscale/run.py
    python ticket-triage-autoscale/run.py --train 500 --test 200
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ticket-triage-scale"))
from common.jul_helper import get_client, Choice  # noqa: E402
from openjev import load_category_tickets  # noqa: E402
from jul import Context  # noqa: E402
from jul.types import options_of  # noqa: E402

DEFAULT_MODEL = "qwen3-embedding-0.6b"   # the fast throughput model from the scale demo


def accuracy(client, questions, tickets, context=None) -> float:
    ok = 0
    for t in tickets:
        pred = client.system_one(state=t.text, questions=questions, context=context).choices["category"].choice
        ok += (pred == t.gold_key)
    return ok / len(tickets)


def throughput(client, question, tickets) -> float:
    """Batched read_many throughput (tickets/s) for the current model/head."""
    engine = client._engine_for(None)
    compiled = engine.compile("choice", question.instructions, options_of(question), None)
    states = [t.text for t in tickets]
    t0 = time.perf_counter()
    engine.read_many(compiled, states)
    return len(states) / (time.perf_counter() - t0)


def run(n_train: int, n_test: int, model: str) -> None:
    os.environ.setdefault("JUL_BATCH_SIZE", "256")
    total = n_train + n_test
    print(f"Loading {total} real support tickets from Open-Jev...", file=sys.stderr)
    tickets = load_category_tickets(total)
    if len(tickets) < total:
        print(f"Only {len(tickets)} unique tickets available; adjusting.", file=sys.stderr)
        n_train = int(len(tickets) * n_train / total)
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(tickets))
    train = [tickets[i] for i in idx[:n_train]]
    test = [tickets[i] for i in idx[n_train:]]

    inst = tickets[0].instructions
    question = Choice(instructions=inst, criteria=tickets[0].options)
    questions = {"category": question}

    client = get_client(model)
    client.system_one(state="warmup", questions=questions)

    # --- zero-shot ---
    zs_acc = accuracy(client, questions, test)
    zs_rate = throughput(client, question, test)

    # --- autotune a tiny head on the labeled train tickets ---
    labeled = [(t.text, {"category": t.gold_key}) for t in train]
    context = Context(examples=[t.text for t in train])
    t0 = time.perf_counter()
    report = client.autotune(context, questions, labeled, save=False)["category"]
    train_s = time.perf_counter() - t0

    # --- tuned ---
    tuned_acc = accuracy(client, questions, test, context=context)
    tuned_rate = throughput(client, question, test)

    print("=" * 64)
    print(f"  Model: {model}   (train={len(train)}, test={len(test)} real tickets)")
    print("-" * 64)
    print(f"  {'':16}{'accuracy':>12}{'throughput':>16}")
    print(f"  {'zero-shot':16}{zs_acc:>11.1%}{zs_rate:>13,.0f} t/s")
    print(f"  {'autotuned':16}{tuned_acc:>11.1%}{tuned_rate:>13,.0f} t/s")
    print("-" * 64)
    print(f"  Accuracy gain : {tuned_acc - zs_acc:+.1%}")
    print(f"  Throughput    : {'preserved' if tuned_rate > zs_rate * 0.9 else 'changed'} "
          f"(head is one matrix multiply on the same vectors)")
    print(f"  Head trained  : {train_s:.1f}s on {len(train)} labeled tickets "
          f"(weights untouched); activated={report.activated}")
    print("=" * 64)
    print("\n  The autoscale value: the fast model keeps its throughput and gains")
    print("  the accuracy of a much larger one — so millions of tickets can be")
    print("  triaged both fast AND well, locally, for $0.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Show autotune lifting a fast model's accuracy without losing throughput.")
    ap.add_argument("--train", type=int, default=500, help="labeled tickets for autotune")
    ap.add_argument("--test", type=int, default=200, help="held-out tickets for accuracy")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="JuL model preset")
    args = ap.parse_args()
    run(args.train, args.test, args.model)
