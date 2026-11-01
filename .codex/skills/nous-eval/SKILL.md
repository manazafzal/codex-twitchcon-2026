---
name: nous-eval
description: Run and audit offline NOUS evaluations without mixing development output with trained-model evidence.
---

# NOUS evaluation

Read AGENTS.md and SPEC.md plus the current milestone prompt. Keep the vocabulary test green; do not add prohibited terms or stems to strings, documentation, or fixtures.

1. Inspect local artifacts before running. Use a hash-verified others library and locally provisioned Qwen2.5 weights. Do not download at runtime, silently fall back to a test backend, or copy benchmark figures from a prompt. Record a missing-artifact run as blocked.
2. Run `make check`; this includes scoped mypy, M4 coverage, secrecy, scoring and deterministic film tests. Browser checks require local Chrome and loopback access, never external pages. For a fast edit cycle use `pytest -q --ignore=tests/test_overlay_visual.py` before the complete check.
3. Build with `nous build-library --model-path PATH`, calibrate fresh alarm data with `nous calibrate-alarm --library PATH --seed 1`, and fit using `nous fit-readout --library PATH`. The saved training NPZ may be reused via `--data`; verify its basis hash and disjoint family/seed/text splits. Test data never selects shrinkage. Keep private corpora out of git.
4. Run `nous eval --library PATH --output results --alphas .3 .45 --seeds 1 --prompts 6 --concepts 30 --held-out 3 --seed 0`. The matched controls, independent embedding threshold, progress, provenance and held-out comparison are automatic. Review JSON before publishing its generated Markdown table.
5. Use `nous eval --mock --output work/eval-ci` for development only. Its source and quality label must remain explicit. An absent v4 classifier produces unavailable fields, not a substitute v4 result. The real acceptance suite requires `NOUS_REAL=1 NOUS_LIBRARY=PATH pytest -q -m realmodel` and local weights.
6. Report measured values with valid n, concept cluster count, and cluster-bootstrap 95% intervals. Wilson intervals are additional summaries. Compare alpha and immune rows with identical prompts/seeds, and old/v4 predictions on the same held-out texts. The task metric is a lexical/repetition proxy; it does not establish human relevance. Do not describe finite-sample accuracy as certainty.
7. Audit no public Tamper events with immune off, all-concept readout, position-zero exclusion, task exemptions, and full-round blind secrecy. Public projection must sanitize snapshots and semantic map keys as well as live token values. Private rows cannot reach disk before reveal.
8. Commit code, tests and auditable tables using `M-backend: ...`; link the code revision and evidence in docs/BUILT_WITH_CODEX.md. Keep supplied reference figures separate from measured output. Research packaging belongs to the next milestone.


For NOUS completion work, also run the scoring/director regressions in `tests/test_round_points.py`. Verify that an answer's frozen selection cannot pay a later push, a rejected guess cannot win, the two Attack panels pay once, and a prior round's moderator does not keep collecting catch awards. Reopen both stream/all-time boards, select a new stream id, and kill a writer before replacement. Check MVP restoration through a snapshot and removal during blind mode. Do not replace the independent cosine alarm with fitted label confidence.
