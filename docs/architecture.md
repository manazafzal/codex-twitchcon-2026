# Engine ownership and offline evidence

One `Session.events()` task owns the engine. Chat, local controls and mode requests enqueue frozen typed commands (`Push`, `SetMode`, `Control`, `Guess`, `Rank`). The owner drains them at safe boundaries; model execution remains on one worker. A second consumer is rejected. Public mixer properties and `hold()` replace external access to implementation state. Producer failures log a generic diagnostic, emit the existing `connection` event with error status, and restart with bounded backoff. The overlay restores connection state from snapshots.

## Local model and library

The trained backend accepts the supported Qwen2.5 identifiers or a locally provisioned path. Transformers loads local files only. Hook outputs use zero-based layers: injection 16, defender 17, readout 20, additional probe 22. Prefill and subsequent positions receive the same injection policy; absolute position zero is excluded from modification and text statistics. Zero injection bypasses arithmetic, preserving logits exactly. TinyBackend keeps a shorter equivalent architecture for CI.

The others library uses the unit difference between each concept mean and the mean of the other concept means. Injection strength is alpha times the configured median norm times the saturating dose curve. The CLI defaults to the supplied norm reference, which is explicitly recorded as configured rather than newly measured. War shares remain capped; evaluation uses a forced target and a beta ceiling of one. Legacy neutral libraries remain loadable for compatibility, without representing current real-model acceptance.

Library files cover every numeric array, configuration and provenance field with a content hash, including optional calibration, independent alarm thresholds and fitted readout arrays. Loading verifies derived arrays as well. Atomic replacement prevents partial writes. PCA uses unit readout directions, deterministic signs and normalized axes. Alias/stem matching is case-insensitive and bounded by words.

## Readout and alarm are separate

The 12-token readout window ranks all concepts. Calibrated cosine z remains the signal field and alarm input. A fitted shrinkage LDA uses concatenated answer means at layers 16, 20 and 22 for labels, answer colours and reveal. Its validation split selects shrinkage; its test split is never used for fitting. Families, seeds and normalized generated-text hashes must be disjoint across partitions. Stored classifier and data provenance allow independent reruns.

The clamp uses neutral 97th-percentile projection thresholds on all directions. Detection instead uses fresh 99.5th-percentile projection thresholds or calibrated z at least four, requiring eight consecutive tokens attributed to one concept. Task-named concepts are exempt. Private detector statistics can be evaluated in either immune setting; public tamper reports require immune on. The old three-token monitor remains only for legacy compatibility tests, not runtime decisions.

## Public secrecy and recording

The server always creates a strict presentation projector from the complete concept catalog. Each hidden round uses a fresh cryptographic permutation to opaque identifiers and an unrelated layout. Token signal map keys, pushes, shares, guesses, tamper reports and user-controlled names are projected. Text is buffered to word boundaries with a lookbehind so multi-token words and multiword aliases are masked before publication. Reveal publishes the alias map and true coordinates.

Snapshots use the same projection and clear previous answer/history metadata when entering a hidden round. Leaderboards expose only viewer ids, names and points while hidden; faction boards wait until reveal. Fixed schema keys are retained, so secrecy assertions inspect semantic values and semantic map keys rather than treating a schema word as leaked content. Complete blind-round tests independently inspect recorded socket frames, API snapshots and boards.

Raw recording rows for a hidden round stay in memory until reveal. Cancelled or incomplete hidden rounds are discarded. Completed revealed rounds retain the private plan required for engine replay. These local recordings may contain chat and should be shared deliberately. Development fixtures are served only when explicitly enabled.

## Points and persistence

A round distributes a bounded push budget using measured answer concept hits, faction dose share and each viewer's accepted dose share. Push and guess cooldowns, per-round attempt limits and an individual point cap prevent repetition from outranking a first correct guess. Guess awards decrease with correct-guess order. A successful moderator immune catch requires attribution to the actual target. Stream and all-time viewer/faction totals are written with a temporary file, fsync and atomic replacement. A killed writer leaves the prior valid file. MVP cards and reveal boards use the existing round event schema. Rank replies and MVP announcements use the existing rate-limited chat sender.

## Evaluation evidence

`thoughtquake eval` runs the real backend and Generator with matched prompts/seeds, independent embedding thresholds and saturated forced-target input. It records vector/library/git hashes, hardware, trial text hashes, raw trial measurements and throughput. Every metric includes its valid sample count, concept cluster count, a seeded concept-cluster bootstrap interval, and an additional Wilson interval where appropriate. JSON metric order matches the generated Markdown columns.

The held-out comparison evaluates old and v4 labels on the same unseen-template examples. Evaluation rejects fitting-family/seed reuse and overlap with stored text hashes. Missing v4 arrays produce unavailable results. Task retention is a lexical-anchor/repetition proxy, not a human judgement of relevance; embedding hit is a thresholded local-model text projection, not an independent semantic judge. These definitions limit comparison with externally supplied benchmark figures.

This checkout contains no trained weights, fitted v4 artifact or supplied training corpus. The implementation can be verified with deterministic mock, synthetic vectors and random-init TinyBackend. Those runs are labelled TINY MODEL / CI and do not establish trained-model accuracy, relevance, false-alarm rates or speed. Real acceptance tests require local artifacts and explicit opt-in. The research report is deferred to P_POLISH_v3c.
