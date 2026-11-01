# MIND WARS

M1 implements the local thought injection engine and offline test fixtures.
Twitch and the overlay are reserved for later milestones.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check
make demo
```

`make demo` emits JSON events from a deterministic mock, labelled `SIMULATED ×0`.
No synthetic crowd is implemented in M1. These fixtures are **TINY MODEL / CI**;
they prove plumbing, and provide no model-quality results.

Install `.[dev,model]` to run the optional random-init Tiny Qwen2 tests offline.
Tests never fetch model weights. `mindwars build-library` explicitly loads the
real Qwen2.5 model and generates the contrast sets and neutral calibration data.
`make eval` is reserved for the later eval milestone and currently exits with an
explanation. No real-model library or evaluation results are committed.

The Neural Immune System clamps projections along known library injection
directions. It does not defend against arbitrary prompt injection.

The mixer reserves quiet-chat Neutral share first, scales the capped faction
shares by the remaining activity, and adds cap excess to Neutral. Dose totals
and strength use only the retained top three factions. Pushes use chronological
monotonic timestamps; tests inject a fake clock. `answer` scheduling freezes the
selected faction and strength until the next answer; experimental `sentence`
and `token` modes redraw at their respective boundaries.

The engine defaults to territory colours. Mind-Reader colours require an eval
file with `source: "realmodel"` and
`schedule_modes.<mode>.window_agreement >= 0.75`. Readout scores use a rolling
12-token mean. The asynchronous stream keeps model calls on one worker and
holds the previous answer for at least two seconds between answers; its history
retains the last three answers. The synchronous event iterator has no delays.
