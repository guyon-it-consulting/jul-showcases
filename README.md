# JuL Showcases

Small, self-contained demos of [JuL](../jul) — *Juste un LLM*, a local decision
runtime with the same typed-decision interface as the TypeSafe (Jev) SDK. Each
showcase reproduces one of the ideas from [jevable.com](https://jevable.com/),
but every decision runs **locally through JuL** (`from jul import TypeSafeClient`),
not the hosted Jev API.

The point of each demo is the same as Jev's: a single small, fast, typed
decision (`Choice`, `Noul`, `Score`) embedded where a full LLM call would be too
slow or too expensive.

## See it in action

**A form that branches itself** — JuL picks the next question from the answers so
far. Ask it as a developer and it asks about your stack; ask as a founder and it
skips that entirely. No `if/then` in the code — the branching lives in the model.

```console
$ python julform/run.py

JuL asks: What best describes your role?
  1. Developer   2. Designer   3. Founder   4. Other
  > 1
JuL asks: What's your primary tech stack?
  1. JavaScript/TypeScript   2. Python   3. Go/Rust   4. Other
  > 1
JuL asks: How big is your team?
  1. Just me   2. 2-10   3. 11-50   4. 50+
  > 1
JuL asks: What's your monthly budget?
  1. <$50   2. $50-500   3. $500+
  > 1
================================================
Form complete. JuL branched to collect:
  role        : Developer
  stack       : JavaScript/TypeScript
  team_size   : Just me
  budget      : <$50
================================================

$ python julform/run.py          # a founder gets a different branch — no "stack" first

JuL asks: What best describes your role?  > 3   (Founder)
JuL asks: How big is your team?           > 4   (50+)
JuL asks: What's your monthly budget?     > 3   ($500+)
================================================
Form complete. JuL branched to collect:
  role: Founder · team_size: 50+ · budget: $500+
================================================
```

**Re-rank a list by plain-language intent** — one `Score` per item, sorted.

```console
$ python intent-reranker/run.py
Intent: 'deep technical engineering content; downweight drama and clickbait'

 1. [3.48 ###] Formal verification of a distributed consensus protocol in TLA+
 2. [3.41 ###] Building a lock-free queue: memory ordering the hard way
 3. [3.21 ###] The math behind fast inverse square root, explained from scratch
 ...
 9. [0.34    ] Elon vs the board: the drama nobody saw coming
10. [0.25    ] My honest review of working from a beach for a year
```

**Mute ad/marketing noise, keep what matters** — one yes/no `Noul` per notification.

```console
$ python notification-triage/run.py

KEPT (you'll be notified):
  [ad 0.00]  Your OTP code is 481920. Do not share it with anyone.
  [ad 0.00]  Payment of $1,204.00 to Landlord LLC was successful.
  [ad 0.01]  Dr. Klein's office: your appointment is confirmed for Thursday 14:00.
MUTED (silenced, not deleted):
  [ad 1.00]  🔥 FLASH SALE! 50% off everything — shop now!
  [ad 0.84]  Congratulations! You may have won a free iPhone. Tap to claim now!!!
```

**Route prompts fast-mode vs full-model before they're sent** — a `Choice` in ~130 ms.

```console
$ python prompt-difficulty/run.py

⚡ [hard 0.00] fast mode   What's the capital of France?
⚡ [hard 0.01] fast mode   Write a haiku about autumn.
🧠 [hard 0.96] full model  Explain how HTTPS certificate validation works…
🧠 [hard 0.98] full model  Design a distributed rate limiter across 20 regions…
🧠 [hard 0.99] full model  Derive the backpropagation equations for a two-layer MLP…
```

**A fully on-device browser agent driving a real site** — JuL picks the operation
+ target from the page's **accessibility tree**; the Apple Foundation Model writes
the field text. It books a train on the real SNCF Connect, from the homepage to
priced results, entirely on your Mac.

▶️ **[Watch the screencast: `browser-agent/demo_sncf.mp4`](browser-agent/demo_sncf.mp4)**
*(recorded on a logged-out session — no account data)*

```console
$ python browser-agent/run_cdp.py --url https://www.sncf-connect.com \
      --goal "Book a one-way train from Lyon to Toulouse in 3 days, stop at results"

→ step 1  TYPE_TEXT  Rechercher     ⌨ "Lyon"        (home search)
→ step 2  TYPE_TEXT  Départ :       ⌨ "Lyon"
→ step 3  TYPE_TEXT  Arrivée :      ⌨ "Toulouse"
→ step 4  SET_DATE   dimanche 27 septembre 2026     (today + 3 days)
→ step 5  CLICK      Voir les prix
✓ step 6  DONE       → results reached & VERIFIED (Lyon + Toulouse + prices)

  JuL decisions : ~130 ms median   ·   Apple FM writes the cities   ·   $0.00
```

Every decision above runs **on-device, in tens of milliseconds, for $0** — no API
key, no network, nothing generated. Two brains, both local: JuL decides, the Apple
Foundation Model writes — and together they book a train. There's also a
scale showcase that triages **millions** of real support tickets (see below).

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
(Browser Use × Jev) idea, but with **both brains on-device** and driving **your
real browser** so it works on real, bot-protected sites:

- **JuL decides.** Each step, one `system_one` call does a *speculative fan-out*:
  pick the operation (`CLICK` / `TYPE_TEXT` / `SELECT` / `DONE`) and, in the same
  pass, the target for each operation family. JuL only ever *chooses*.
- **The Apple Foundation Model writes.** When the operation is `TYPE_TEXT`, the
  on-device Apple model (`fm respond`, macOS 26+) generates the field value (e.g.
  "Lyon"). JuL never generates text.
- **The action space comes from the accessibility tree.** Instead of DOM
  heuristics, [`agent_ax.py`](browser-agent/agent_ax.py) reads the AX tree over
  CDP, so every control carries its true role and accessible name ("Départ :",
  "Arrivée :", "Voir les prix"). This is what makes real, complex pages tractable.
- **The code owns the loop.** Observation, an anti-loop guard, an action budget,
  goal-driven date selection, and independent outcome verification live in the
  harness, not the model — the same division of labor as the original.

Nothing leaves the Mac: no cloud, no API key, no cost. This is *more* on-device
than the original, which calls a hosted model for text.

```
OBSERVE  CDP Accessibility.getFullAXTree  → role + accessible-name action table
DECIDE   JuL system_one (fan-out): operation + target                  [~130 ms/step]
WRITE    if TYPE_TEXT → Apple Foundation Model generates the value      [~300 ms, warm]
ACT      act on the real node (backendDOMNodeId); anti-loop guard
LOOP     re-observe → new action space
```

Measured on a real SNCF Connect session (Apple M-series), matched to
jev-ultrafast's discipline (both models warmed up before the clock, initial
navigation excluded, independent outcome verification):

```
Goal: "one-way train from Lyon to Toulouse in 3 days, stop at results"
→ TYPE_TEXT Rechercher   fm→ "Lyon"        (home search)
→ TYPE_TEXT Départ :      fm→ "Lyon"
→ TYPE_TEXT Arrivée :     fm→ "Toulouse"
→ SET_DATE  dimanche 27 septembre 2026     (today + 3 days, harness-matched)
→ CLICK     Voir les prix
✓ results reached & VERIFIED (Lyon + Toulouse + prices on the page)
6 steps · JuL ~130 ms/decision median · $0.00
```

No site-specific scripting: the agent decides only from the action space.

Screencast of the run: [`browser-agent/demo_sncf.mp4`](browser-agent/demo_sncf.mp4)
(recorded on a logged-out session — no account data).

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
```

The agent attaches to **your own browser** over CDP — the browser-use /
jev-ultrafast approach, where the model talks to your real Chrome/Arc rather than
a throwaway Chromium (which anti-bot systems block). The action space comes from
the **accessibility tree** ([`agent_ax.py`](browser-agent/agent_ax.py)), which
gives each control its true role and accessible name ("Départ :", "Arrivée :",
"Voir les prix") — far more robust than DOM heuristics on complex pages.

```bash
# 1) launch your browser with remote debugging, open the site, pass consent by hand:
/Applications/Arc.app/Contents/MacOS/Arc \
    --remote-debugging-port=9222 --user-data-dir="$HOME/.arc-agent"

# 2) let the on-device agent drive it (JuL decides, Apple FM writes):
python browser-agent/run_cdp.py --url https://www.sncf-connect.com \
    --goal "Book a one-way train from Lyon to Toulouse in 3 days, stop at results"

# optional: record a screencast of the run
python browser-agent/record_run.py
```

If `fm` is unavailable, the agent still runs but skips text entry (it only
decides operations/targets).

Measured on a real SNCF Connect session (Apple M-series), matched to
jev-ultrafast's discipline (both models warmed up before the clock, initial
navigation excluded, independent outcome verification): 6 steps, JuL decision
~130 ms median, Apple FM writing the cities, results reached and verified — all
on-device for $0.

Honest scope: real sites are dynamic and non-deterministic; the accessibility
tree makes field/target detection reliable, but heavily fortified sites (DataDome
CAPTCHAs, etc.) require your own trusted session (hence driving your real browser).

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
