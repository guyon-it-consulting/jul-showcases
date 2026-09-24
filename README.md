# JuL Showcases

Small, self-contained demos of [JuL](../jul) — *Juste un LLM*, a local decision
runtime with the same typed-decision interface as the TypeSafe (Jev) SDK. Each
showcase reproduces one of the ideas from [jevable.com](https://jevable.com/),
but every decision runs **locally through JuL** (`from jul import TypeSafeClient`),
not the hosted Jev API.

The point of each demo is the same as Jev's: a single small, fast, typed
decision (`Choice`, `Noul`, `Score`) embedded where a full LLM call would be too
slow or too expensive.

## Showcases

| Dir | Jevable inspiration | What it shows | JuL primitive |
| --- | --- | --- | --- |
| [`julform/`](julform/) | JevForm | A form that branches itself — after each answer, JuL picks the next best question or ends the form. | `Choice` |
| [`intent-reranker/`](intent-reranker/) | Upweight for HN / Jev Search | Re-rank a fixed list of items by a plain-language intent. | `Score` |
| [`notification-triage/`](notification-triage/) | Quiet marketing notifications | Classify each notification as ad/marketing noise vs. important. | `Noul` |
| [`prompt-difficulty/`](prompt-difficulty/) | Prompt difficulty classifier | Rate a prompt easy/hard before sending, to offer a "fast mode". | `Score` |

All four share one thin helper, [`common/jul_helper.py`](common/jul_helper.py),
which owns the single `TypeSafeClient` so the model is loaded once and reused.

## Setup

JuL must be importable, and the showcases use the **`wemm-4b-4bit`** preset
(Tencent WeMM-Embedding-4B, MLX 4-bit) — the current benchmark champion: 85.7%
zero-shot / 89.7% tuned on the Jev bench, ~55 ms/decision, 2.6 GB. See
[`../jul/docs/benchmark-results-2026-09.md`](../jul/docs/benchmark-results-2026-09.md).

From the `jul` checkout:

```bash
cd ../jul
pip install -e ".[mlx]"     # Apple Silicon;  use ".[torch]" elsewhere

# Register the model (weights already converted under jul/models/):
jul models add wemm-4b-4bit --repo "$(pwd)/models/wemm-4b-mlx-4bit"
```

Note: register the model with an **absolute** `--repo` path (the `$(pwd)/...`
above expands to one while you are in the `jul` directory). A relative path
(`./models/...`) only resolves from the `jul` directory and fails when the
showcases run from here.

Then, from this directory, just run any showcase with plain `python`:

```bash
python julform/run.py
python intent-reranker/run.py
python notification-triage/run.py
python prompt-difficulty/run.py
```

To use a different model without touching code, set `JUL_SHOWCASE_MODEL`, e.g.
`JUL_SHOWCASE_MODEL=minicpm5-2b python intent-reranker/run.py`.

No API key, no network at run time, nothing generated — JuL is stopped one step
before its first token and the answer is read straight out of its head.

## Notes

- First call in a process loads the model (a few seconds); later calls are fast
  (~40 ms per decision with `wemm-4b-4bit` on Apple Silicon).
- `wemm-4b-4bit` is an embedding-optimized model, so classification/ranking
  showcases (intent, notifications, difficulty) are especially sharp with it.
  The difficulty demo uses a two-way `Choice` (easy/hard) rather than a graded
  `Score` because the contrast is much cleaner on this model.
- Each `run.py` is a CLI demo with baked-in sample data and accepts overrides so
  you can try your own inputs. Run with `-h` for options.
- To swap in the real hosted Jev instead of JuL, change the import in
  `common/jul_helper.py` from `jul` to `typesafe_sdk` — the call shapes are identical.
