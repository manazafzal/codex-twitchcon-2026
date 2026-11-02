# Real-model results

Streamer-supplied results note, reproduced from the submitted attachment. These checks were reported by the project author; Codex verified the supplied library's file and content hashes, but did not independently rerun the real-model experiments. The first-person statements below belong to the reporter.

These are my own checks of NOUS on the real model, on 2 November 2026.

- Model: Qwen2.5-0.5B-Instruct, run locally.
- Machine: a Linux computer with no graphics card (CPU only). Not tested on a Windows laptop or a graphics card yet.
- Code: `98c5785` for the library build and fit, and `bca8452` (the final code) for the idle and pushed checks.
- This is not a live audience test. The crowd in the video is simulated and labelled.

## What I measured

| Check | Result |
| --- | --- |
| Mind-Reader names the right idea (first guess), 360 held-out answers, 30 ideas | 94.2% (91.7 to 96.4% interval across ideas) |
| Right idea in its first three guesses | 96.1% (94.2 to 98.1%) |
| Same test before fitting the Mind-Reader | 47.5% first guess, 66.7% first three |
| Nobody pushing: says "No clear thought yet" | 192 of 192 |
| Rounds with pushes: reading names the pushed idea | 320 of 320 |
| Neural Immune System: false alarms on normal answers | 0 of 20 |
| Neural Immune System: pushed answers caught | 20 of 20 |

## Notes and limits

- The library used is `library/nous-fitted.npz`. Copy it to `~/.config/nous/concepts.npz` (on Windows `C:\Users\<you>\.config\nous\concepts.npz`). SHA-256: `ee70c50cae57f841423160515dcd8d43bee52a6265b4ace9660b645bf1fb7e00`.
- The idle and pushed checks used the cut-off `355.85`, which was calibrated on 60 idle answers. The smallest "pushed" score was about 430, so the gap is roughly 74. Weaker pushes and fewer pushers were not tested.
- The immune system check (10 ideas, 2 prompts each, push strength 0.45, 32 words) was run earlier in the day on an earlier library and earlier code (`ebd5a64`). I did not rerun it on the final library.
- Before calibration, the fitted Mind-Reader named a wrong idea on all 192 idle readings. That was fixed in `da4fad7`.
- The 24 starter topic packs in `data/packs` have not been tested on the real model. They are experimental.
- Older text in `README.md`, `docs/architecture.md`, `docs/paper.md` and `docs/backend-evaluation.md` says no real-model result was verified. That was true when it was written. This file replaces it for the numbers above. The research tables in `docs/paper.md` still show the full preregistered study as not run.
- Not tested: the Windows installer, a real Twitch audience, OBS on a streaming PC, and any graphics-card speed.
