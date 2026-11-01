# Quick start in 3 steps

1. **[Download NOUS](https://github.com/manazafzal/codex-twitchcon-2026/archive/refs/heads/main.zip)** and choose **Extract all**. Open the extracted folder.
2. **Double-click `setup.bat`.** It installs the helpers, downloads the small AI, and opens NOUS in your browser. Keep its window open while you play. Internet is needed for this first setup.
3. **Click “Try the demo”.** Watch a full round in under 30 seconds. No Twitch login needed. If the AI isn't ready, NOUS clearly shows a recorded round with pretend chat.

## Meet NOUS

Chat tries to make an AI think about a team's idea. The AI tries to stay on task. Guess its hidden thought to win points. **NOUS** is the Greek word for mind.

In Twitch chat: **`!join`** picks your team, **`!push word`** backs an idea, **`!guess word`** makes a guess, and **`!rank`** shows your score. Ordinary team words or team emotes count a little too. Your first contribution gets a friendly welcome; repeated messages cannot win extra points.

## Connect your Twitch

Choose **Connect my Twitch** on the welcome screen and follow the three ticked steps. Twitch requires a free Public app code; the screen links to its registration page and shows where to copy it. NOUS then opens Twitch sign-in, checks your channel, and prepares the local AI. No config files to edit. First-time AI preparation can take several minutes; the recording is ready while you wait.

Open **controls** to start a round with a button or **R**. Streamers and moderators can also type **`!round`** or **`!immune on`**. Add the game's **`/overlay/`** address to OBS at **1920 × 1080**. Keep the private welcome/control address to yourself.

If setup pauses, check your internet and double-click `setup.bat` again. Scores are saved locally. If the AI download pauses, you can still use the recording. On a PC without the Windows app installer, setup explains how to install Python and retry.

## Developers and other systems

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
nous start          # Welcome screen
nous demo           # Offline recorded demo; no model or Twitch needed
make check
```

`setup.bat` is for Windows. The commands above work on Linux/macOS too. Model downloads happen only in explicit setup (`python -m nous.install`), never as a side effect of opening the recorded demo.

## Engine and advanced controls

Open **http://127.0.0.1:8080/** for the overlay, or
**http://127.0.0.1:8080/fixture.html** for the development hero view when
`NOUS_DEV_FIXTURES=1` is set.
The fixture uses a canned event list and the same renderer as the live view.
Append `?bg=transparent` for OBS. The canvas scales from 1920×1080.

Every demo is labelled **SIMULATED ×40** and **TINY MODEL / CI**. Mock text is
scripted to test presentation; its vectors and scores are test fixtures, not
model-quality evidence. `nous demo --mock` explicitly uses the deterministic development engine.
The default `nous demo` uses the shipped recording. Neither downloads
weights. Install `.[dev,model]` for Tiny tests; tests allow only local loopback sockets.

`--users N`, `--script golden/demo_script.json`, `--port 8080`, and `--no-browser`
customise the demo. The seeded crowd uses `sim_` names and changing faction waves.
It defaults off when its `twitch_connected` integration flag is set. Live Twitch setup is covered in the [streamer guide](docs/streamer-guide.md).

Record and replay:

```sh
nous demo --mock --record work/demo.jsonl
nous replay work/demo.jsonl --frames
nous replay work/demo.jsonl --engine
```

Frame replay needs no model and renders recorded output, with the source badge
changed to **REPLAY**. Engine replay re-feeds recorded pushes, seed, logical clock,
and mode controls through fresh model calls; recorded token text is not copied.
It checks the library hash and schedule. Tiny recordings reconstruct the same
random-init backend; real-model engine replay requires `--library PATH` and the
original model. Reproducibility is limited to the same model, configuration, and
hardware. No recorded real-chat golden run is included.

Broadcaster controls are at **http://127.0.0.1:8080/control**. Each run prints a
fresh random control token in the console. Paste it into the control page; it
stays in page memory and is never included in overlay URLs or `/api/state`.
Choose War / Attack / Telepathy there. Press **I** on the control page to toggle
the Neural Immune System, or use its ON/OFF buttons. Protected API calls are:

```sh
curl -X POST http://127.0.0.1:8080/api/mode \
  -H 'Authorization: Bearer TOKEN_PRINTED_AT_STARTUP' \
  -H 'Content-Type: application/json' -d '{"mode":"attack"}'
curl -X POST http://127.0.0.1:8080/api/immune \
  -H 'Authorization: Bearer TOKEN_PRINTED_AT_STARTUP' \
  -H 'Content-Type: application/json' -d '{"enabled":true}'
```

War produces short answers with the last three retained in the history column.
Attack runs one fixed injection and prompt twice with identical random state,
IMMUNE OFF then ON. It temporarily overrides the War immune setting.

Telepathy selects a library concept outside the active war and injects it at
β=2 for an everyday prompt. After generation, `!guess <word>` opens for 30 seconds.
Correct guesses earn decreasing viewer points, with the first correct guess receiving most.
The top five viewers appear on reveal; stream and all-time totals persist locally.
The current stream resumes after a restart. Set `NOUS_STREAM_ID` to a new value
for a new stream; all-time totals carry forward. The reveal names the secret, winner, and Mind-Reader's actual top
guess. Names, applied-faction metadata, and readout labels are masked on the
public WebSocket and API snapshot before reveal. Raw private recording rows are held until reveal and discarded if the round is
cancelled. Completed rounds retain plans for reproducible engine replay.

Twitch viewers cannot switch modes. Broadcasters and moderators may send
`!immune on` or `!immune off`; roles are checked from Twitch user IDs and badges.
During Attack/Telepathy, changes wait for War so the comparison or challenge
retains its prescribed settings. Chat announcements occur at round boundaries
and in response to `!rank`, subject to the existing five-second limiter.
Round MVP announcements have an additional cooldown.

The server exposes `/ws`, `/api/state`, and `/api/leaderboard`. Reconnecting sockets receive the full
current snapshot, including answer history. Slow clients are disconnected and
can reconnect for a fresh snapshot. Server and crowd tasks stop on shutdown.

The mixer reserves quiet-chat Neutral share first, scales capped faction shares
by activity, and moves cap excess to Neutral. Dose and strength use the top three
factions. `answer` scheduling freezes faction and strength for each answer;
`sentence` and `token` are experimental. Colours default to territory. Mind-Reader
colours require a real-model eval with window agreement ≥ 0.75 for the schedule.

The Neural Immune System clamps projections along known library injection
directions. It does not defend against arbitrary prompt injection.
`nous build-library --model-path /local/qwen` uses local Qwen2.5 weights
to generate contrast sets and neutral calibration. Runtime never downloads weights.

Offline evaluation and readout fitting:

```sh
nous calibrate-alarm --library library/qwen2.5-0.5b-instruct.npz --seed 1
nous fit-readout --library library/qwen2.5-0.5b-instruct.npz
nous eval --library library/qwen2.5-0.5b-instruct.npz --output results
nous eval --mock --output work/eval-ci
```

Set `NOUS_MODEL_PATH` to locally provisioned weights. Evaluation writes
ordered JSON/Markdown tables with sample counts, concept-cluster uncertainty,
matched controls and provenance. Missing trained artifacts stop a real run; they
never trigger a mock substitute. CI output is explicitly **TINY MODEL / CI**.
Task retention uses a documented lexical/repetition proxy and needs human review.
See [architecture and evidence limits](docs/architecture.md). No trained-model
quality, throughput or false-alarm result has been verified in this checkout.

Live chat setup: register a **Public** Twitch app, set
`NOUS_TWITCH_CLIENT_ID`, run `nous auth`, then
`nous run --channel NAME [--sim] [--record FILE]`. The source badge is
**LIVE**. Simulation is disabled unless explicitly requested and then retains its
own badge. A built library can be supplied with `--library`; otherwise the model
output remains explicitly labelled **TINY MODEL / CI**. See the streamer guide
for credential storage, bot announcements, OBS setup, and the required live check.

Colouring defaults to `--schedule-mode answer --colour-source applied`: one faction
per answer, including prompt prefill. `sentence` and `token` remain experimental.
Readout colouring aggregates an answer or a window (12 tokens by default), then
assigns one colour to that group. It buffers those groups instead of assigning
colours to individual words. Per-token scores still feed the 60-token chart.
Use `--colour-source readout --eval-file results/eval.json` only with real-model
evidence: `source: "realmodel"` and
`schedule_modes.<mode>.window_agreement >= 0.75`. The overlay labels the source
as **territory** or **Mind-Reader colours**. Optional reveal accuracy comes only
from `telepathy: {"accuracy": ..., "n": ...}` in that real-model evidence file.
No lead-time claim is made. Real-model quality, coherence, and throughput remain
unverified; fixture output retains its **TINY MODEL / CI** label.

Research write-up: [plain-English paper and evidence](docs/paper.md), [registered hypotheses](docs/hypotheses.md) and [reproduction commands](.codex/skills/nous-research/SKILL.md). Rows marked unrun are unavailable evidence, not measured effects.

## How we built this with Codex

We built NOUS milestone by milestone in one shared Codex thread. Codex wrote the engine, eval CLI, ablation runner, table and figure generator, concept builder and every test. We used git commits, executable checks and saved logs to track what worked, what failed and what still needs a real machine or trained model.

Our [build story](docs/BUILT_WITH_CODEX.md) links each prompt to its implementation, tests, fixes and commits, including the usage-limit pauses. The [topic-builder guide](docs/topic-builder.md) explains the optional `!propose word` command, strict admission checks and honest pack rejections. The beginner quick start above stays the same.
