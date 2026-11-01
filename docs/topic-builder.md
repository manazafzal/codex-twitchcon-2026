# Adding topics to NOUS

The optional `!propose comet` command thanks a viewer and queues a private test. It stays out of the How to play strip. Chat accepts ASCII letters only, from three to twenty characters, and uses the repository vocabulary policy. Each viewer waits five minutes between proposals; the whole channel waits fifteen seconds. The queue holds at most eight waiting ideas, suppresses duplicates, and admits at most five topics per live session.

A local operator can run:

```sh
nous concept add comet
nous concept add comet --from-model 24
nous concept add comet --examples examples.json
```

The first two commands are equivalent. Examples can be a JSON/YAML list of strings or a UTF-8 file with one sentence per line. Their text and whitespace are preserved; repeated examples cannot be split into an independent training/held-out check. CLI names may also contain spaces or hyphens; chat names are deliberately narrower. Existing names and aliases are rejected instead of hiding an existing team behind a new one.

The prepared local model and base library must exist already. No model download occurs. `--model-path`, `--library` and `--output` select local paths; defaults follow NOUS's local data directory. A rejected or unavailable build saves `quality.json` beside its pack directory and never replaces the active library. A successful CLI build saves the expanded library atomically; restart an already running game to load a library changed by a separate CLI process. Chat proposals update their running session between rounds.

## What is tested

The generator reads `data/builder_prompts.yaml`, with a packaged copy for installed use outside the checkout. It uses a fixed seed, drops duplicate generated sentences and stops rather than inventing missing examples. Each generated topic sentence has a neutral control with the same word count, using a prefix of model output without repeated filler. These controls are saved for audit; the actual direction subtracts other concept means, not the matched neutral controls. Pasted examples are not rewritten or expanded by the model.

The report retains texts, seeds, model identity, template/text hashes, raw means and the train/held-out split. New base-library builds now retain their contrast origins. When an older library lacks them, the builder regenerates source sets and records that fact; it never substitutes unit directions for the missing raw means.

All four admission rules are fixed:

- Fit on half the candidate texts and classify the other half among every existing concept plus the candidate: top-1 at least 0.8.
- Maximum cosine with existing injection/readout directions: at most 0.6.
- At alpha 0.45 on six matched everyday prompts, keyword or independently calibrated embedding hit must improve over alpha zero by at least 0.10.
- The fixed lexical/repetition task-retention proxy must be at least 0.6 on the injected answers.

Every check states its actual n and whether it ran. Early failures leave later checks explicitly unrun. These small admission samples are not a population-level effectiveness claim. Passing the four checks is still insufficient if fresh alarm calibration or the expanded v4 classifier fit fails. The builder recalibrates the whole catalog, rejects overlapping classifier partitions, recomputes PCA coordinates and hashes the expanded library before publication.

Live builds use a background task and serialized access to shared model weights. Only the engine owner installs a completed result, between rounds. A secret round must finish before publication. The recorded `round` event's `catalog` phase carries the new public catalog without adding a new event kind; snapshots and the word masker refresh together. Frame replay retains new names and colours. Engine replay explicitly refuses recordings that change library bases and directs the user to `--frames`.

## Packs and honest limits

`data/packs/` contains cosmos, kitchen and mythic, each with eight requested entries and individual quality reports. This environment has no trained weights or prepared base library. All shipped entries are therefore **rejected because testing is unavailable**, with n=0 and null measurements, rather than falsely certified or reported as measured failures. No pack entry is live by default.

To test the packs on a prepared machine:

```sh
python -m tools.build_packs --library /local/concepts.npz --model-path /local/qwen --output data/packs
```

Each pack starts from the same base and includes only its previously accepted entries when testing the next candidate. Individual accepted entries include an expanded `library.npz`; rejected entries retain reasons without an installable library.

Development checks:

```sh
pytest -q tests/test_concept_builder.py tests/test_telepathy_leak.py tests/test_vocabulary.py
NOUS_REAL=1 NOUS_LIBRARY=/local/concepts.npz NOUS_MODEL_PATH=/local/qwen pytest -q -m realmodel tests/test_concept_builder.py
make check
```

The deterministic fake model demonstrates a passing candidate and a random-text rejection. It is test evidence, never trained-model quality evidence. Real-model tests require explicit local artifacts and otherwise skip. After changing the vocabulary rule, run `python -m tools.build_name_policy` and keep the policy/test in sync.
