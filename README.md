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
| [`ticket-triage-scale/`](ticket-triage-scale/) | Support-ticket triage at volume | Route **millions** of real support tickets, measuring real throughput and cost vs a hosted API. | `Choice` |
| [`ticket-triage-autoscale/`](ticket-triage-autoscale/) | The autoscale value | `autotune` lifts a fast model's accuracy (+14.5 pts) in seconds, with throughput preserved. | `Choice` + `autotune` |
| [`browser-agent/`](browser-agent/) | A faster browser agent (Browser Use × Jev) | A **fully on-device** browser agent: JuL picks the operation + target each step; the Apple Foundation Model writes field text. | `Choice` (fan-out) |

The first four share one thin helper, [`common/jul_helper.py`](common/jul_helper.py),
which owns the single `TypeSafeClient` so the model is loaded once and reused. The
two ticket-triage demos add [`ticket-triage-scale/openjev.py`](ticket-triage-scale/openjev.py),
a loader for the public [Open-Jev](https://huggingface.co/datasets/ZefanCai/Open-Jev)
support-ticket dataset (CC0-1.0).

## Scale & autoscale: triaging millions of tickets

The two ticket-triage showcases use **real** support tickets from Open-Jev and
answer the question "can JuL triage a huge volume, fast, and well?".

**Scale** ([`ticket-triage-scale/`](ticket-triage-scale/)) routes tickets in one
batched pass and measures real throughput. Measured on Apple Silicon with the fast
`qwen3-embedding-0.6b` model, on real ticket text:

```
Triaged 50,000 tickets in 668 s   ->  ~75 tickets/second, 82.9% accuracy, $0.00
Extrapolated: 1,000,000 tickets  ->  ~3.7 h local, $0.00
              (a hosted LLM API at ~250 ms/call, 50x parallel, would be ~$400)
```

Throughput depends on ticket length (long conversations cost more tokens than
short messages), so the demo always reports the number it actually measured on
your machine, then extrapolates.

**Autoscale** ([`ticket-triage-autoscale/`](ticket-triage-autoscale/)) shows the
real value of `client.autotune(...)`: a tiny per-task head trained on a few
hundred labeled tickets, with the model's weights untouched. Measured on real
tickets (train=500, test=200):

```
                 accuracy    throughput
  zero-shot        82.0%       134 t/s
  autotuned        96.5%       136 t/s     (head trained in 6.2 s)
  ----------------------------------------
  +14.5 points accuracy, throughput preserved
```

So the fast model keeps its throughput and gains the accuracy of a much larger
one — millions of tickets triaged both fast *and* well, locally, for $0.

## A fully on-device browser agent

[`browser-agent/`](browser-agent/) reproduces the "A faster browser agent"
(Browser Use × Jev) idea, but with **both brains on-device**:

- **JuL decides.** Each step, `snapshot.js` turns the page into a numbered action
  table, and one `system_one` call does a *speculative fan-out*: pick the
  operation (`CLICK` / `TYPE_TEXT` / `SELECT` / `DONE`) and, in the same pass, the
  target for each operation family. We keep the target matching the chosen
  operation — two+ decisions in one model pass. JuL only ever *chooses*.
- **The Apple Foundation Model writes.** When the operation is `TYPE_TEXT`, the
  on-device Apple model (`fm respond`, macOS 26+) generates the field value (e.g.
  "London"). JuL never generates text.
- **The code owns the loop.** Observation freshness, an anti-loop guard, an action
  budget, and independent goal verification live in [`agent.py`](browser-agent/agent.py),
  not in the model — the same division of labor as the original.

Nothing leaves the Mac: no cloud, no API key, no cost. This is *more* on-device
than the original, which calls a hosted model for text.

```
OBSERVE  Playwright + snapshot.js  → indexed action table
DECIDE   JuL system_one (fan-out): operation + click/type/select targets   [~250 ms/step]
WRITE    if TYPE_TEXT → Apple Foundation Model generates the value          [~300 ms, warm]
ACT      Playwright executes; freshness + anti-loop guards
LOOP     re-observe → new action space
```

Measured on a bundled local demo site (multi-step flight search), Apple M-series:

```
Goal: "round-trip flights from Zurich to London in economy, stop at results"
→ TYPE_TEXT Where from?   fm→ "Zurich"
→ TYPE_TEXT Where to?     fm→ "London"
→ SELECT    Cabin class   JuL→ economy
→ CLICK     Search flights
✓ DONE      (results visible)
5 steps · ~7 s wall · JuL ~280 ms/step · $0.00
```

It generalizes to other goals (e.g. one-way Paris→Tokyo in business) with no
site-specific scripting. See [`browser-agent/`](browser-agent/) for the loop.

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

The two ticket-triage demos need the Hugging Face `datasets` library and a fast
model registered (they default to `qwen3-embedding-0.6b`):

```bash
pip install datasets
jul models add qwen3-embedding-0.6b --repo mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ

python ticket-triage-scale/run.py --n 50000        # throughput + million-scale extrapolation
python ticket-triage-autoscale/run.py              # zero-shot vs autotuned accuracy
```

The browser agent needs Playwright and the Apple Foundation Models CLI
(`fm`, built into macOS 26+; accept its licence once):

```bash
pip install playwright && python -m playwright install chromium
sudo fm license            # one-time, accept Apple's terms; check with: fm available

python browser-agent/run.py                    # drives a bundled local demo site
python browser-agent/run.py --headed           # watch the browser window
```

If `fm` is unavailable, the agent still runs but skips text entry (it only
decides operations/targets).

The same brain also drives the **real Google Flights** site — the exact
Browser Use × Jev scenario (Zürich → London):

```bash
python browser-agent/run_flights.py --headed   # watch it on the real site
```

It handles the cookie-consent gate and ARIA comboboxes, and correctly enters both
cities — including **replacing** Google's prefilled origin: JuL judges each
prefilled field against the goal with a `Noul` (e.g. "Lyon" vs a Zürich goal →
0.04 → refill), so it types "Zurich" and "London" itself. All on-device, $0.

Honest limitation: Google Flights renders results without a clean navigation and
re-renders its search controls dynamically, which the generic MVP harness does
not reliably trigger (jev-ultrafast solves this with a dedicated Browser Harness).
So the real-site run reliably *fills the search correctly* but may not always
reach the results view. The bundled local demo site (`run.py`) completes the full
flow end-to-end every time; treat `run_flights.py` as a best-effort real-site demo.

To use a different model without touching code, set `JUL_SHOWCASE_MODEL`, e.g.
`JUL_SHOWCASE_MODEL=minicpm5-2b python intent-reranker/run.py`. The ticket-triage
demos take `--model` directly (e.g. `--model wemm-4b-4bit` for higher accuracy at
lower throughput).

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
