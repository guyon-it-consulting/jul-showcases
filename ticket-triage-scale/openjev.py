"""Load real support tickets from the public Open-Jev dataset.

Open-Jev (ZefanCai/Open-Jev, CC0-1.0) publishes support-ticket triage as *typed
decisions*: each row is a state (the ticket/conversation) plus one question
(`choice` / `noul` / `score`), its ordered `options`, and a gold `target`. This
is the exact shape of JuL's API, so no reformatting is needed.

Several decisions share one ticket (`group_id`): a category Choice, a severity
Score, a frustration Score, refund/repro Nouls, etc. For the scale and autoscale
demos we focus on the **category** Choice — the routing decision — and keep its
gold label so we can measure real accuracy.

Everything is fetched with `datasets` streaming, so we never download the whole
corpus: we pull only the first N rows we need.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Ticket:
    """One support ticket reduced to its category-routing decision."""
    text: str                     # the ticket / conversation (the JuL "state")
    instructions: str             # the question shown to the model
    options: dict[str, str]       # key -> description, in dataset order
    gold_key: str                 # the correct option key (from the gold target)


def _state_text(row) -> str:
    """Open-Jev stores the state as JSON; decode to the plain conversation text."""
    raw = row["state_json"]
    try:
        val = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return str(raw)
    return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)


def _option_pairs(options: list[str]) -> dict[str, str]:
    """Options look like 'billing: Charges, invoices, refunds'. Split into key -> description."""
    pairs = {}
    for opt in options:
        if ": " in opt:
            key, desc = opt.split(": ", 1)
        else:
            key, desc = opt, opt
        pairs[key.strip()] = desc.strip()
    return pairs


def load_category_tickets(n: int, split: str = "train",
                          config: str = "release-v2-redistributable") -> list[Ticket]:
    """Stream up to `n` unique category-routing tickets from Open-Jev with their gold label.

    Requires `pip install datasets`. Uses streaming, so only the rows needed are fetched.
    The support-routing category question comes from the `customer-control-v1` source, of
    which there are ~700 unique tickets near the start of the corpus.
    """
    from datasets import load_dataset

    ds = load_dataset("ZefanCai/Open-Jev", config, split=split, streaming=True)
    tickets: list[Ticket] = []
    for row in ds:
        if row["kind"] != "choice" or "category of this support ticket" not in row["question"]:
            continue
        options = _option_pairs(list(row["options"]))
        keys = list(options)
        target = list(row["target"])
        # Gold = the option with the highest target weight (ties -> first).
        gold_idx = max(range(len(target)), key=lambda i: target[i])
        tickets.append(Ticket(
            text=_state_text(row),
            instructions=row["question"],
            options=options,
            gold_key=keys[gold_idx],
        ))
        if len(tickets) >= n:
            break
    return tickets


def load_tickets_cycled(n: int, unique_cap: int = 100000) -> tuple[list[Ticket], int]:
    """Return `n` tickets for a throughput run, cycling the pool of unique real tickets.

    Real ticket texts drive the timing (their true length/token count), so throughput
    is genuine; cycling only lets us reach a large volume the small public slice does
    not itself contain. Returns (tickets, n_unique).
    """
    import itertools

    pool = load_category_tickets(min(n, unique_cap))
    if len(pool) >= n:
        return pool[:n], len(pool)
    cycled = list(itertools.islice(itertools.cycle(pool), n))
    return cycled, len(pool)


if __name__ == "__main__":
    # Quick smoke test: show a few tickets and their gold category.
    for t in load_category_tickets(3):
        print(f"[{t.gold_key}] {t.text[:80]}...")
        print(f"   options: {list(t.options)}")
