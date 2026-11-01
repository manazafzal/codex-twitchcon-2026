# Built with Codex

## M-visual — P_POLISH_v3b: Mind Atlas / Living Night

**Prompt.** Build a smooth, signal-driven night sky around the Subject: PCA concept positions, calibrated token glow, dose pressure, moving currents, residual trails and immune rings. Keep the event stream and source labels, bundle fonts, support transparent OBS capture and deterministic film, measure the result in offline headless Chrome, and publish milestone commits.

**Built.** Plain HTML/CSS/JS with a WebGL2 field and Canvas2D effects, plus a Canvas-only fallback. The shared 1920×1080 page includes the serif answer, three-answer history, proportional Mind Share, SD ridgelines with full names, source badge, push ticker and mode signatures. The virtual clock controls words, captions, reconnect delays and effects. The scale governor reduces field resolution when 60-frame mean time exceeds 22 ms. Neutral calibration is saved and hashed with the library; old files remain readable without fabricating SD values. Telepathy publishes opaque coordinates and measurement keys, then an alias map at reveal. Fixture files are opt-in, not production assets.

**Provenance.** `trace_data.js` contains recorded deterministic mock calls and recorded random-init TinyBackend calls. The default mock scene supplies readable demonstration text; `backend=tiny` uses the actual tiny-model text and states. Every development scene carries `SIMULATED ×40` and `TINY MODEL / CI`. Neither is trained-model evidence. The recorded state values are real backend outputs; the development timeline uses a fixed presentation cadence, not a model-speed benchmark. The renderer does not manufacture readout values or fetch assets. The local fonts include their OFL notices.

**Tests and fixes.** Added PCA and signal arithmetic, calibration roundtrip/hash, schema validation, blind-key safety, fixture gating, allowlisted fonts, five-scene Chrome checks, Canvas fallback, transparency, quarter-size contrast, minimum text size and full-label overflow assertions. A full 20-second, 30-fps recording is compared byte-for-byte by PNG hash on two fresh browser runs. Browser inspection caught and fixed a loopback resolver restriction, font readiness, fixture clock dispatch, answer-mask remnants, missing history/push restoration, live connection-chip restoration, virtual share transitions, and a title/history overlap. See [performance measurements](perf.md) and [raw measurements](overlay-measurements.json).

**Signal definitions.** The SD field standardizes the existing windowed cosine scores with saved neutral-position mean and standard deviation. Residual is the norm of the change between consecutive readout states; drive is that change divided by the current state norm, capped at one. Clamp strength is the relative change in the recorded defender projections. Missing calibration produces no SD claim. Original cosine scores remain in the existing event fields.

**Scope and limits.** This prompt replaces SPEC §15's earlier geometry, palette and type minimum. Visual evidence here uses CPU SwiftShader and development backends. A real model, hardware-GPU 60 fps, OBS composition and live Twitch viewing still require streamer-machine checks. No accuracy or model-quality result is inferred from visual motion.

**Milestone commits.**

- [c61831f — Mind Atlas and browser tooling](https://github.com/manazafzal/codex-twitchcon-2026/commit/c61831f)
- [9c09b3e — final fixes, five scenes, timing and film evidence](https://github.com/manazafzal/codex-twitchcon-2026/commit/9c09b3e)

**Validation.** `make check`: ruff passed; 114 tests passed in 1231.56 s, including two complete 600-frame films. The final fixture/contract pass also passed 113 non-film tests; the War film input records were checked unchanged when the comparison captures were corrected. Five final scenes report zero console errors; see the measured limits in `perf.md`. The CLI smoke served the overlay with 30 PCA points and 30 token scores while keeping development traces at 404. An MP4 encoder smoke produced three frames at 480×270 and 30 fps. [Full check output](check-output.txt).


## M-backend — P_POLISH_v3a: backend and evaluation

**Prompt.** Use latest main; preserve the event schema, M4 behavior, source badges and vocabulary constraints. Implement an offline others library with position-zero exclusion and checked provenance; fixed real-model hooks and dose limits; all-concept calibrated readout plus a fitted multi-layer v4 classifier; independent eight-token alarms; complete blind-round secrecy; a queue-owned supervised engine; bounded viewer points and atomic leaderboards. Write the evaluation CLI, tests, generated tables, repository workflow skill and process notes. Finish with checks, an actual eval attempt and milestone commits. Research packaging remains P_POLISH_v3c.

**Built.** Library schema covers every array, optional LDA parameters, per-concept hashes, calibration/alarm provenance, deterministic unit-direction PCA and alias/stem recognition. The trained loader is local-only. Hooks exclude the absolute sink position from injection, clamp and statistics, preserve KV caching and bypass zero-vector arithmetic. Runtime readout ranks the full catalog; LDA labels do not replace the cosine alarm signal. Alarm attribution uses stricter independent thresholds, task exemptions and a same-concept run. Modern fixed comparison/secret rounds inherit the configured alpha and norm; legacy fixtures retain their original strength.

Strict presentation uses a new cryptographic opaque permutation per hidden round, independent coordinates, word-boundary buffering and multiword masking. Snapshots remove earlier answers and faction metadata. Hidden raw recording rows wait in memory until reveal and are dropped on cancellation. Existing event kinds carry MVP cards, connection failures and reveal boards. A single queue owner processes typed commands; producer failures restart with bounded backoff and generic logs. Points have input cooldowns, attempt limits, a round cap and atomic persistence; the leaderboard API omits faction data while hidden.

The offline CLI runs matched alpha/immune controls, independently calibrates embedding thresholds, compares old/v4 readouts on held-out templates, records local hardware/provenance and emits ordered JSON/Markdown tables. It uses concept-cluster bootstrap intervals and additional Wilson summaries. Fitting selects shrinkage on validation only and rejects family/seed/text overlap. Saved local corpora can be reused without loading a model; the corpus hash and vector basis are recorded. Task retention is explicitly a lexical/repetition proxy and requires separate human assessment before relevance claims.

**Tests and fixes.** Added library-array corruption, exact dose math, full-catalog z scores, synthetic LDA partition/roundtrip, cluster resampling, CLI fitting with local data, matched evaluation schema, off-state tamper silence, same-concept alarm/exemption, a six-token neutral regression, queue ownership/restart, whole blind-round socket/API recording, split-word and multiword masking, point math/spam resistance and crash-before-replace persistence tests. TinyBackend checks zero-vector equality, prefill/cached-state changes, sink exclusion and defender projection reduction. The existing M4 suites remain intact. Real-model acceptance is opt-in and needs locally trained artifacts.

Review caught and fixed double-standardizing SD scores, active-only ranking, a canonical-order identity leak, early multiword publication, snapshot history leakage, raw plan writes before reveal, reuse of fitting seeds in evaluation, stale fixed-round strength and mismatch between generated evidence and the existing answer-colour gate. An ID-order test initially inspected insertion order instead of concept order; the assertion now independently checks the canonical catalog. Browser preflight and the full film test retain the prior visual contract.

**Evidence and limits.** The supplied benchmark bands were not copied into result files. No trained weights, saved fitted classifier, training corpus or referenced readout study exists in this checkout. The real eval command stops at the missing local library rather than downloading or silently substituting a mock. CI measurements are explicitly labelled `source: mock`, `TINY MODEL / CI`; their scripted text and sparse fixture vectors cannot establish trained-model quality. In particular, the fixture's neutral text itself contains concept vocabulary, so its control keyword rate is measured honestly rather than forced to zero. The v4 columns stay unavailable without a fit. The default fixture traces are historical development captures, not newly calibrated trained-model data.

**Validation.** `make check`: ruff passed; scoped mypy passed; 139 tests passed in 1238.09 s, including both complete films. The explicitly enabled real-model suite skipped four tests because local artifacts are absent. [Complete check output](backend-check-output.txt), [real-run blocker and skips](backend-real-check-output.txt), and [architecture and evidence limits](architecture.md). Final measured CI tables and milestone commit links follow below.


**Measured CI evidence.** [Evaluation notes and cluster intervals](backend-evaluation.md), [generated complete table](../results/backend-ci/eval.md), [raw trials and provenance](../results/backend-ci/eval.json), and [film hash verification](backend-film-check.json). All evaluation numbers in these artifacts are measured mock output, with n and concept-cluster intervals. No real-model result is claimed.

**Milestone commits.**

- [cdd4a58 — offline evaluation, strict secrecy, viewer points and tests](https://github.com/manazafzal/codex-twitchcon-2026/commit/cdd4a58)
- [4f47c83 — measured CI report, raw trials and uncertainty tables](https://github.com/manazafzal/codex-twitchcon-2026/commit/4f47c83)

The post-report vocabulary and evaluation suite passed with 17 tests; ruff and whitespace checks passed. No runtime code changed after the complete check.


## NOUS rename

The product, package, CLI, environment prefix, browser titles/globals, tests, documentation, Makefile and repository evaluation skill now use NOUS. Nous is Greek for mind: chat reaches into a mind, and the mind defends itself. This is a standalone rename commit before further backend fixes. Source badges and event fields are unchanged. Local config now uses the NOUS directory; existing credentials outside this checkout were not moved.

Rename validation: ruff and scoped mypy passed; 131 non-browser tests passed. Screenshots were refreshed with the NOUS wordmark; browser preflight checks all five scenes, fallback, full labels and transparency. The final milestone check also runs the full deterministic film comparison. A case-insensitive repository search found no earlier product name in tracked text or paths. No trained-model measurement was inferred from the rename.


## NOUS backend completion

**Prompt.** Inspect the working tree first, preserve the existing backend work, rename the project in a standalone commit, finish v4 readout separation and fair viewer points, persist stream/all-time leaderboards atomically, retain blind secrecy, and finish with a green complete check and a push to main.

**Starting state.** Both initial status commands were clean. The previous backend job had already been committed, including fitting, scoring, persistence, MVP/rank wiring and 139 passing tests. The local `work/readout_v4.md` and trained artifacts remain unavailable; the user's measurements are not presented as a new reproduction.

**Fixes.** Completed v4 answer/window labels alongside colours while preserving original cosine/z alarm inputs. Fixed Attack scoring that closed after OFF, guess finalization that prevented later queued awards, and round-winning guesses bypassing point eligibility. Late answer pushes receive next-round credit using their arrival timestamps; incidental Neutral words earn no injection contribution points. Moderator catch attribution is limited to the current round and live controls. Stream totals now persist alongside all-time totals, with explicit stream ids and version-one migration. MVP/reveal boards restore from snapshots, hide while blind, and use independent virtual expiry versions.

**Tests.** Added end-to-end v4-versus-alarm disagreement, queued guess prizes, cooldown/attempt-limited wins, exact point-cap and timestamp checks, single Attack payout/catch, delayed push credit, Neutral no-credit, rank and MVP chat limiting, stream resume/reset/migration, and a browser MVP/reconnect/blind check. The killed-writer and complete recording-client Telepathy leak tests remain intact. Fast preflight passed 143 tests; the targeted browser check passed. Final complete validation is recorded after the full run.

**Commits.**

- [226f7d2 — standalone NOUS rename](https://github.com/manazafzal/codex-twitchcon-2026/commit/226f7d2)
- [fc8b56b — answer-level v4 labels, colours and independent alarm test](https://github.com/manazafzal/codex-twitchcon-2026/commit/fc8b56b)
- [ea40889 — fair round scoring, persistent stream boards and regressions](https://github.com/manazafzal/codex-twitchcon-2026/commit/ea40889)

**Final validation.** `make check` passed: ruff; mypy on 19 source files; **152 passed, 4 deselected in 1243.96 s**. This includes two complete 600-frame films with identical frame hashes and the MVP snapshot/blind test. The real-model opt-in suite reported four skips and 152 deselections because local artifacts are absent. CLI smoke served NOUS overlay/control/WebSocket/leaderboard and confirmed fixture gating. Case-insensitive tracked-text and path searches found no previous product name. The scoring rules in this prompt supersede SPEC's older public one-point scheme; existing internal M4 game-state tests remain intact.

[Full check output](nous-check-output.txt), [opt-in model skips](nous-real-check-output.txt), [CLI smoke](nous-cli-smoke.txt), [film summary](nous-film-check.json), and [all frame hashes](film-hashes.json). Refreshed NOUS screenshots remain in [screenshots/](screenshots/). No trained-model benchmark was reproduced; neither the local study file nor the required trained artifacts is available. No live Twitch or OBS check was performed in this milestone.
