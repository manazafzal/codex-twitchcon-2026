# AGENTS.md — THOUGHTQUAKE

Read this file and `SPEC.md` before every task. If they conflict with a prompt, the prompt wins for that task only; tell me about the conflict in your final message.

## What this repo is
THOUGHTQUAKE is a Twitch game where chat factions fight over the thoughts of a small local AI (the "Subject"), while a live Mind-Reader and a Neural Immune System watch. A Python server runs on the streamer's PC. Viewers only type in normal Twitch chat. The overlay is a browser source. No Twitch Extension. No paid API. No cloud inference.

Hackathon: Codex x TwitchCon (Devpost). The repo must be new work, built mostly with Codex, and judges may only watch the video and read the text. Everything user-visible must be accurate and checkable.

## Hard rules (do not break)
1. **Vocabulary.** In user-facing text (overlay, chat replies, README top section, CLI help, docs outside `docs/related-work.md`) use: *thought injection*, *mind territory*, *Mind Share*, *Mind-Reader*, *Neural Immune System*, *Telepathy*, *faction*, *the Subject*. Do NOT use: "steering", "steer", "obsessed", "obsession", "can't stop talking about", "Golden Gate", "Claude", "bridge" (as an example concept), "turn up the dial", "feature clamping". The words "activation steering", "ActAdd", "CAA", "Golden Gate Claude", "brainscope" appear ONLY in `docs/related-work.md` and code comments/docstrings. A test (`tests/test_vocabulary.py`) enforces this on overlay files, README, and CLI help.
2. **Never single-concept saturation.** The overlay must never show one faction holding more than the dominance cap (default 75 % of applied injections) except in the explicitly labelled "Immune ON/OFF" comparison. Prompts given to the Subject are always everyday tasks ("explain how to make tea"), never "tell me about yourself".
3. **No fake results.** Numbers shown in the overlay, README, or video cards must come from `results/eval.json` produced by `make eval` (real model) or be labelled `TINY MODEL / CI`. Never hard-code a result.
4. **Labels.** Every run shows exactly one source badge: `LIVE` (real Twitch chat), `REPLAY` (recorded real chat), or `SIMULATED ×N` (synthetic chatters). Simulated chatters never appear without the badge, and the sim is off by default when Twitch is connected.
5. **No secrets in git.** Tokens live in `~/.config/thoughtquake/` (mode 0600). `.env`, `*.token.json` are git-ignored. Client ID is read from env `THOUGHTQUAKE_TWITCH_CLIENT_ID`. No client secret is needed (public client, device code flow).
6. **Do not download anything at test time.** Tests must pass with no internet, no GPU, and no real model weights. Use `TinyBackend` (random-init small Qwen2-architecture model built from a config, or pure-numpy mock) and `MockBackend`. Real-model tests are marked `@pytest.mark.realmodel` and are skipped unless `THOUGHTQUAKE_REAL_MODEL=1`.
7. **No code or data copied from any earlier scratch prototype.** Implement from `SPEC.md`.
8. Small dependency set: `numpy`, `aiohttp`, `pytest`, `ruff`; extras: `torch`, `transformers` (extra `model`). No Node build step: the overlay is plain HTML/CSS/JS files served statically.
9. Python 3.11+. Type hints everywhere in `src/`. `ruff check` and `pytest -q` must be green before you finish a task.

## Commands
- Install (dev, CI-safe): `pip install -e ".[dev]"`; with tiny-model tests: `pip install -e ".[dev,model]"` (CPU torch).
- `make check` → ruff + pytest (non-real-model).
- `make eval` → runs the eval harness. With real model: `THOUGHTQUAKE_REAL_MODEL=1 make eval`. Writes `results/eval.json` and `results/eval.md`, and refreshes the table between `<!-- EVAL:START -->` and `<!-- EVAL:END -->` in `README.md`.
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
