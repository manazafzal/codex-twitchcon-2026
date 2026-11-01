---
name: nous-research
description: Regenerate and audit preregistered local NOUS ablations and the paper without inventing missing evidence.
---

# NOUS research

Read AGENTS.md, SPEC.md, docs/hypotheses.md and the current request. Keep vocabulary rules intact in all strings and documentation. Work from the repository root with complete git history; the registration commit must be available. Do not rewrite or amend the registered file. A changed sampling design requires a separate registration before measurement.

## Exact commands

```bash
python -m pip install -e '.[dev,model,research]'
export NOUS_MODEL_PATH=/absolute/path/to/local/Qwen2.5-0.5B-Instruct
nous research run --config configs/ablations.yaml --seed 0 --output research/
make paper
make check
```

Weights must already exist locally. The research command never downloads weights and never substitutes a mock model. When no local model path is available, unset NOUS_MODEL_PATH and run the same command: it writes the complete grid as unrun, with actual n=0 and no estimates. Install plotting dependencies explicitly, outside tests. CPU runs can be lengthy; progress logs identify calibration, generation and classifier cells. Wider research doses do not relax the live game's limits.

Run fast checks during edits:

```bash
ruff check .
mypy src/nous/engine src/nous/model src/nous/concepts src/nous/evaluation.py src/nous/research
pytest -q tests/test_research.py tests/test_backend_eval.py tests/test_telepathy_leak.py
python -m nous.research.paper --check
```

The full check includes local Chrome and deterministic film tests when Chrome exists. Browser checks need loopback, never an external page or browser download. Without the optional research extra, plotting tests skip; rendering/checking the already committed paper does not import matplotlib.

## Evidence audit

The manifest contains the registration hash, unchanged hypothesis-file digest, configuration digest, source commit, seed, numeric environment and output-file hashes. Each table row says run or unrun and states actual n, clusters and planned n. Do not interpret unrun rows as zero effects. A classifier fit rejects overlapping template families, seeds or normalized text hashes across partitions. Selection uses validation only; the primary full classifier is predefined separately.

Review paired comparisons and concept-cluster intervals, not only means. Bootstrap samples resample concepts, retaining matched answers. Relative reduction is undefined for a zero-hit control. The classifier-confidence detector is an ablation only: the operational alarm remains projection/z-cosine. Do not transfer prompt hints or earlier exploratory measurements into these artifacts. Synthetic algorithm tests are never trained-model evidence.

Tables are deterministic for matching inputs and seed; timings and timestamps are excluded. Compare CSV, JSON and Markdown bytes on repeat runs. Figures use a fixed SVG hash salt and omit variable dates. The paper source permits numeric results only through explicit table/figure placeholders; symbolic mathematics is separately allowed. Run make paper after evidence/source changes. make check verifies evidence hashes and fails on a stale rendered paper rather than silently accepting it. Keep raw private corpora outside tracked files.
