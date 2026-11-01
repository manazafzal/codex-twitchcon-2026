# How we built NOUS with Codex

We built NOUS in this shared Codex thread: chat tries to bring an idea into a local AI's answer, a Mind-Reader identifies the idea, and a separate defence tries to protect the task. Our prompts supplied the goals, limits and acceptance checks. Codex wrote the implementation, the eval CLI, the ablation runner, the table and figure generator, the concept builder, and every test in this repository.

We kept the work in milestone commits instead of presenting a finished demo without its history. Below we describe what each prompt asked for, what we built, what we checked, and what still needs real-world verification. We use saved logs and repository changes as evidence; we do not turn test-model output, planning notes or a remembered test count into trained-model results. The complete history is [on GitHub](https://github.com/manazafzal/codex-twitchcon-2026/commits/main/).

## M1 — start with the engine, without Twitch or an overlay

We asked Codex to read the specification and build only the Python package and engine. We added the source-layout package, installation extras, Makefile and CI; backend interfaces; deterministic numpy and random-init local model backends; a local trained-model loader; the original concept library; dose mixing, windowed readout, the projection clamp and typed events.

We added arithmetic tests for decay, per-viewer limits, top-three selection, Neutral allocation and the dominance cap; synthetic readout/clamp checks; library round trips; generation/event checks; optional real-hook tests using a random-init architecture; and the vocabulary test. We used those small tests to separate a working data path from a claim about a trained model. A successful mock or random-init run was never evidence of model quality. The original commit contains these tests; we do not have a separate saved M1 check transcript to quote a historical count from.

We kept Twitch and overlay work out of that first milestone. [M1 commit](https://github.com/manazafzal/codex-twitchcon-2026/commit/1a3f5a9).

## M2 — rename, then build the local stream shell

We next asked for a standalone product/package rename followed by an aiohttp server and plain browser overlay. We added static assets, the WebSocket event stream, state snapshots, local-token mode control, a seeded crowd with visibly tagged names, mandatory source badges, recording/replay, a fixture page and the demo CLI. We preserved the initial engine commit when reconciling the existing main history.

We added server, event-schema, simulated-crowd, session and replay tests. We checked that the overlay handled every event type without introducing a JavaScript build tool or a DOM dependency. That contract test checked the renderer's inputs, not its appearance; we added actual browser and image checks later. Keeping simulation labelled was part of the implementation and the tests, not a video-only caption.

[Rename](https://github.com/manazafzal/codex-twitchcon-2026/commit/95b559e), [M2 implementation](https://github.com/manazafzal/codex-twitchcon-2026/commit/746be1f), [history-preserving merge](https://github.com/manazafzal/codex-twitchcon-2026/commit/87ef2e3).

## M3 — connect Twitch with local test servers

We asked for Public-client device login, EventSub WebSocket chat, a bounded chat sender and alias parsing. We implemented token validation and refresh, atomic credential replacement, device polling and expiry handling, subscription setup, reconnect/resubscribe handling, duplicate-message suppression and a LIVE source badge. We wrote the streamer guide alongside the integration.

We added message fixtures and an in-process fake WebSocket/Helix service. We exercised pending-to-success login, refresh after an unauthorized response, reconnect paths and send-rate limits without contacting Twitch. We handled duplicate and own-bot messages so replies could not feed an announcement loop. These checks establish local behavior; we still need a real Twitch account to verify the documented endpoints, field names, scopes and delivery. We say that explicitly in the [streamer guide](streamer-guide.md).

[M3 commit](https://github.com/manazafzal/codex-twitchcon-2026/commit/57a6082).

## M4 — give the engine playable rounds and protected controls

We asked for War, an Attack comparison using the same prompt twice, and a Telepathy state machine with guesses, a reveal and a scoreboard. We added the round director, applied-versus-readout colour selection, answer history, round-boundary chat replies and a private control page. We restricted chat control of the defence to the broadcaster/moderators.

We added fake-clock tests for guesses, aliases, timeouts and round sequencing, plus presentation, control and colour tests. We made the Attack comparison preserve its prompt and random state between the defence-off and defence-on answers. We replaced the earlier per-word colour expectation with answer/window colouring; sentence and token schedules stayed experimental. We did not promote the planning document's exploratory observations into new measurements.

[M4 commit](https://github.com/manazafzal/codex-twitchcon-2026/commit/527efb3).

## M-visual — build and measure the Mind Atlas

We asked for the smooth living-night sky, with motion computed from model signals, a readable hero layout and deterministic filming. We built WebGL2 and Canvas renderers, a Canvas fallback, bundled fonts, transparent capture, scaling, virtual timers, full faction labels, ridgelines and mode transitions. We kept development traces gated and labelled their mock/random-init origin.

We wrote the browser client, screenshot/measurement tools, `tools/film.py` and the visual tests. We checked five scenes, browser errors, minimum text size, transparency, contrast, full-label overflow and matching frame hashes across complete repeated films. We fixed font readiness, virtual-clock dispatch, answer-mask remnants, history/push restoration, connection-chip restoration and title/history overlap. Those fixes are recorded in the implementation and its earlier audit notes.

We retained the measured limits in [performance notes](perf.md), [raw measurements](overlay-measurements.json) and the [saved check output](check-output.txt). Software-rendered Chrome checks do not establish hardware-GPU throughput or OBS composition. We did not copy an artwork or present the development traces as trained-model evidence.

[Renderer and tools](https://github.com/manazafzal/codex-twitchcon-2026/commit/c61831f), [measured scenes and fixes](https://github.com/manazafzal/codex-twitchcon-2026/commit/9c09b3e), [audit](https://github.com/manazafzal/codex-twitchcon-2026/commit/ccc338d).

## M-backend — evaluation, secrecy, fair points, and the NOUS name

We asked for the all-concept library/readout, the fitted multi-layer v4 classifier, a separate alarm, a queue-owned engine, strict hidden-round presentation and persistent viewer points. We wrote the eval CLI and its generated tables, cluster uncertainty, local-only model loading, calibrated libraries and validation-only classifier fitting. We kept classifier labels separate from projection/cosine alarm inputs.

We added tests for hashes, partition overlap, hook positions, alarm attribution/exemptions, failed producers, whole-round public secrecy and split-word masking. We added scoring, cooldown, rate-limit, round-cap, persistence and killed-write tests. We checked delayed push credit and prevented an Attack comparison from paying twice. We fixed a label path that still followed cosine instead of the fitted classifier, without changing the alarm signal. We kept faction data out of hidden leaderboards and deferred raw secret recording rows until reveal.

We hit a usage-limit pause during this work. Our continuation prompt asked us to inspect the working tree and finish the existing work, rather than start over or trust the suggested passing-test count. We also renamed the product, package, CLI, environment prefix, titles and repository skill to NOUS in a separate commit before completing the remaining backend changes.

We saved the [first backend check](backend-check-output.txt), [labelled CI evidence](backend-evaluation.md), [NOUS completion check](nous-check-output.txt) and [real-model blockers](nous-real-check-output.txt). No trained weights or fitted corpus were available here. We did not copy the prompt's benchmark hints, force the mock control hit rate to zero, or replace missing classifier values with invented accuracy.

[Initial backend](https://github.com/manazafzal/codex-twitchcon-2026/commit/cdd4a58), [CI evidence](https://github.com/manazafzal/codex-twitchcon-2026/commit/4f47c83), [NOUS rename](https://github.com/manazafzal/codex-twitchcon-2026/commit/226f7d2), [v4 label fix](https://github.com/manazafzal/codex-twitchcon-2026/commit/fc8b56b), [fair scoring](https://github.com/manazafzal/codex-twitchcon-2026/commit/ea40889), [completion evidence](https://github.com/manazafzal/codex-twitchcon-2026/commit/251fcba).

## M-easy — make a first visit understandable

We asked for a Windows double-click setup, a browser welcome screen, an offline demo, a Twitch connection path and a few obvious chat commands. We built the installer scripts, private first-run wizard, clearly labelled recorded fallback, countdown/headline/reveal presentation, default-hidden Nerd panel, simple participation commands, team emotes and bounded first-time welcomes.

We added offline/token-free demo tests, wizard/cookie/secrecy checks, role and participation tests, welcome-rate limits, visible-text checks and browser screenshots. We fixed retry feedback, an app-code field that needed to remain editable after failure, same-account streamer participation and recording controls that could not actually change a recording. We kept demo scores separate from live totals and stopped the previous engine owner before switching sources.

We saved [first-run screens](first-run.md), [full checks](easy-check-output.txt) and [focused checks](easy-targeted-check-output.txt). We did not claim that someone's mum had tested it, that a recording was live inference, or that the native Windows installer and actual Twitch flow had run on this Linux machine.

[Setup and offline start](https://github.com/manazafzal/codex-twitchcon-2026/commit/64de04a), [chat and welcomes](https://github.com/manazafzal/codex-twitchcon-2026/commit/2c672f7), [readable rounds](https://github.com/manazafzal/codex-twitchcon-2026/commit/b884aef), [screens](https://github.com/manazafzal/codex-twitchcon-2026/commit/f3d4fd7), [retry fixes](https://github.com/manazafzal/codex-twitchcon-2026/commit/ece1b45), [full validation](https://github.com/manazafzal/codex-twitchcon-2026/commit/c1fab4b).

## M-research — register predictions before collecting evidence

We asked for a judge-readable paper and executable ablations, including comparisons that might contradict our expectations. We committed only [the hypotheses](hypotheses.md) before running the new research command. We wrote the ablation runner, paired/concept-cluster statistics, validation-only classifier grids, CSV/JSON/Markdown tables, PNG/SVG figures, the paper renderer and the repository research skill. We put six plain-English lines before the abstract and made stale evidence or untraceable numerical prose fail checks.

We added synthetic algorithm tests, matching-seed byte comparisons, split-integrity checks, library-inference equivalence, artifact modification checks and failure-isolation tests. We fixed a zero-hit control being treated as unrun instead of inconclusive, definite failures being obscured by another inconclusive component, and one failed classifier cell discarding other completed cells. We separated unavailable alarm calibration from an otherwise valid label classifier. We explained that a classifier seeing the injection layer can remain accurate even if a later defence changes the answer.

We encountered another usage-limit pause. When we returned, the full check had completed: the [saved log](research-check-output.txt) records 205 passing tests and four deselected real-model tests. We checked that result rather than guessing or restarting the film job. The [research command output](research-run-output.txt) and [paper](paper.md) retain all empirical rows as unrun: no trained weights were available, so actual trained-model n is zero and confidence intervals are unavailable. Passing synthetic tests did not establish the research hypotheses.

[Hypotheses-only registration](https://github.com/manazafzal/codex-twitchcon-2026/commit/b1a090f), [runner and paper checks](https://github.com/manazafzal/codex-twitchcon-2026/commit/661f0ac), [decision/failure fixes](https://github.com/manazafzal/codex-twitchcon-2026/commit/fa5eab8), [paper and check evidence](https://github.com/manazafzal/codex-twitchcon-2026/commit/4e87797).

## M-concepts — test proposed topics before admitting them

We asked for `nous concept add`, the optional `!propose` command and three requested topic packs. We built seeded contrast generation, preserved pasted examples, duplicate rejection, word-count-matched neutral controls and reports containing source texts, raw means, seeds, model identity and hashes. We added the fixed admission checks, complete alarm/classifier refitting and private, atomic pack files. We record missing legacy contrast sources instead of pretending that their unit directions recover the original means.

We added a deterministic fake model: a coherent candidate passes, while random text fails held-out classification. We test each admission bar, failed refitting, cooldowns, repeated-proposal replies, queued publication, fresh masking, dynamic overlay labels and catalog-aware recording. We added an explicitly enabled real-model test, which requires local weights and otherwise skips. We kept the bonus command out of the play strip and extended vocabulary scanning to documentation and data assets.

We changed the build design from blocking a round boundary to a background task with serialized model access. Only the owner installs a complete result between rounds. We caught a command-routing regression while adding proposals, restored the existing round/mode/rank handlers and added a regression test. Browser testing also caught the fixture timeline overwriting an injected test scene; we paused that timeline before checking the new label. We recorded catalog changes so frame replay preserves names, and made engine replay explicitly refuse a changing basis instead of silently using the wrong library.

We shipped all requested pack entries with quality reports, but we rejected them because trained testing is unavailable here. Their measurements remain null with n=0; we did not weaken the bars or certify a test model's output as real quality. We document commands, thresholds, provenance and limits in the [topic-builder guide](topic-builder.md).

[Concept implementation](https://github.com/manazafzal/codex-twitchcon-2026/commit/dec3fb3).

## M-story — leave a checkable build record

We asked for this account to be plain, first-person and grounded in the repository. We rewrote it in milestone order, linked the code and saved evidence, retained the dead ends and usage-limit pauses, and added a short link below the README's unchanged quick start. We checked the narrative against git history, existing test files and saved logs instead of inventing missing historical results.

We keep the latest milestone's full check output with the final verification update. We continue to distinguish engineering tests from trained-model evidence, native Windows execution, live Twitch delivery, OBS composition and hardware-GPU performance. None of those absent checks becomes a success just because the Python suite is green.
