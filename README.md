# THOUGHTQUAKE

Chat factions contest the Subject's mind territory, watched by a Mind-Reader
and a Neural Immune System. M1–M4 provide the local engine, browser overlay, labelled offline crowd,
recording, replay, and Twitch Device Code / EventSub integration.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check
thoughtquake demo --mock
```

Open **http://127.0.0.1:8080/** for the overlay, or
**http://127.0.0.1:8080/fixture.html** for the screenshot-ready static hero view.
The fixture uses a canned event list and the same renderer as the live view.
Append `?bg=transparent` for OBS. The canvas scales from 1920×1080.

Every demo is labelled **SIMULATED ×40** and **TINY MODEL / CI**. Mock text is
scripted to test presentation; its vectors and scores are test fixtures, not
model-quality evidence. `thoughtquake demo` uses random-init Tiny Qwen2 when the
optional model dependencies are installed, otherwise the mock. Neither downloads
weights. Install `.[dev,model]` for Tiny tests; tests allow only local loopback sockets.

`--users N`, `--script golden/demo_script.json`, `--port 8080`, and `--no-browser`
customise the demo. The seeded crowd uses `sim_` names and changing faction waves.
It defaults off when its `twitch_connected` integration flag is set. Live Twitch setup is covered in the [streamer guide](docs/streamer-guide.md).

Record and replay:

```sh
thoughtquake demo --mock --record work/demo.jsonl
thoughtquake replay work/demo.jsonl --frames
thoughtquake replay work/demo.jsonl --engine
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
The first correct alias wins one point; the in-memory scoreboard retains the top
five players. The reveal names the secret, winner, and Mind-Reader's actual top
guess. Names, applied-faction metadata, and readout labels are masked on the
public WebSocket and API snapshot before reveal. Private recordings retain round
plans for reproducible engine replay; share recordings after the round ends.

Twitch viewers cannot switch modes. Broadcasters and moderators may send
`!immune on` or `!immune off`; roles are checked from Twitch user IDs and badges.
During Attack/Telepathy, changes wait for War so the comparison or challenge
retains its prescribed settings. Chat announcements occur at round boundaries
only, subject to the existing five-second limiter.

The server exposes `/ws` and `/api/state`. Reconnecting sockets receive the full
current snapshot, including answer history. Slow clients are disconnected and
can reconnect for a fresh snapshot. Server and crowd tasks stop on shutdown.

The mixer reserves quiet-chat Neutral share first, scales capped faction shares
by activity, and moves cap excess to Neutral. Dose and strength use the top three
factions. `answer` scheduling freezes faction and strength for each answer;
`sentence` and `token` are experimental. Colours default to territory. Mind-Reader
colours require a real-model eval with window agreement ≥ 0.75 for the schedule.

The Neural Immune System clamps projections along known library injection
directions. It does not defend against arbitrary prompt injection.
`thoughtquake build-library` explicitly loads the real Qwen2.5 model to generate
contrast sets and calibration data. `make eval` reports that the eval harness is
outside M4. No real-model calibration, quality, throughput, or lead-time claim is made.

Live chat setup: register a **Public** Twitch app, set
`THOUGHTQUAKE_TWITCH_CLIENT_ID`, run `thoughtquake auth`, then
`thoughtquake run --channel NAME [--sim] [--record FILE]`. The source badge is
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
