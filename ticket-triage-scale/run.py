"""ticket-triage-scale — triage a large volume of real support tickets, fast.

Loads real support tickets from Open-Jev and routes each to a team with a JuL
`Choice`. It processes them in one batched pass (`engine.read_many`), measures the
real throughput on your machine, checks accuracy against the dataset's gold
labels, then extrapolates to 1M / 10M tickets and compares the cost against a
hosted LLM API.

The headline: millions of tickets triaged locally, in a time you can measure now,
for essentially zero marginal cost — nothing is sent anywhere, nothing is generated.

Run:
    python ticket-triage-scale/run.py                    # 2000 tickets, default model
    python ticket-triage-scale/run.py --n 10000
    python ticket-triage-scale/run.py --model wemm-4b-4bit   # slower but more accurate
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from common.jul_helper import get_client, Choice  # noqa: E402
from openjev import load_tickets_cycled  # noqa: E402
from jul.types import options_of  # noqa: E402

# A fast model is the point of the scale demo. qwen3-embedding-0.6b is the
# throughput champion; override with --model for a more accurate (slower) one.
DEFAULT_MODEL = "qwen3-embedding-0.6b"

# Rough cost model for a hosted LLM triage call, for the comparison only.
HOSTED_MS_PER_CALL = 250        # typical hosted System-One latency (Jev published p50 ~246 ms)
HOSTED_USD_PER_CALL = 0.0004    # ~ a small classification call (input tokens); order of magnitude


def triage_batched(client, tickets):
    """Route every ticket in one batched pass. Returns (predicted_keys, seconds)."""
    # All tickets share the same question/options here, so we compile once and
    # read every state in a single batched call — the high-throughput path.
    first = tickets[0]
    q = Choice(instructions=first.instructions, criteria=first.options)
    engine = client._engine_for(None)
    compiled = engine.compile("choice", q.instructions, options_of(q), None)
    keys = [o.key for o in options_of(q)]

    states = [t.text for t in tickets]
    t0 = time.perf_counter()
    scores, _ = engine.read_many(compiled, states)   # (n, K) cosine scores
    seconds = time.perf_counter() - t0

    pred_idx = scores.argmax(axis=1)
    return [keys[i] for i in pred_idx], seconds


def fmt_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds/60:.1f} min"
    return f"{seconds/3600:.2f} h"


def run(n: int, model: str, batch_size: int) -> None:
    os.environ.setdefault("JUL_BATCH_SIZE", str(batch_size))
    os.environ.setdefault("JUL_BATCH_TOKENS", "131072")

    print(f"Loading up to {n:,} real support tickets from Open-Jev...", file=sys.stderr)
    tickets, n_unique = load_tickets_cycled(n)
    note = "" if len(tickets) == n_unique else f" ({n_unique} unique, cycled to {len(tickets):,})"
    print(f"Loaded {len(tickets):,} tickets{note}. Model: {model}\n", file=sys.stderr)

    client = get_client(model)
    # Warm up the model (first call loads weights; excluded from the timing).
    client.system_one(state="warmup", questions={"c": Choice(
        instructions=tickets[0].instructions, criteria=tickets[0].options)})

    preds, seconds = triage_batched(client, tickets)

    gold = [t.gold_key for t in tickets]
    # Accuracy is measured on the unique tickets only (cycling would just repeat it).
    correct = sum(preds[i] == gold[i] for i in range(n_unique))
    acc = correct / n_unique
    rate = len(tickets) / seconds

    print("=" * 62)
    print(f"  Triaged {len(tickets):,} tickets in {seconds:.2f} s")
    print(f"  Throughput : {rate:,.0f} tickets / second")
    print(f"  Accuracy   : {acc:.1%}  ({correct}/{n_unique} unique vs gold labels)")
    print(f"  Cost       : $0.00  (100% local, nothing sent, nothing generated)")
    print("=" * 62)

    print("\n  Extrapolated at this throughput:")
    for volume in (1_000_000, 10_000_000):
        local_s = volume / rate
        print(f"    {volume:>12,} tickets  ->  {fmt_duration(local_s):>8}   local, $0.00")

    print("\n  Same volume on a hosted LLM API "
          f"(~{HOSTED_MS_PER_CALL} ms/call, ~${HOSTED_USD_PER_CALL}/call):")
    for volume in (1_000_000, 10_000_000):
        # Hosted, assuming heavy concurrency of 50 parallel calls.
        hosted_s = volume * (HOSTED_MS_PER_CALL / 1000) / 50
        hosted_usd = volume * HOSTED_USD_PER_CALL
        print(f"    {volume:>12,} tickets  ->  {fmt_duration(hosted_s):>8}   (50x parallel), "
              f"${hosted_usd:,.0f}")

    # Show a few routed tickets.
    print("\n  Sample routing:")
    for t, p in list(zip(tickets, preds))[:5]:
        mark = "ok" if p == t.gold_key else f"!= {t.gold_key}"
        print(f"    -> {p:15s} [{mark:>14}]  {t.text[:52].strip()}...")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Triage a large volume of real support tickets with local JuL.")
    ap.add_argument("--n", type=int, default=2000, help="number of tickets to triage")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="JuL model preset")
    ap.add_argument("--batch-size", type=int, default=512, help="JUL_BATCH_SIZE for batched reads")
    args = ap.parse_args()
    run(args.n, args.model, args.batch_size)
