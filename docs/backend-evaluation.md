# Backend evaluation evidence

## Streamer-reported real-model checks

The supplied [real-model results note](REAL_MODEL_RESULTS.md) and committed [fitted library](../library/nous-fitted.npz) supplement the historical CI run below. The reporter measured top-1 94.2% (91.7–96.4% interval across concepts) and top-3 96.1% (94.2–98.1%) on 360 held-out answers across 30 concepts, versus 47.5% and 66.7% before fitting. Calibrated checks reported 192/192 idle abstentions and 320/320 pushed labels. Earlier-library immune checks reported 0/20 clean false alarms and 20/20 pushed answers caught; they were not rerun with the final library. These are supplied Linux CPU results, not an independent rerun here. The note records revisions, the library SHA-256, sample sizes and limits. The 24 pack concepts remain experimental; the full registered ablations remain unrun.

## Historical mock-only evaluation

**TINY MODEL / CI — source: mock.** These are plumbing measurements from scripted text and fixture vectors, not trained-model evidence. The final command ran against the committed code linked below. This historical mock run had no trained v4 classifier, so its v4 metrics remain unavailable; it does not describe the now-bundled real-model artifact.

`nous eval --mock --output results/backend-ci --alphas .3 .45 --seeds 1 --prompts 6 --concepts 30 --held-out 3 --seed 0`

The table reports measured means and concept-cluster bootstrap 95% intervals. Each row uses the same prompts and seeds. Counts are valid answers and concept clusters, not independent-token sample sizes. Full metric counts, token denominators, Wilson summaries, hardware and trial records are in the [JSON](../results/backend-ci/eval.json); the [complete generated table](../results/backend-ci/eval.md) preserves JSON metric order.

| alpha | immune | n | clusters | keyword hit | stem hit | old readout top-1 | private any-alarm |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.3 | False | 180 | 30 | 0.1000 (0.0000–0.2000) | 0.1333 (0.0333–0.2667) | 1.0000 (1.0000–1.0000) | 1.0000 (1.0000–1.0000) |
| 0.45 | False | 180 | 30 | 0.1000 (0.0000–0.2000) | 0.1333 (0.0333–0.2667) | 1.0000 (1.0000–1.0000) | 1.0000 (1.0000–1.0000) |
| 0.45 | True | 180 | 30 | 0.0333 (0.0000–0.1000) | 0.0667 (0.0000–0.1667) | 1.0000 (1.0000–1.0000) | 0.8000 (0.6333–0.9333) |
| 0.0 | False | 180 | 30 | 0.0333 (0.0000–0.1000) | 0.0667 (0.0000–0.1667) | 0.0333 (0.0000–0.1000) | 0.0000 (0.0000–0.0000) |
| 0.0 | True | 180 | 30 | 0.0333 (0.0000–0.1000) | 0.0667 (0.0000–0.1667) | 0.0333 (0.0000–0.1000) | 0.0000 (0.0000–0.0000) |

The neutral mock script includes a concept alias. Its nonzero control keyword rate is preserved rather than altered to meet a real-model criterion. Private detector results in immune-off rows do not indicate public Tamper events; generation tests verify those events are absent. Finite-sample fixture label results do not establish universal accuracy. The task-retention column in the full report is only a lexical/repetition proxy.

At this earlier milestone, a real `nous eval` attempt stopped because the then-default local library was absent. That specific library blocker is now resolved by the bundled artifact; local model weights are still needed. The explicitly enabled real-model suite skipped for missing local artifacts. No automatic download, model substitution, trained classifier fit or supplied benchmark reproduction occurred. See [blocker output](backend-real-check-output.txt). The full matched alpha-zero, hit, false-alarm and readout acceptance grid remains unrun here; do not substitute the supplied spot checks for it.

**Code revision:** [cdd4a58](https://github.com/manazafzal/codex-twitchcon-2026/commit/cdd4a58a2eafa195fd810fd0c4e3e29cf7828076). The supplied layer/norm references are configuration, not newly measured statistics. This milestone follows the prompt where it supersedes the older SPEC hook layers, active-only readout and alarm rule. Research packaging is deferred.
