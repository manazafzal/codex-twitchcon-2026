# NOUS — SPEC (build-ready)

Status: written Sun 1 Nov 2026 (AEDT). Target: submitted Mon 2 Nov 2026 22:00 AEDT.
Repo: `manazafzal/codex-twitchcon-2026` (build in ONE Codex cloud thread).

## 1. One-line pitch
**Chat factions fight over the thoughts of a live AI — while a real-time Mind-Reader and a Neural Immune System watch every move.**

Devpost title: **NOUS** · tagline: **"Chat fights over an AI's mind. Live, local, $0."** (≤ 60 chars)

## 2. Anti-"Golden Gate Claude" rules (product-level; enforced by tests)
A judge must never think "this is Golden Gate Claude". Every one of these is designed out:

| Way a judge could think it | What we do instead |
|---|---|
| Single-concept obsession ("it can't stop talking about X") | Always ≥ 2 factions fighting; a faction may hold at most 75 % of applied injections (dominance cap); the video never opens, nor spends > 5 s, on one concept. |
| "Model forced to mention a landmark/bridge" | Library has no landmarks or place names. Prompts are everyday tasks; the Subject is never asked "who are you". |
| Identity confusion shots ("I am the …") | No self-referential prompts. Subject is called "the Subject". |
| The word "steering" / "feature" / "dial" as headline | Own vocabulary: thought injection, mind territory, Mind Share, Mind-Reader, Neural Immune System, Telepathy. The technique name appears only in `docs/related-work.md` (cites ActAdd, CAA, Golden Gate Claude, brainscope, Neuronpedia, Lindsey 2025 as ancestors and states what is new). |
| Slider UI (brainscope / Neuronpedia-style) | No sliders for viewers. Doses come only from chat. |
| SAE-feature framing | We state exactly: difference-of-means vectors from self-generated contrast sets (ActAdd/CAA lineage), not SAE features. |
| Repeated-word wall-of-text screenshot | Words coloured by faction; mixed content in one sentence; no screenshot of a single-concept loop. |
| Old name MINDWARP | Use NOUS only. |

**What GGC never showed (our hero):** several factions' concepts competing inside ONE answer, each word coloured by the faction the Mind-Reader says is driving it; a live readout of the AI's state while chat fights; a defender that detects and neutralises an injection; a chat guessing game against the Mind-Reader.

## 3. What is new (honest claim)
Ancestors: ActAdd (Turner et al. 2023), CAA, RepE, Golden Gate Claude (Anthropic, 2024), brainscope, Neuronpedia. **New here (as far as I could find; searches were quick, not exhaustive):** the multiplayer game format — live chat as the only control, faction contest with Mind Share, per-token readout colouring, an automatic defender, and a Telepathy guessing round — as a free, local, drop-in streamer toolkit with a reproducible eval. We do not claim a new steering technique.

## 4. Architecture

```
Twitch chat ──EventSub WS──▶ twitch/eventsub.py ─┐
sim crowd (labelled) ───────▶ sim/crowd.py ──────┤
replay JSONL ───────────────▶ replay/player.py ──┴▶ engine/mixer.py ─▶ engine/generate.py ─▶ events
                                                                    │ model backend (HF / Tiny / Mock)
                                                                    ├ concept library (cached vectors)
                                                                    ├ readout (probe per token)
                                                                    └ immune (defender hook)
events ──▶ server/app.py (aiohttp) ──WS /ws──▶ overlay/ (browser source)
        └▶ replay/recorder.py (JSONL)        └▶ twitch/chat_send.py (Helix Send Chat Message)
```

Directories:
```
src/nous/{config.py,cli.py}
src/nous/model/{backend.py,hf_backend.py,tiny_backend.py,mock_backend.py}
src/nous/concepts/{library.py,builder.py,concepts.yaml}
src/nous/engine/{mixer.py,generate.py,readout.py,immune.py,rounds.py,events.py}
src/nous/game/telepathy.py
src/nous/twitch/{auth.py,eventsub.py,chat_send.py,parse.py}
src/nous/sim/crowd.py
src/nous/replay/{recorder.py,player.py}
src/nous/server/app.py
src/nous/overlay/{index.html,style.css,app.js}
src/nous/eval/{run_eval.py,metrics.py,report.py}
tests/  golden/  library/  results/  docs/{related-work.md,streamer-guide.md}
```

## 5. Model and backends

`ModelBackend` protocol (all engine code depends only on this):
- `num_layers`, `hidden_size`
- `prefill(prompt) -> state`
- `step(state, token, inject: Vector|None, defend: DefendSpec|None) -> (logits, readout_hidden, state)` — runs one token with an optional additive vector at layer L, an optional defender, and returns the hidden state at layer R for the new position.
- `sample(logits, temperature, top_p, rng) -> token`, `decode(tokens)`.
- `embed_texts(texts, layer) -> mean hidden states` (used by the library builder).

Backends:
1. `HFBackend` — `transformers` + `torch`. Default `Qwen/Qwen2.5-0.5B-Instruct` (Apache-2.0); optional `Qwen/Qwen2.5-1.5B-Instruct` on GPU or fast CPU. Config `NOUS_MODEL`, `NOUS_DEVICE=auto|cpu|cuda`. Layer L = round(0.55 × num_layers) (injection after `layers[L]`), readout layer R = L + 4. The hook adds the vector at the newest position only (prompt is prefilled uninjected; KV cache kept). Speed measured on an 8-core CPU box: about 34 tok/s unhooked, 16–26 tok/s hooked, 0.5B bf16.
2. `TinyBackend` — random-init model built in-process from a tiny `Qwen2Config` (e.g. 2 layers×32 hidden, vocab 256, byte-level tokenizer stub). Used in tests to exercise the real hook code paths (shapes, indices, KV cache, defender math) with no download. Requires torch; tests skip cleanly if torch is missing.
3. `MockBackend` — pure numpy, deterministic: hidden state = sum of injected concept directions + noise; text = scripted words per dominant concept. Used for engine/server/Twitch/overlay tests and `nous demo --mock`.

Important: tests with Tiny/Mock prove plumbing, not quality. Quality is only claimed from `make eval` on the real model.

## 6. Concept library (~30 cached vectors)
- `concepts.yaml`: 30 entries `{id, label, color_index, aliases[]}`. Everyday, abstract, diverse; **no landmarks, no place names, no people, no brands**. Seed list: ocean, space, jazz, horror, gardening, war, pirates, dinosaurs, chemistry, football, robots, wizards, detective, cats, dragons, medieval, romance, ninjas, volcano, desert, winter, circus, farm, disco, weather, library, school, pizza, time-travel, cooking. (Codex may swap ≤ 5 for better separation after eval.)
- Aliases are ~8 words each (e.g. ocean: sea, wave, tide, whale…) used to match chat messages to factions: a message counts for faction F if it contains an alias or the id as a whole word (case-insensitive). A message matching ≥ 2 factions counts for the first match only. `!push <word>` is optional sugar; plain words work.
- Builder (`nous build-library`): for each concept, generate N=8 short texts from the model ("Write one short vivid sentence that is all about {label}."), plus a shared neutral set (12 texts, ordinary sentences). Injection vector V_c = mean hidden at layer L (all token positions, all texts) − neutral mean. Readout direction D_c = same at layer R. Save `library/<model_slug>.npz` with V, D, neutral baselines HR_n, vector norms, and a hash of the config. Build time on 8-core CPU ≈ 12 s per concept with the 0.5B model (≈ 6 min for 30). Commit the built library for the default model (small: 30×2×896 floats) so streamers need no build step.
- New word (not in library): `!push <new word>` triggers a background build (≈ 20–70 s CPU), overlay shows "synthesising concept…", cached after. Rate-limit: one build at a time; max 5 custom concepts per session. Stretch only.

## 7. Faction mixer (`engine/mixer.py`) — pure python, fully tested
Input events: `Push(user, faction, t, source)`.
- **Per-user weight:** a user's first push in any 8 s window counts 1.0, subsequent ones 0.25 (anti-spam); max 3 counted pushes per user per 20 s.
- **Dose:** `dose[f]` = Σ weight × 2^(−(now−t)/H) with half-life H = 20 s.
- **Shares:** `share[f] = dose[f] / Σ dose` over the top-3 factions (others dropped). **Dominance cap:** any share > 0.75 is clamped to 0.75 and the excess is moved to the 'Neutral' slot (no injection). Neutral share also = max(0, 1 − Σdose / κ) with κ = 3 (so a quiet chat gives a plain answer).
- **Strength:** β = βmax × (1 − exp(−Σdose / κ)); βmax = 1.5 default, hard max 2.0 (collapse risk above ~3 on 0.5B).
- **Schedule modes (`schedule_mode`, config + eval-selected):** which faction's vector acts on which tokens.
  - `answer` (**default**): one faction (or Neutral) is drawn by `share` at the start of each answer and acts on the prompt prefill and every token. This is the configuration measured to work for a single faction (§14). The contest is fought across answers and inside the Mind Share bar; the mixer re-draws between answers.
  - `sentence` (**experimental**): the faction is re-drawn by `share` every `chunk` tokens (default 16) so a single answer can move between factions' territory. In scratch tests the *text* barely showed it (§14), so it is promoted to default only if `make eval` metric C passes its gate (§17).
  - `token` (experimental, **measured not to work on 0.5B**, §14): re-draw every token. Keep only for the eval table.
  - Applied vector = `unit(V_f) × inject_scale × β` (`inject_scale` ≈ 10 for Qwen2.5-0.5B hidden units; calibrate in eval). Prefill injection (`inject_prefill=True`) matters: injecting only generated tokens was much weaker in scratch tests.
  - Summing two vectors ("blends") is NOT used: it gave words of both concepts in only 1–2 of 18 answers (§14).
- Outputs per tick (≈ 2 Hz): `shares`, `beta`, `top pushers`.

## 8. Generation loop (`engine/generate.py`)
- Rounds: the engine keeps generating short "answers" (24–40 tokens, 1–2 sentences) to everyday prompts from a bank of ~40 (tea, morning routine, school day, packing a bag, bike repair, …; no identity prompts). The mixer state is re-read at the start of every answer (and every `chunk` tokens in `sentence` mode), so Mind Share flips are visible every ~2 s. Between answers the overlay keeps the previous answer on screen for ≥ 2 s and keeps a history column of the last 3 answers, each with its faction colour, so a viewer sees the territory changing.
- Each token step emits `token` event: `{i, text, applied: faction|null, readout: {scores: {f: cos}, top: f|null, margin}, color: faction|null}`.
- **Colour source gate:** `colour_source = readout | applied`. Default `applied` (the server knows which faction's territory a window was generated in; the overlay labels it "territory"). It switches to `readout` (the overlay says "Mind-Reader colours") only when `results/eval.json` shows window-level agreement ≥ 0.75 over the active factions for the chosen `schedule_mode`. Per-token readout colouring was at chance in scratch tests (§14), so colours are per window (default 12 tokens), never per word.
- **Readout colouring:** `scores[f] = cos(h_R − HR_neutral, D_f)` over all library concepts; `top` = argmax among the *currently active* factions (≤ 3) plus the secret concept in Telepathy; colour = `top` only if `margin` (best − second) ≥ `τ_margin` (calibrated in eval at the 90th percentile of unsteered margins), else grey. Colour also encoded by underline style per faction index for colour-blind safety.
- Backpressure: events are produced as fast as the model allows (target ≥ 8 tok/s on CPU); overlay animates them as a word stream at a steady pace (typewriter buffer) so slow models still look smooth.

## 9. Mind-Reader
- Per-token readout vector (above) feeds the hero colouring and the small strip chart (last 60 tokens, stacked per active faction).
- **Claims allowed in UI/video, and only with eval numbers:** "Mind-Reader names the injected concept in X % of answers vs Y % for a text keyword detector" (measured on Qwen2.5-0.5B at low dose: probe 47 % vs keyword 6 % at β=0.5; 83 % at β=2). Do **not** claim "predicts the next word" unless `make eval` reports a positive lead-time (see §13 metric L); otherwise say "reads it before the words show it" only if lead-time median ≥ 1 token with p < 0.05, else drop the sentence.

## 10. Neural Immune System (`engine/immune.py`)
- Defender is a second hook at layer L+1 (after the injection point). For each library concept c it keeps the unit direction u_c (= unit V_c) and threshold τ_c = 97th percentile of `h · u_c` over unhooked neutral generations (computed by the builder, stored in the library). On each token: for the concept(s) whose projection exceeds τ_c, subtract `(proj − τ_c) · u_c` from the hidden state. Pure tensor math, unit-tested on Tiny and on numpy.
- **Detection chip:** `TAMPERING DETECTED: <concept>` when the defender fires on ≥ 3 consecutive tokens (or the Mind-Reader margin is above threshold with no matching chat push). `neutralised %` = 1 − (post-defence projection / pre-defence projection), averaged over the answer.
- **Modes:** `IMMUNE: OFF` (default for the war), `IMMUNE: ON` (toggle by streamer hotkey / chat command `!immune on` from mod/broadcaster only). The showcase "Attack" round runs the same attack twice, OFF then ON.
- **Honest scope:** it defends against *injected concept directions in the library*, an oracle-style projection clamp. It does not defend against arbitrary prompt injection. README says so.
- Measured earlier on this setup (single concept, 0.5B): attack concept mention rate 78 % → 0 % at β=2 and 44 % → 0 % at β=3, defender firing on 98.8 % of tokens; coherence not yet scored. The eval must report mention-rate drop and a simple coherence proxy (distinct-token ratio and no more than 20 % repeated 3-grams) so the claim is not "delete everything".

## 11. Telepathy round (`game/telepathy.py`)
State machine: `IDLE → ARMED(secret) → GENERATING → GUESSING(30 s) → REVEAL → IDLE`.
- Server picks a secret concept (not in the active war) from the library, injects at β = 2.0 for an everyday prompt. Overlay shows the answer text and the Mind-Reader bars with **labels hidden** ("A", "B", "C" top-3 candidates replaced with blank bars).
- Chat guesses by typing `!guess <word>` (alias-matched). First correct wins a point for that user (in-memory scoreboard, top 5 shown). A guess that matches wins immediately; at timeout reveal the answer.
- Reveal card: secret concept, Mind-Reader's top guess (it is right in X % of rounds per eval), who guessed first.
- Pure state machine, unit-tested with a fake clock.

## 12. Twitch integration (all free; no Extension; no Affiliate features)
Register a Twitch app (Client Type **Public**) at dev.twitch.tv/console; env `NOUS_TWITCH_CLIENT_ID`.
- **Auth (`twitch/auth.py`) — Device Code Grant Flow:** `POST https://id.twitch.tv/oauth2/device` (form: `client_id`, `scopes="user:read:chat user:write:chat"`) → show `verification_uri` + `user_code`; poll `POST https://id.twitch.tv/oauth2/token` with `grant_type=urn:ietf:params:oauth:grant-type:device_code`, `device_code`, `client_id`, `scopes` until success (handle `authorization_pending`, honour `interval`, stop at `expires_in`). Store `{access_token, refresh_token, expires_at, user_id, login}` in `~/.config/nous/token.json` (0600). Access tokens last ~4 h; refresh tokens are single-use and expire after 30 days idle, so always persist the new refresh token atomically; refresh at 5 min before expiry or on 401. Validate via `GET https://id.twitch.tv/oauth2/validate`.
- **EventSub WebSocket (`twitch/eventsub.py`):** connect `wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30`. On `session_welcome` (must subscribe within 10 s) `POST https://api.twitch.tv/helix/eventsub/subscriptions` with `{type:"channel.chat.message", version:"1", condition:{broadcaster_user_id, user_id}, transport:{method:"websocket", session_id}}` (headers `Authorization: Bearer`, `Client-Id`). Handle `session_keepalive` (reconnect if none within timeout+5 s), `session_reconnect` (open the new `reconnect_url` first, then close the old one; do not resubscribe), `notification`, `revocation`, exponential-backoff reconnect with resubscribe. Optional second subscription `channel.raid` (condition `to_broadcaster_user_id`) → "reinforcements": +2 dose for a random faction named in the raid message… (stretch; cut first).
- Parse: dedupe by `message_id`; ignore the bot/broadcaster's own bot replies; normalise to `Push`.
- **Send Chat Message (`twitch/chat_send.py`):** `POST https://api.twitch.tv/helix/chat/messages` `{broadcaster_id, sender_id, message}`; ≤ 200 chars; max 1 message / 5 s; messages: round start/end, Telepathy reveal, short "Team X leads" announcements (at most every 60 s). Failures are logged and ignored.
- The exact JSON field names above are from memory of the public docs; verify against live Twitch on the streamer PC in the first live test and fix with a test fixture.
- Unit tests use recorded-style JSON fixtures and an in-process fake WebSocket/HTTP server (`aiohttp.test_utils`).

## 13. Eval harness (`make eval`) — the evidence table
`nous eval` writes `results/eval.json`, `results/eval.md`, and updates the README table. Real model required for headline numbers; with Tiny/Mock it runs a smoke version and stamps `TINY MODEL / CI`.
Metrics (all with n, seeds, and 95 % Wilson intervals):
- **A. Readout vs text detector.** For each of 12 concepts × 3 prompts × 3 seeds at β ∈ {0.5, 1, 2}: does the Mind-Reader (argmax cosine over the library, answer-level mean hidden) name the injected concept? Compare with a keyword/alias detector on the generated text. (Earlier scratch result on this model: 47/58/83 % vs 6/22/39 %; use as a sanity target, not a promise.)
- **B. Immune before/after.** Same attacks with defender OFF/ON: concept-mention rate, readout score, coherence proxy.
- **C. Faction contest.** Two-faction answers in each `schedule_mode` (answer / sentence / token): % of answers containing alias words of both factions; per-window agreement between applied faction and Mind-Reader colour (over 2 factions, chance 0.5; over all, chance 1/30). Gate: §17. §14 gives the early scratch result (token mode failed).
- **L. Lead time.** For single-concept injection, first token index where the Mind-Reader score for the injected concept exceeds its threshold vs first token index where an alias word appears in text; report median difference and % of answers where the readout leads. If no lead is shown, the README must say "no lead-time claim".
- **T. Telepathy.** Mind-Reader top-1/top-3 accuracy over 60 secret rounds.
- **S. Speed.** tokens/s with and without hooks on the current hardware.
The README table is regenerated between `<!-- EVAL:START -->` / `<!-- EVAL:END -->` markers and the same JSON feeds the video stat cards.


## 14. Feasibility evidence from the planning box (scratch tests, not in the repo)
Qwen2.5-0.5B-Instruct, CPU, random seeds fixed, small n; treat as direction not proof.
- **Single faction on the whole answer (prefill + all tokens injected):** the faction's word appeared in the answer in 28 / 47 / 56 % at β = 1 / 2 / 3 (n=36 per cell per setting; scratch aggregate). Answer-level readout named the injected concept 47 / 58 / 83 / 100 % at β = 0.5 / 1 / 2 / 3, vs 6 / 22 / 39 / 53 % for a text keyword detector.
- **Two factions inside one answer:** per-token alternation (prefill uninjected) gave words of both factions in 0/18 (β=1, chunk 1), 0/18 (β=1, chunk 4), 2/18 (β=1.5, chunk 1), 0/18 (β=1.5, chunk 4). The two "hits" were poetic mixes of sea and star imagery with garbled words. **Summed vector blend**: 2/18 (β=1) and 1/18 (β=1.5). **Per-token readout** agreed with the applied faction at chance (0.42–0.54 over two factions; 0.11–0.21 over six).
- **Sentence-length chunks (16 tokens) with prefill injection:** 16-token chunks, β=2, 3 pairs × 3 prompts (9 answers per setting; windows overlap so n is small and not independent). With prefill injected: the chunk's own faction word appeared in its chunk in 3/24 chunks (other faction's word 2/24); both factions' words in one answer 1/9; **window-level readout named the applied faction in 41/56 windows (0.73; chance 0.50)**. Without prefill injection: own-word 2/27, other 2/27, both 0/9, window readout 57/63 (0.90). Reading: the Mind-Reader sees internal state change that the text barely shows (the 0.5B model needs whole-answer injection to show concept words), but this readout is partly circular (it reads the injected direction itself) and the sample is small. So: contest at answer granularity, colour by answer, treat window readout as a promising but unproven extra.
- **Free-chat topic clustering** (raw chat messages as vectors): purity 0.40, 1-NN-style accuracy 0.25 (chance 0.17); message vectors did not inject topics (0–6 %). Not used.
- **Not tested:** the real pipeline end to end, GPU, models above 0.5B, OBS/Twitch live.
Design consequences: injection includes the prefill; default colour source is `applied` until the Mind-Reader window metric passes; the hero claim is gated (§17).

## 15. Overlay (`overlay/`, 1920×1080, browser source, no build step)
Design spec for the hero view (the one frame that must be perfect):
- Canvas fixed 1920×1080, scaled by CSS transform to fit; `?bg=transparent` for OBS; dark theme default `#0B0F1A`, text `#F5F7FA`.
- **Top bar (0–96 px):** left `NOUS` wordmark (no Twitch logos); centre round label (e.g. "Answer 7 · Explain how to make tea"); right chips: source badge (`LIVE` red / `REPLAY` amber / `SIMULATED ×40` grey outlined), `IMMUNE: OFF|ON`, `TAMPERING DETECTED: ocean` (red, only when firing).
- **Hero text panel (x 120–1800, y 150–700):** the Subject's answer, 56 px / line-height 1.35, ≤ 5 lines, words appear with a 120 ms fade; each sentence/window coloured by faction (per `colour_source`, never per word; Okabe–Ito palette: #E69F00, #56B4E9, #009E73, #F0E442, #D55E00, #CC79A7, #0072B2) with a 4 px underline whose style (solid / dashed / dotted) also encodes the faction; neutral words `#F5F7FA`. A small legend row beneath: ● Team Ocean ● Team Space.
- **Mind Share bar (y 740–840):** full-width 1680 px, height 80 px, segments per faction + grey Neutral, 600 ms ease transitions, in-segment text "OCEAN 54 %" (≥ 32 px, auto-hide label if segment < 12 %). A "75 % cap" tick mark.
- **Lower third (y 880–1040):** left (x 120–1080) Mind-Reader strip chart (stacked area last 60 tokens, ≥ 24 px labels, a vertical "now" cursor); right (x 1120–1800) ticker of the latest 5 pushes: `name → faction` (names taken from Twitch display names; sim names visibly tagged `sim`).
- Accessibility: contrast ≥ 4.5:1; never flash > 3 Hz; all state also readable without colour; minimum font 28 px for anything.
- Modes of the same screen: **War** (above), **Attack** (split: left IMMUNE OFF, right IMMUNE ON, same prompt, two columns), **Telepathy** (bars unlabeled, "Guess in chat: !guess <word>", countdown ring, scoreboard), **Stats** card (renders from `results/eval.json`).
- Mode switch is announced by a 1.5 s caption ("ROUND: TELEPATHY").
- First-time viewer onboarding: an always-visible one-line instruction pill: "Type a word to join a team: ocean · space · jazz · horror".

## 16. Recording, replay, offline demo
- **Recorder:** JSONL, one line per record: `{t, kind: "push"|"frame"|"mode"|"meta", ...}`; `meta` stores config, seeds, model slug, library hash, app version.
- **Replay:** `nous replay file.jsonl` (a) `--engine` re-feeds the recorded pushes through the engine with the recorded seeds (deterministic on the same hardware and model; labelled `REPLAY`), or (b) `--frames` plays back the recorded output frames exactly (needs no model; always reproducible; used for the golden run that judges can run).
- **Demo mode:** `nous demo` → labelled simulated crowd (`sim/crowd.py`): N (default 40) synthetic users with names tagged `sim_*`, each choosing a faction with a seeded script (e.g. waves for Team A then B). Badge `SIMULATED ×N` is mandatory, shown always, and the crowd is off when connected to Twitch unless `--sim` is passed explicitly (then both badges show).
- Golden run files committed under `golden/`: `golden_run.jsonl` (recorded real session on the streamer PC) and `demo_script.json` (seeded sim script).

## 17. Gates and decision rules
- Default hero (no gate needed): **territory flips between short answers** — the last 3 answers shown with faction colours, the Mind Share bar swinging, chat names in the ticker. Copy says "flips", never "inside one sentence".
- Upgrade to "two factions inside one answer" only if metric C passes: ≥ 50 % of two-faction answers contain alias words of both factions AND window agreement ≥ 0.75. Scratch result was 0–11 % (§14), so expect not to claim this.
- Mind-Reader colouring claim only if window agreement ≥ 0.75; else say "territory".
- Mind-Reader "before the text shows it" only with metric L (§13).
- Immune claim is relative reduction in concept mentions with a coherence check; quote the measured numbers only.
- If real-model throughput < 8 tok/s on the streamer PC, drop to `Qwen2.5-0.5B` bf16 on CPU with a shorter answer length (40 tokens), or enable GPU.
