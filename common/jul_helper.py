"""Shared JuL client for all showcases.

Every showcase imports `get_client()` from here so the model is loaded once per
process and reused across decisions. This is the only place that touches `jul`;
to run the demos against the hosted Jev instead, change the import below from
`jul` to `typesafe_sdk` — the constructor and `system_one` shapes are identical.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache

# Re-export the typed primitives so showcases import everything from one place.
from jul import (  # noqa: F401
    TypeSafeClient,
    Choice,
    Noul,
    NoulCriteria,
    Score,
)

#: Model preset used by every showcase. Override with JUL_SHOWCASE_MODEL.
#: `wemm-4b-4bit` is the benchmark champion (Tencent WeMM-Embedding-4B, MLX 4-bit):
#: 85.7% zero-shot / 89.7% tuned on the Jev bench, ~55 ms/decision, 2.6 GB.
#: See ../jul/docs/benchmark-results-2026-09.md.
DEFAULT_MODEL = os.environ.get("JUL_SHOWCASE_MODEL", "wemm-4b-4bit")


@lru_cache(maxsize=1)
def get_client(model: str = DEFAULT_MODEL) -> TypeSafeClient:
    """Return the process-wide JuL client, loading the model on first use."""
    return TypeSafeClient(model=model)


def warmup(client: TypeSafeClient) -> None:
    """Force the model to load now (a no-op decision), so later timings are clean."""
    print(f"Loading JuL model '{client.model}' (first call only)...", file=sys.stderr)
    client.system_one(
        state="warmup",
        questions={"_": Choice(instructions="pick", criteria={"a": "one", "b": "two"})},
    )
