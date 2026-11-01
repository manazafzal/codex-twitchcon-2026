# AGENTS.md — THOUGHTQUAKE

Read this file and `SPEC.md` before every task. If they conflict with a prompt, the prompt wins for that task only; tell me about the conflict in your final message.

## What this repo is
THOUGHTQUAKE is a Twitch game where chat factions fight over the thoughts of a small local AI (the "Subject"), while a live Mind-Reader and a Neural Immune System watch. A Python server runs on the streamer's PC. Viewers only type in normal Twitch chat. The overlay is a browser source. No Twitch Extension. No paid API. No cloud inference.

Hackathon: Codex x TwitchCon (Devpost). The repo must be new work, built mostly with Codex, and judges may only watch the video and read the text. Everything user-visible must be accurate and checkable.

## Hard rules (do not break)
1. **Vocabulary.** In user-facing text (overlay, chat replies, README top section, CLI help, docs outside `docs/related-work.md`) use: *thought injection*, *mind territory*, *Mind Share*, *Mind-Reader*, *Neural Immune System*, *Telepathy*, *faction*, *the Subject*. Do NOT use: "steering", "steer", "obsessed", "obsession", "can't stop talking about", "Golden Gate", "Claude", "bridge" (as an example concept), "turn up the dial", "feature clamping". The words "activation steering", "ActAdd", "CAA", "Golden Gate Claude", "brainscope" appear ONLY in `docs/related-work.md` and code comments/docstrings. The milestone test (`tests/test_vocabulary.py`) checks case-insensitive stems in all Python string literals (including docstrings) and text assets under `src/`, `docs/`, `tests/`, and `.codex/skills/`, plus README and CLI help. The only file exception is `docs/related-work.md`. Comments contain no runtime text; do not add prohibited terms or stems elsewhere.
2. **Never single-concept saturation.** The overlay must never show one faction holding more than the dominance cap (default 75 % of applied injections) except in the explicitly labelled "Immune ON/OFF" comparison. Prompts given to the Subject are always everyday tasks ("explain how to make tea"), never "tell me about yourself".
3. **No fake results.** Numbers shown in the overlay, README, or video cards must come from `results/eval.json` produced by `make eval` (real model) or be labelled `TINY MODEL / CI`. Never hard-code a result.
4. **Labels.** Every run shows exactly one source badge: `LIVE` (real Twitch chat), `REPLAY` (recorded real chat), or `SIMULATED ×N` (synthetic chatters). Simulated chatters never appear without the badge, and the sim is off by default when Twitch is connected.
5. **No secrets in git.** Tokens live in `~/.config/thoughtquake/` (mode 0600). `.env`, `*.token.json` are git-ignored. Client ID is read from env `THOUGHTQUAKE_TWITCH_CLIENT_ID`. No client secret is needed (public client, device code flow).
6. **Do not download anything at test time.** Tests must pass with no internet, no GPU, and no real model weights. Use `TinyBackend` (random-init small Qwen2-architecture model built from a config, or pure-numpy mock) and `MockBackend`. Real-model tests are marked `@pytest.mark.realmodel` and are skipped unless `THOUGHTQUAKE_REAL=1`.
7. **No code or data copied from any earlier scratch prototype.** Implement from `SPEC.md`.
8. Small dependency set: `numpy`, `aiohttp`, `pyyaml`; development: `pytest`, `ruff`, `mypy`, `types-PyYAML`; extras: `torch`, `transformers` (extra `model`). No Node build step: the overlay is plain HTML/CSS/JS files served statically.
9. Python 3.11+. Type hints everywhere in `src/`. `make check` (ruff, scoped mypy, and pytest) must be green before you finish a task.

## Commands
- Install (dev, CI-safe): `pip install -e ".[dev]"`; with tiny-model tests: `pip install -e ".[dev,model]"` (CPU torch).
- `make check` → ruff + mypy on engine/model/concepts/evaluation + pytest (non-real-model).
- `make eval` → the offline real-model harness, requiring a verified local library and weights. Equivalent: `thoughtquake eval --library library/qwen2.5-0.5b-instruct.npz --output results --alphas .3 .45 --seeds 1 --prompts 6 --concepts 30 --held-out 3 --seed 0`. Output is `eval.json` plus `eval.md`; no automatic README quality claims.
- CI-only evaluation: `thoughtquake eval --mock --output work/eval-ci`. The source is `mock` and quality is `TINY MODEL / CI`; never relabel this as real evidence.
- `thoughtquake demo` → offline demo mode (labelled simulated crowd), opens overlay URL.
- `thoughtquake replay golden/golden_run.jsonl` → deterministic replay of a recorded run.
- `thoughtquake auth` → Twitch device-code login. `thoughtquake run --channel NAME` → live.
- `thoughtquake build-library` → builds `library/<model>.npz` concept vectors for the real model.

## Working agreement
- One milestone per task. Write the tests first (or alongside), run them, show me the output. If a test fails, fix the cause; do not delete or weaken the test.
- Keep modules small and pure where possible: engine logic (mixer, readout colouring, immune decision, telepathy rules, round state machine) must be testable without torch.
- Everything the overlay shows comes from one JSON event stream (`/ws`). Overlay has no business logic beyond rendering. Record = log that stream plus chat input to JSONL; replay = feed the recorded chat input back through the same engine with fixed seeds, or (`--frames`) replay the recorded output frames exactly.
- Fail gracefully: if the model is slow, the overlay shows "thinking…" and keeps animating; if Twitch disconnects, show a `RECONNECTING` chip and keep the game going.
- Commit after each green milestone with a clear message. Do not rewrite history.
- Final message of each task: what changed, commands run with results, anything not verified (for example "not run against the real model", "not tested against live Twitch").

## Out of scope (do not build)
Twitch Extension, bits, channel points, subscriptions, any paid API, user accounts/database, free-text topic clustering of chat, vector arithmetic "cocktails", model-introspection claims, models other than Qwen2.5-0.5B/1.5B-Instruct, mobile layout.

## Code style
`src/thoughtquake/` layout. `ruff` defaults plus line length 100. Dataclasses for events. `asyncio` for IO, torch calls via `run_in_executor` single worker. Log with `logging` (no prints in library code). Docstrings explain *why*, and may cite the research ancestors (ActAdd, CAA, Golden Gate Claude, brainscope).

## M-visual: overlay tests, film, and measurement
The Mind Atlas milestone prompt supersedes §15's old geometry, palette and 28 px minimum: the new stage uses a 780 px left column and a 17 px minimum. Keep the existing event fields; `token.sky` and `layout` add measured rendering data. The SD display requires saved neutral calibration; older libraries show no SD signal until rebuilt. Hidden rounds must project both coordinates and signal keys through the public presentation layer.

- `make check` includes `tests/test_overlay_visual.py`. With local `chromium` or `google-chrome`, it runs offline Chrome DevTools checks using SwiftShader; without Chrome those browser tests skip. No browser downloads, Node, browser frameworks or remote assets are used. Browser tests use loopback HTTP only.
- `pytest -q tests/test_overlay_visual.py` checks five scenes, errors, full names, minimum text size, transparency, quarter-size contrast, Canvas fallback, and two complete 600-frame films. This can take about twenty minutes on this software-only runner; the fixed 30 fps film cadence is not a playback-speed claim.
- `THOUGHTQUAKE_DEV_FIXTURES=1 thoughtquake demo --mock` enables `/fixture.html?scene=war` (also `attack`, `immune`, `telepathy`, `reveal`). Default fixtures use recorded mock measurements; `&backend=tiny` selects captured random-init model measurements. Both show `TINY MODEL / CI`. Fixture pages, scripts and trace data return 404 without that environment setting.
- `python -m tools.capture_trace` refreshes the committed development traces using actual backend calls; requires the `model` extra. Never substitute invented token measurements or present these traces as trained-model evidence.
- `python -m tools.film --verify --output /tmp/thoughtquake.mp4` records 20 virtual seconds at 30 fps and compares every frame hash on a second run. Chrome is required; ffmpeg is needed only for MP4 output. `--hashes /tmp/film.json` selects the hash report; `--scene` and `--backend` select the recording. `?manual&scale=.5` exposes `ThoughtquakeOverlay.step(seconds)`; every presentation timer advances on that clock.
- `python -m tools.measure_overlay` refreshes `docs/screenshots/` and `docs/overlay-measurements.json`. Run it alone for valid timing. It measures 120 actual rAF intervals at `?scale=.5`; see `docs/perf.md` for limits. Manual screenshot/film timing is not a playback-fps measurement.
- Bundled fonts and OFL notices live in `src/thoughtquake/overlay/fonts/`; server font routes are allowlisted. `?nogl` selects Canvas2D; `?bg=transparent` removes the ground. Never publish development traces by enabling fixtures on a live server.


## M-backend: offline evaluation and safety contracts
The P_POLISH_v3a prompt replaces SPEC's older relative hook layers, alarm rule and active-only readout. Real Qwen2 uses injection layer 16, readout 20, probe layers 16/20/22 and clamp 17. Absolute position zero is excluded. The supplied norm reference is configuration, not a fresh measurement. Defaults are alpha .45 (cap .5), all-concept readout, and an eight-token same-concept alarm using independent thresholds or calibrated z. Task-named concepts are exempt. Only an enabled Neural Immune System emits public tamper reports.

- Provision model files outside runtime; set `THOUGHTQUAKE_MODEL_PATH` or pass `--model-path`. Loading uses local files only, never automatic downloads. `thoughtquake build-library --model-path /local/qwen --variant others` builds the current format; `--variant neutral` is the labelled legacy ablation. All numeric arrays and provenance are covered by the library hash.
- `thoughtquake calibrate-alarm --library PATH --model-path /local/qwen --seed 1 --generations 60` uses fresh uninjected generations. Reusing readout-calibration seed or overlapping generated texts is rejected.
- `thoughtquake fit-readout --library PATH --model-path /local/qwen` generates the split corpus, fits shrinkage using validation only, saves its NPZ and classifier provenance, and reports both old and v4 test accuracy. `--data /local/readout-training.npz` fits an existing hash-verified local corpus without loading a model. Families, seeds and normalized text hashes must be disjoint across splits. Do not commit private corpora.
- Ablations: vary `--alphas` and compare the matched immune rows; real acceptance requires `others`. `build-library --variant neutral` retains the old contrast baseline for local analysis and compatibility tests, not the real acceptance command. Matched alpha-zero controls and immune off/on rows are automatic. Compare old/v4 columns on identical held-out examples, never across different samples. Missing v4 values stay unavailable, not zero accuracy.
- Fast backend tests: `pytest -q tests/test_backend_eval.py tests/test_engine_owner.py tests/test_telepathy_leak.py tests/test_scoring.py tests/test_tiny_backend.py`. Full `make check` also retains M4 and browser/film coverage. Real acceptance: `THOUGHTQUAKE_REAL=1 THOUGHTQUAKE_MODEL_PATH=/local/qwen THOUGHTQUAKE_LIBRARY=/local/library.npz pytest -q -m realmodel`; no local artifacts means skip, not success evidence.
- Evaluation intervals resample concepts (2000 seeded replicates), and every metric includes its valid n and cluster count. Wilson intervals are additional answer-level summaries, not a substitute for cluster uncertainty. Task retention is explicitly a lexical/repetition proxy. Real relevance, real false alarms and trained readout accuracy require actual model runs; supplied prompt figures are not outputs.
- Engine mutation belongs to one queue consumer. Use typed commands and public mixer methods. Before reveal, every public snapshot/frame passes the strict presentation projection, and raw private recording rows stay buffered until reveal. Semantic payloads and map keys are checked for leaks; fixed event-schema keys remain unchanged.
- Viewer points persist atomically under `THOUGHTQUAKE_DATA_DIR` (default local config directory). APIs expose viewer ids/names/points, hide faction boards before reveal, and never include a hidden target. Keep development fixtures disabled in production.
- Follow `.codex/skills/thoughtquake-eval/SKILL.md` for evidence review and reruns. The research package and paper belong to P_POLISH_v3c.
