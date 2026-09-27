# Arbitrator — Development Timeline & Changelog

Arbitrator (public as **Arbitrator-AI**, `github.com/UnabashedVoice/Arbitrator-AI`) is an ethical deliberation and decision-education engine. It analyses the likely consequences of a proposed action before it is carried out. It is the oldest of the five sibling projects (Arbitrator, Actualizer, Palaestra, Annals, Compendium), and the only one that keeps a hard-constraint "seed core".

> **How this was compiled (2026-09-27).** From the git history of `main` and `origin/archive/v0.1-legacy`, the file dates inside `Backups/zipz/*.zip` and `Backups/`, the `next_session_prompt.md` handoff in `Backups/unzipz/filetree-and-nextprompt/`, the working-tree diff, the audit log at `../arbitrator_audit.jsonl`, and the cross-project batch in `../../system_runs/2026-09-26-five-question/`. Dates before the git history begins come from file timestamps and are approximate. The 2026-09-26 work, uncommitted when this was compiled, was committed and pushed on 2026-09-27.

---

## Timeline at a glance

| Date | Phase | What happened |
|---|---|---|
| 2025-04-01 | v0.1 prototype | First scenario logs (`SeedCore/data/logs/log_S001_2025-04-01T…`) from the original prototype |
| 2025-04-02 | v0.1 published | GitHub repo created; v0.1 "ethical engine" pushed, with FailureModes, decision flow and feedback/truth-table specs |
| 2026-01-25 | — | Date of the local clone of the v0.1 repo (`Backups/_OLD/`) |
| 2026-03-06 | Rebuild, part 1 | Ethics Core, Context Parser, Synthesis, Audit Log and the orchestrator bridge rewritten from scratch (`audit_log.zip`) |
| 2026-03-10 | Rebuild, part 2 | Feedback system (trust ledger), channel tests, first CLI (`SeedCore.zip`) |
| 2026-04-02 | Rebuild, part 3 | Model registry, package restructure (`SeedCore/tests/`, `cli/commands/`) |
| 2026-04-03 | Post-audit | Eight channels finalised, response parser hardened, orchestrator completed. 767 tests. Packaged as `Arbitrator-AI-post-audit.zip` |
| 2026-04-08 | — | `extract_to_mastercopy.py` flattens the zip into `Backups/mastercopy/` |
| 2026-09-14 | Import | Backups copied into this workspace as `Arbitrator-imported`. Actualizer spun off as a separate project the same day |
| 2026-09-21 | v0.2 on `main` | v0.1 archived to `archive/v0.1-legacy`; post-audit codebase committed to `main`; history rewritten to the UnabashedVoice identity |
| 2026-09-25 | Annals + fixes | `run --annals`; local folder renamed to `Arbitrator` (fixing imports that had been silently broken); UTF-8 console guard; first real local runs logged |
| 2026-09-26 | Committed 2026-09-27 | LM Studio backend, Compendium consultation, `--annals-record`; first full-stack batch (5 questions × 3 cycles × 2 models) |

---

## 2026-09-26: Compendium wiring (committed 2026-09-27)

Built on 2026-09-26, when the user asked for the Compendium to be wired into the stack. That request overrode the earlier decision to keep the Compendium separate. All of it is opt-in. It adds 11 modified files (+246/−3) and 2 new files.

### Added
- **`LMStudioBackend`** (`SeedCore/channels/backend.py`), ported from Actualizer. It calls a local LM Studio server.
  - For gpt-oss models it renders the Harmony prompt itself and posts to `/v1/completions`. This replaces the template's injected "You are ChatGPT…" identity with `arbitrator-local-identity-v1`, which is Actualizer's user-approved local-identity text with the project name changed. `template-default` stays available for control runs.
  - Other models use `/v1/chat/completions` with their own template.
  - `strip_reasoning()` removes gpt-oss analysis channels and Qwen3 `<think>` blocks, so channels parse JSON from the answer only. The raw completion is kept in `last_raw`.
  - The identity key is appended to `model_id`, so every channel output and Annals case says which identity produced it.
- **`ARBITRATOR_LMSTUDIO_MODEL`** (and `ARBITRATOR_LMSTUDIO_URL`). When set, LM Studio becomes the *only* candidate in `model_registry._discover_candidates()`, and it also overrides `get_default_backend()`. There is deliberately no silent fallback to the mock: a run meant to test a local model must fail loudly if the model is unreachable.
- **Compendium consultation** (`SeedCore/orchestrator/compendium_link.py`).
  - One model call per run. The model reads the Compendium's level-0 index and names at most three entries, possibly none.
  - The Compendium's own text for those entries (Summary plus the strongest counter-position) is shown to channels that declare `uses_compendium`. Only `ethical_adversarial` does; the empirical channels are unchanged.
  - The consultation never raises. A failure is recorded and added to the warnings, and the run continues as it would have without it.
  - The Compendium is found at `$COMPENDIUM_ROOT` or as a sibling `Compendium/` folder.
- `OrchestratorConfig.use_compendium`, the `run --compendium` flag and a `compendium` config default (`False`).
- New audit entry kind `compendium_consulted`, with `writers.write_compendium_consulted()`. It logs the entries chosen, the reasons, any ids the model named that don't exist, and the raw selection output. Disclosed text is identified by the Compendium version, not copied.
- `PipelineResult.compendium`. The CLI prints the consultation's identity line.
- **`run --annals-record FILE`** chooses which Annals record to append to (default `$ANNALS_RECORD`, else the Annals' own record). This lets test batches write to a throwaway record, because the real record is append-only.
- `SeedCore/tests/test_compendium_link.py`: 13 tests covering Harmony/`<think>` stripping, env-var backend selection, which channels see referents, verbatim disclosure, empty and unparseable selections, and orchestrator recording with and without the flag.

### Verified in use
- **First full-stack batch** (`system_runs/2026-09-26-five-question/`, started 2026-09-26 13:12). Each run is a real `arbitrator run --compendium --annals --annals-record … --json` CLI call, going LM Studio → eight channels → Compendium → synthesis → Annals test record.
  - gpt-oss-20b finished all 15 runs (5 questions × 3 cycles) by 20:47, at about 19–66 minutes per question.
  - qwen3-32b (16k context) had finished 2 of 15 when this was written. Run 3 started at 23:51 and was still in progress.
  - All runs completed (`ok=True`) and were recorded in the Annals test record.
  - Question q5 (a coastal-city short-term-rental tax) consistently drew an **empty** Compendium selection, which is correct: the corpus doesn't cover it. The AI-agent questions drew personal-identity entries (Parfit, Locke, Boethius, `llm-identity-contemporary`, Korsgaard).
- Findings from that batch:
  - Routing invoked only 3 channels per question.
  - The Ethics Core pre-screen FAILs these proposals on structural estimates alone, so the batch needs `continue_after_fail`.
  - A run blocked by the Ethics Core has no consequence map, so it can't be recorded in the Annals.
  - Models reused finding ids across channels, which exposed an Annals intake bug (fixed in the Annals).

---

## 2026-09-25

### `a9dd9aa` — Tighten the stdout/stderr encoding guard to match Actualizer and Annals
- Wrapped `reconfigure()` in `try/except` as well as the `hasattr()` check. Display should never be what breaks a run whose analysis succeeded. 767/767 tests pass.

### `e4d5109` — Reconfigure stdout/stderr to UTF-8 in `main()`
- **Fixed:** on a cp1252 Windows console, the non-ASCII glyphs in `display.py` raised `UnicodeEncodeError`. That was what silently turned a successful `run --annals` into "Not recorded in the Annals". The guard is a no-op when a test replaces stdout. 767/767.

### `40dc6a0` — Update stale path in `annals_link` docstring after local folder rename
- **Local folder renamed** from `Arbitrator-imported` to `Arbitrator`. The `Arbitrator.*` absolute imports used throughout `cli/` need a directory literally named `Arbitrator` on `sys.path`, so the whole `arbitrator run` CLI had been raising `ModuleNotFoundError`. `Backups/unzipz/Arbitrator-AI-post-audit/Arbitrator/` shows this was always the intended layout.
- **Test suite went from 616/616 (with 2 import-error stubs) to 767/767.** `python -m Arbitrator.cli.main run` now runs the real pipeline end to end.
- The first real runs are logged at `../arbitrator_audit.jsonl` (opened 2026-09-25T04:38Z, 42 entries).

### `5d66bf3` — Add `run --annals`: record a recommendation in the Annals
- New `cli/annals_link.py`. It opens an Annals case from a run, locking each consequence-map finding in as a prediction before any outcome is known.
- Annals is found at `$ARBITRATOR_ANNALS` or as a sibling folder, and is unused without the flag.
- New flags `--annals`, `--annals-people FILE` and `--annals-question TEXT`.
- A failed record never discards the analysis: it warns "Not recorded in the Annals".
- Committed at the same moment (00:10:26) as the matching wiring in Actualizer, Palaestra and the Annals' own first commit.

---

## 2026-09-21 — v0.2 lands on `main`

### `83b9e1b` — Remove duplicate CLI files superseded by `cli/commands/`
- Deleted `cli/audit.py`, `config.py`, `feedback.py` and `run.py` (−806 lines). They were byte-identical copies left over from the April refactor, and `main.py` imports only from `cli/commands/`.

### `5d5954e` — Initial commit: post-audit modular codebase
- The v0.1 architecture was moved to the `archive/v0.1-legacy` branch, and `main` was replaced with the post-audit codebase: 80 files, +30,648 lines.
- **SeedCore subsystems:**
  - `ethics_core/`: the Prime Directive, five absolute hard constraints (existential harm, targeting conscious entities, mass harm for individual gain, irreversible ecological destruction, high-uncertainty catastrophic risk), and a five-verdict truth table (`pass`, `fail`, `ambiguous`, `escalate`, `hard_reject`) over HarmScore, BenefitScore and AffectsConsciousEntity.
  - `context_parser/`: domain, population and flag extraction, and the routing manifest.
  - `channels/`:
    - Eight specialist channels. Four are primary (economic, ecological, social_demographic, ethical_adversarial) and emit flags. Four are secondary (legal_institutional, historical_precedent, geopolitical, uncertainty_modeling) and consume those flags.
    - A pluggable `backend.py` (Anthropic, Ollama, Mock), a hardened `response_parser.py`, and `model_registry.py` (capability profiles and channel-aware model selection).
  - `synthesis/`: channel-output aggregation and the `ConsequenceMap` builder.
  - `audit_log/`: a tamper-evident, append-only hash chain.
  - `orchestrator/`: the full pipeline (Input → Context Parser → Ethics Core → channels → Synthesis → Confidence Check → Consequence Map → Human Review). `HARD_REJECT`/`FAIL` halt the pipeline.
  - `feedback/`: a trust-weighted, role-tiered feedback system (`trust_ledger.py`, which saves atomically by temp file and `os.replace`).
- **CLI:** `cli/main.py` (argparse), `display.py`, `config_manager.py`, and the `run`, `feedback`, `audit`, `config` and `models` commands.
- **Docs:** `docs/Arbitrator_Architecture_v0.1.docx` and `.pdf`.
- The same day, the history on `main` and `archive/v0.1-legacy` was **rewritten to the UnabashedVoice identity** before the sibling repos went public. Clones made before this date may still carry the old author address.

---

## 2026-09-14 — Imported into this workspace
- `Backups/` (containing `_OLD`, `zipz`, `unzipz` and `mastercopy`) was copied into `Arbitrator/Arbitrator-imported`.
- Design discussions that day led to:
  - **Actualizer** being split off as a separate, consciousness-oriented project.
  - The seed core (immutable, sealed hard constraints) being confirmed as **unique to Arbitrator**. Actualizer takes no floor (decided 2026-09-15).

---

## 2026-03-06 → 2026-04-08 — The pre-git rebuild (reconstructed from archive timestamps)

These dates come from the files inside `Backups/zipz/*.zip`. They reflect the snapshots that survived, not necessarily the day each file was first written.

- **2026-03-06:** `ethics_core/` (constraints, evaluator, models, scoring, truth_table, tests), `context_parser/` (extractors, lexicons, models, parser, tests), `synthesis/` (consequence_map, synthesizer, tests), `audit_log/` (log, models, writers, tests), and `orchestrator/bridge.py` and `result.py`. Snapshot: `audit_log.zip`.
- **2026-03-10:** `feedback/` (aggregator, models, processor, trust_ledger, validator, tests), `channels/test_channels.py`, and the first CLI (`audit`, `config`, `config_manager`, `display`, `feedback`, `run`, `test_cli`). Snapshot: `SeedCore.zip`.
- **2026-04-02:** `channels/model_registry.py` and its tests, `cli/commands/models.py`, and the package restructure into `SeedCore/tests/` and `cli/commands/`. Side snapshots: `unzipz/modelselect/`, `unzipz/hardened-response-parser/`.
- **2026-04-03:** all eight channel modules, `channel_output.py`, `backend.py`, `channel_stubs.py`, `orchestrator.py`, `cli/commands/*` and `main.py`, and the consolidated `SeedCore/tests/*`.
  - The handoff at the time lists 767 passing tests: Ethics Core 65, Context Parser 93, Synthesis 81, Audit Log 82, Orchestrator 83, Channels 108, Feedback 102, CLI 80, Model Registry 73.
  - The Anthropic and Ollama backends were implemented but fell through to `MockBackend` in development.
  - Packaged as `Arbitrator-AI-post-audit.zip` (90 files).
- **2026-04-08:** `extract_to_mastercopy.py` extracts the zip flat into `mastercopy/`. `mastercopy/updated-system-design.md` and `system-prompt.md` are larger, speculative design notes from this period.

---

## 2025-04-02 — v0.1 (now `archive/v0.1-legacy`)

| Commit | Change |
|---|---|
| `d093581` | Initial commit: `.gitignore`, `LICENSE` |
| `33f185b` | **Initial Arbitrator-AI ethical engine.** `SeedCore/`: `ethics_rules/base_rules.json` and `conflict_matrix.json`; validators (`ethics_validator.py`, `adversarial_module.py`, `scenario_parser.py`); `reasoning/llama_bridge.py`, a local LLM bridge (other reasoning modules were stubs); a test scenario and two run logs from 2025-04-01; README, CONTRIBUTING, `run_arbitrator.py`. Core values: *Mutual Benefit Over Individual Gain; Minimize and Mitigate Harm; All Consciousness Is Sacred.* |
| `88d358c` | Merged the GitHub-created branch |
| `c6458d9` | README links Known Failure Modes |
| `20b5ae5` | `docs/FailureModes.md`: value misalignment, capture by power structures, and others, each with causes and mitigations |
| `79ea69f` / `cf704b0` | `specs` created as an empty file, then deleted |
| `edf3d2a` | `specs/decision_flow.md`: Mermaid flow (Input → Context Parsing → Ethics Core → Adversarial Simulation → Consequence Map → Confidence threshold → publish or human review) |
| `06d8ee1` | `specs/feedback_schema.md`, `specs/truth_table_ethics.md` |

---

## Open items
- **Arbitrator training in Palaestra:** not built. Annals cases correctly record `palaestra_lineage: none`.
- **Ethics Core pre-screen:** it FAILs most real proposals on structural estimates alone. A blocked run leaves nothing for the Annals to record.
- **Falsifiers:** Arbitrator doesn't state its own falsifiers, so Annals predictions get a generic `wrong_if`.
