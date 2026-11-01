# THOUGHTQUAKE

Chat factions contest the Subject's mind territory, watched by a Mind-Reader
and a Neural Immune System. M1–M3 provide the local engine, browser overlay, labelled offline crowd,
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

Broadcaster controls use a local bearer token. Set `THOUGHTQUAKE_LOCAL_TOKEN`
before starting the server, or use the generated 0600 temporary token file whose
path is logged at startup. The file is removed on normal shutdown. Tokens are
never included in `/api/state`, WebSocket snapshots, or overlay URLs.

```sh
curl -X POST http://127.0.0.1:8080/api/mode \
  -H "Authorization: Bearer $THOUGHTQUAKE_LOCAL_TOKEN" \
  -H 'Content-Type: application/json' -d '{"mode":"attack"}'
```

Modes are `war`, `attack`, and `telepathy`; changes apply between answers. Attack
uses the same prompt, injection draw, and random state for the OFF/ON comparison.
Telepathy currently supplies the masked presentation, countdown, reveal, and
scoreboard event fields. Chat guess adjudication and scoring (§11) remain for the
game milestone. Stats and real-model claims await the eval harness.

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
outside M3. No real-model calibration, quality, throughput, or lead-time claim is made.

Live chat setup: register a **Public** Twitch app, set
`THOUGHTQUAKE_TWITCH_CLIENT_ID`, run `thoughtquake auth`, then
`thoughtquake run --channel NAME [--sim] [--record FILE]`. The source badge is
**LIVE**. Simulation is disabled unless explicitly requested and then retains its
own badge. A built library can be supplied with `--library`; otherwise the model
output remains explicitly labelled **TINY MODEL / CI**. See the streamer guide
for credential storage, bot announcements, OBS setup, and the required live check.
