# AGENTS.md — NOUS

Read this file and `SPEC.md` before every task. If they conflict with a prompt, the prompt wins for that task only; tell me about the conflict in your final message.

## What this repo is
NOUS is a Twitch game where chat factions fight over the thoughts of a small local AI (the "Subject"), while a live Mind-Reader and a Neural Immune System watch. A Python server runs on the streamer's PC. Viewers only type in normal Twitch chat. The overlay is a browser source. No Twitch Extension. No paid API. No cloud inference.

Hackathon: Codex x TwitchCon (Devpost). The repo must be new work, built mostly with Codex, and judges may only watch the video and read the text. Everything user-visible must be accurate and checkable.

## Hard rules (do not break)
1. **Vocabulary.** In user-facing text (overlay, chat replies, README top section, CLI help, docs outside `docs/related-work.md`) use: *thought injection*, *mind territory*, *Mind Share*, *Mind-Reader*, *Neural Immune System*, *Telepathy*, *faction*, *the Subject*. Do NOT use: "steering", "steer", "obsessed", "obsession", "can't stop talking about", "Golden Gate", "Claude", "bridge" (as an example concept), "turn up the dial", "feature clamping". The words "activation steering", "ActAdd", "CAA", "Golden Gate Claude", "brainscope" appear ONLY in `docs/related-work.md` and code comments/docstrings. The milestone test (`tests/test_vocabulary.py`) checks case-insensitive stems in all Python string literals (including docstrings) and text assets under `src/`, `docs/`, `tests/`, and `.codex/skills/`, plus README and CLI help. The only file exception is `docs/related-work.md`. Comments contain no runtime text; do not add prohibited terms or stems elsewhere.
2. **Never single-concept saturation.** The overlay must never show one faction holding more than the dominance cap (default 75 % of applied injections) except in the explicitly labelled "Immune ON/OFF" comparison. Prompts given to the Subject are always everyday tasks ("explain how to make tea"), never "tell me about yourself".
3. **No fake results.** Numbers shown in the overlay, README, or video cards must come from `results/eval.json` produced by `make eval` (real model) or be labelled `TINY MODEL / CI`. Never hard-code a result.
4. **Labels.** Every run shows exactly one source badge: `LIVE` (real Twitch chat), `REPLAY` (recorded real chat), or `SIMULATED ×N` (synthetic chatters). Simulated chatters never appear without the badge, and the sim is off by default when Twitch is connected.
5. **No secrets in git.** Tokens live in `~/.config/nous/` (mode 0600). `.env`, `*.token.json` are git-ignored. Client ID is read from env `NOUS_TWITCH_CLIENT_ID`. No client secret is needed (public client, device code flow).
6. **Do not download anything at test time.** Tests must pass with no internet, no GPU, and no real model weights. Use `TinyBackend` (random-init small Qwen2-architecture model built from a config, or pure-numpy mock) and `MockBackend`. Real-model tests are marked `@pytest.mark.realmodel` and are skipped unless `NOUS_REAL=1`.
7. **No code or data copied from any earlier scratch prototype.** Implement from `SPEC.md`.
8. Small dependency set: `numpy`, `aiohttp`, `pyyaml`; development: `pytest`, `ruff`, `mypy`, `types-PyYAML`; extras: `torch`, `transformers` (extra `model`). No Node build step: the overlay is plain HTML/CSS/JS files served statically.
9. Python 3.11+. Type hints everywhere in `src/`. `make check` (ruff, scoped mypy, and pytest) must be green before you finish a task.

## Commands
- Install (dev, CI-safe): `pip install -e ".[dev]"`; with tiny-model tests: `pip install -e ".[dev,model]"` (CPU torch).
- `make check` → ruff + mypy on engine/model/concepts/evaluation + pytest (non-real-model).
- `make eval` → the offline real-model harness, requiring a verified local library and weights. Equivalent: `nous eval --library library/qwen2.5-0.5b-instruct.npz --output results --alphas .3 .45 --seeds 1 --prompts 6 --concepts 30 --held-out 3 --seed 0`. Output is `eval.json` plus `eval.md`; no automatic README quality claims.
- CI-only evaluation: `nous eval --mock --output work/eval-ci`. The source is `mock` and quality is `TINY MODEL / CI`; never relabel this as real evidence.
- `nous demo` → offline demo mode (labelled simulated crowd), opens overlay URL.
- `nous replay golden/golden_run.jsonl` → deterministic replay of a recorded run.
- `nous auth` → Twitch device-code login. `nous run --channel NAME` → live.
- `nous build-library` → builds `library/<model>.npz` concept vectors for the real model.

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
`src/nous/` layout. `ruff` defaults plus line length 100. Dataclasses for events. `asyncio` for IO, torch calls via `run_in_executor` single worker. Log with `logging` (no prints in library code). Docstrings explain *why*, and may cite the research ancestors (ActAdd, CAA, Golden Gate Claude, brainscope).

## M-visual: overlay tests, film, and measurement
The Mind Atlas milestone prompt supersedes §15's old geometry, palette and 28 px minimum: the new stage uses a 780 px left column and a 17 px minimum. Keep the existing event fields; `token.sky` and `layout` add measured rendering data. The SD display requires saved neutral calibration; older libraries show no SD signal until rebuilt. Hidden rounds must project both coordinates and signal keys through the public presentation layer.

- `make check` includes `tests/test_overlay_visual.py`. With local `chromium` or `google-chrome`, it runs offline Chrome DevTools checks using SwiftShader; without Chrome those browser tests skip. No browser downloads, Node, browser frameworks or remote assets are used. Browser tests use loopback HTTP only.
- `pytest -q tests/test_overlay_visual.py` checks five scenes, errors, full names, minimum text size, transparency, quarter-size contrast, Canvas fallback, and two complete 600-frame films. This can take about twenty minutes on this software-only runner; the fixed 30 fps film cadence is not a playback-speed claim.
- `NOUS_DEV_FIXTURES=1 nous demo --mock` enables `/fixture.html?scene=war` (also `attack`, `immune`, `telepathy`, `reveal`). Default fixtures use recorded mock measurements; `&backend=tiny` selects captured random-init model measurements. Both show `TINY MODEL / CI`. Fixture pages, scripts and trace data return 404 without that environment setting.
- `python -m tools.capture_trace` refreshes the committed development traces using actual backend calls; requires the `model` extra. Never substitute invented token measurements or present these traces as trained-model evidence.
- `python -m tools.film --verify --output /tmp/nous.mp4` records 20 virtual seconds at 30 fps and compares every frame hash on a second run. Chrome is required; ffmpeg is needed only for MP4 output. `--hashes /tmp/film.json` selects the hash report; `--scene` and `--backend` select the recording. `?manual&scale=.5` exposes `NousOverlay.step(seconds)`; every presentation timer advances on that clock.
- `python -m tools.measure_overlay` refreshes `docs/screenshots/` and `docs/overlay-measurements.json`. Run it alone for valid timing. It measures 120 actual rAF intervals at `?scale=.5`; see `docs/perf.md` for limits. Manual screenshot/film timing is not a playback-fps measurement.
- Bundled fonts and OFL notices live in `src/nous/overlay/fonts/`; server font routes are allowlisted. `?nogl` selects Canvas2D; `?bg=transparent` removes the ground. Never publish development traces by enabling fixtures on a live server.


## M-backend: offline evaluation and safety contracts
The P_POLISH_v3a prompt replaces SPEC's older relative hook layers, alarm rule and active-only readout. Real Qwen2 uses injection layer 16, readout 20, probe layers 16/20/22 and clamp 17. Absolute position zero is excluded. The supplied norm reference is configuration, not a fresh measurement. Defaults are alpha .45 (cap .5), all-concept readout, and an eight-token same-concept alarm using independent thresholds or calibrated z. Task-named concepts are exempt. Only an enabled Neural Immune System emits public tamper reports.

- Provision model files outside runtime; set `NOUS_MODEL_PATH` or pass `--model-path`. Loading uses local files only, never automatic downloads. `nous build-library --model-path /local/qwen --variant others` builds the current format; `--variant neutral` is the labelled legacy ablation. All numeric arrays and provenance are covered by the library hash.
- `nous calibrate-alarm --library PATH --model-path /local/qwen --seed 1 --generations 60` uses fresh uninjected generations. Reusing readout-calibration seed or overlapping generated texts is rejected.
- `nous fit-readout --library PATH --model-path /local/qwen` generates the split corpus, fits shrinkage using validation only, saves its NPZ and classifier provenance, and reports both old and v4 test accuracy. `--data /local/readout-training.npz` fits an existing hash-verified local corpus without loading a model. Families, seeds and normalized text hashes must be disjoint across splits. Do not commit private corpora.
- Ablations: vary `--alphas` and compare the matched immune rows; real acceptance requires `others`. `build-library --variant neutral` retains the old contrast baseline for local analysis and compatibility tests, not the real acceptance command. Matched alpha-zero controls and immune off/on rows are automatic. Compare old/v4 columns on identical held-out examples, never across different samples. Missing v4 values stay unavailable, not zero accuracy.
- Fast backend tests: `pytest -q tests/test_backend_eval.py tests/test_engine_owner.py tests/test_telepathy_leak.py tests/test_scoring.py tests/test_tiny_backend.py`. Full `make check` also retains M4 and browser/film coverage. Real acceptance: `NOUS_REAL=1 NOUS_MODEL_PATH=/local/qwen NOUS_LIBRARY=/local/library.npz pytest -q -m realmodel`; no local artifacts means skip, not success evidence.
- Evaluation intervals resample concepts (2000 seeded replicates), and every metric includes its valid n and cluster count. Wilson intervals are additional answer-level summaries, not a substitute for cluster uncertainty. Task retention is explicitly a lexical/repetition proxy. Real relevance, real false alarms and trained readout accuracy require actual model runs; supplied prompt figures are not outputs.
- Engine mutation belongs to one queue consumer. Use typed commands and public mixer methods. Before reveal, every public snapshot/frame passes the strict presentation projection, and raw private recording rows stay buffered until reveal. Semantic payloads and map keys are checked for leaks; fixed event-schema keys remain unchanged.
- Viewer points persist atomically under `NOUS_DATA_DIR` (default local config directory). APIs expose viewer ids/names/points, hide faction boards before reveal, and never include a hidden target. Keep development fixtures disabled in production.
- Follow `.codex/skills/nous-eval/SKILL.md` for evidence review and reruns. The research package and paper belong to P_POLISH_v3c.


## NOUS completion checks
- The current product/package/CLI and environment prefix are NOUS/`nous`/`NOUS_`. Preserve this naming in new files and browser globals. The evaluation skill is `.codex/skills/nous-eval/SKILL.md`.
- Fairness regressions: `pytest -q tests/test_scoring.py tests/test_round_points.py tests/test_telepathy_leak.py`. They cover temporal push credit, decreasing guess awards, guess eligibility, the round cap, one Attack payout, current-round live moderator attribution, stream resume/migration, a killed atomic write and public secrecy.
- `NOUS_STREAM_ID` selects a stream. Without a new value, the saved current stream resumes on process restart; changing it clears only stream totals. Existing version-one score files migrate to the current schema. `NOUS_DATA_DIR` still controls the local store location.
- Fitted v4 labels/colours are answer/window decisions. Keep per-token cosine/z untouched for the alarm; never substitute classifier confidence for projection thresholds. Tests must make classifier and detector disagree to catch accidental coupling.
- `pytest -q tests/test_overlay_visual.py -k mvp` verifies MVP/board restoration and blind hiding. Full `make check` includes all browser and deterministic film tests. Keep fixed schema fields and source badges unchanged.


## M-easy: beginner setup and participation
The beginner prompt supersedes the earlier technical default overlay, default test-model demo and round-boundary-only bot replies. Keep source badges and the existing event fields. Technical labels belong in the closed-by-default Nerd panel; it must show no secret before reveal. The default screen uses team language, AI's guess, a round headline/countdown and a readable reveal.

- Windows: extract the source ZIP, double-click `setup.bat`, then click Try the demo. `tools/setup.ps1` provisions Python/helpers and explicitly downloads the small model. Setup downloads are authorized installation actions, not implicit runtime or test behavior. Failures have plain retry instructions; a paused model download still allows the recorded demo. Native Windows execution requires a Windows check.
- `nous start` opens the private welcome screen. `nous demo` opens the same demo directly, with no Twitch login or model preparation. If locally prepared model/library files exist it can use them; otherwise it plays three shipped, clearly labelled recordings of actual test-backend calls and pretend chat. Each recorded slot is 24 seconds. Never present these as trained-model evidence. `nous demo --mock` remains an explicit development engine, and `make demo` uses the beginner default.
- `python -m tools.capture_demo` refreshes the shipped recordings from local test-backend calls, with a documented presentation clock. Raw recording JSON is a package resource, never a public static route. Development fixture gating remains intact.
- The welcome wizard uses a per-run bootstrap fragment, strips it immediately and sets a local HttpOnly/SameSite cookie. Cookie-authorized writes require an exact same-origin header. Public `/ws`, `/api/state`, overlay URLs and the Nerd panel never carry this secret or Twitch credentials. A Public Twitch app code is still required by Twitch; enter it in the wizard, not a config file. A connection tick requires the actual chat connection, not just a successful HTTP request.
- Chat: `!join` assigns a team, `!push word` is deliberate, `!guess word` guesses, `!rank` reports points. `!round` and bare `!immune`/on/off require broadcaster/mod roles. R on the private control page starts a round. No other chat mode commands are enabled.
- Ordinary matching words/team emotes use a typed internal Participation command and contribute 0.1 at most once per viewer per 20 seconds. They have separate mixer/scoring allowances so they cannot consume deliberate pushes. Do not add weighting fields to the public Push schema. Welcome messages are bounded, once per viewer, at least ten seconds apart, and use the existing five-second chat sender limiter. Team words/names are masked for blind welcomes.
- Source changes stop the prior engine owner before starting another, refresh the blind identity map, and keep demo points separate from saved live totals. Retain the full leak/scoring suites.
- Fast beginner checks: `pytest -q tests/test_easy_start.py tests/test_easy_chat.py tests/test_easy_overlay.py`. Browser tests skip if local Chrome is absent. `make check` retains scoped mypy, all existing tests and the complete film comparison. Do not download a browser/model during tests. Capture final screens with `python -m tools.measure_overlay` while other heavy tests are stopped.

- The broadcaster may use explicit viewer commands when signed in with the same account as the bot. Ordinary messages from that account remain ignored to prevent announcement loops; a separate bot account's own messages remain ignored. All thirty concept teams have a matching standard emoji. Recording controls return a plain explanation instead of silently accepting changes they cannot apply. A failed app code must remain editable in the wizard.

## M-research: registered evidence and paper

For this milestone, research artifacts under `research/` are the paper's evidence source, replacing rule three's earlier eval-only location for this paper. The model remains local-only. Larger alpha values and variable layers belong exclusively to the research adapter; production caps and defaults stay unchanged. The vocabulary rule still covers every new string, paper, skill and fixture; do not introduce prohibited terms or stems.

- Before measurements, commit `docs/hypotheses.md` alone. Its registration commit and SHA-256 are checked against git history and cited by the generated paper. Do not amend it after observing outcomes. CI needs full history (`fetch-depth: 0`) to verify the registration.
- Follow `.codex/skills/nous-research/SKILL.md`. Install optional plotting support with `pip install -e '.[dev,model,research]'`. Set `NOUS_MODEL_PATH` to already provisioned local weights, then run `nous research run --config configs/ablations.yaml --seed 0 --output research/`. No model downloads occur. Missing weights produce explicitly unrun rows with actual n=0, not mock evidence.
- The one-factor grids, matched controls, classifier split/selection rules and alarm sweeps are fixed in the registration and configuration. Every metric carries n, clusters and concept-bootstrap intervals; paired effects retain matched answer identities. A zero control leaves relative reduction undefined. Inconclusive comparisons and failed cells are retained.
- `make paper` renders `docs/paper.md` from `docs/paper.src.md`. Use explicit table/figure placeholders for numerical findings. `make check` verifies the rendered document and artifact digests, runs ruff and mypy including `src/nous/research`, then the existing complete pytest suite. A stale paper fails; regenerate it explicitly.
- Fast research checks: `pytest -q tests/test_research.py`. Optional plot tests skip without matplotlib; trained weights and network are never required in tests. The actual trained-model grid remains unverified until local artifacts exist and the runner completes. Do not replace those missing measurements with supplied hints or synthetic test outcomes.

## M-concepts: private topic admission

The topic-builder prompt replaces SPEC's unfinished custom-topic shortcut: viewers use the optional `!propose WORD`, not an unknown push. Keep the bonus command out of the play strip. Follow `docs/topic-builder.md` for CLI, pack and test commands. The vocabulary test now also scans `data/`, JSON and text assets. Packaged policy digests derive from rule one; regenerate them with `python -m tools.build_name_policy` after changing that rule.

- Preserve supplied examples exactly. Generated sets use the saved YAML template, a fixed seed, deduplication and length-matched neutral controls. Record source texts, raw means, seeds, model and hashes. Rebuild and disclose missing legacy contrast sources; unit vectors cannot recover their means.
- Do not relax admission bars. Half-text all-catalog top-1 must be at least .8, maximum existing-direction cosine at most .6, matched six-prompt injection gain at least .10 at alpha .45, and task proxy at least .6. Failed/unrun checks reject a candidate. Fresh alarm calibration and complete v4 fitting must also finish before publication.
- Background builders and generation share serialized model access. Only the owner installs between rounds; no active blind round may receive a catalog update. Refresh masking patterns, snapshots, parser names and layout together. The existing round event's catalog phase is recorded; changing-basis recordings require frame replay.
- Pack reports produced here with no trained artifacts are rejected/unrun, not real-model results. Never promote them or fabricate values. Test with `pytest -q tests/test_concept_builder.py`; real tests need explicit NOUS_REAL and local paths. Full `make check` retains all existing secrecy, fairness and film coverage.
