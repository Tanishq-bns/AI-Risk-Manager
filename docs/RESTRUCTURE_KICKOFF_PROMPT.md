# Repository Restructuring Kickoff Prompt — AI Risk Manager

Paste everything below into Antigravity with the `Tanishq-bns/AI-Risk-Manager` repo open.

---

You are restructuring the file/folder organization of an existing, working repository. **This is a housekeeping and documentation-consolidation task, not a feature or architecture change.** The single most important success criterion is: **the application behaves identically after your changes as before them.** If you are ever unsure whether a change is purely organizational or could affect behavior, treat it as behavioral and stop to ask.

## Non-negotiable safety contract — read this before touching anything

1. **Establish a verified baseline before any change.** Confirm `git status` is clean, then run, in order, and save the real output of each: `pytest` (note the exact pass count — the README currently claims 185 tests, verify the real number), `python scripts/failure_drills.py` (note the real pass count — README claims 17/17), `python scripts/benchmark_performance.py` (note real P50/P95/P99), and start the server (`uvicorn risk_manager.api.app:app --host 127.0.0.1 --port 8000`) and manually exercise all 5 demo scenarios (Legitimate, Suspicious, Serial, Critical, Prompt Injection) plus the review-queue override flow. Save this baseline output — you will diff against it at the end.
2. **Commit a checkpoint tag before you start** (e.g., `git tag pre-restructure-baseline`) so anything can be instantly reverted.
3. **No source code logic changes.** You may move files, rename files, delete genuinely unused/dead files, merge documentation, and fix broken links or factually wrong instructions in docs. You may **not** change any `.py` file's logic, any API contract, any schema, any config default, or any frontend behavior.
4. **Every file you move, merge, or delete must have every reference to it fixed in the same step** — check `README.md`, every file under `docs/`, and (for anything with an actual code citation) the docstrings/comments in `risk_manager/`, `tests/`, `scripts/`, `alembic/` that mention it by name. A restructure that leaves broken links or dangling citations is not done.
5. **Re-verify every claim in this prompt yourself before acting on it** — the analysis below is accurate as of when it was written, but re-run the greps yourself (commands are given) before deleting anything, in case the repo has changed since.
6. **After finishing, re-run the entire baseline from step 1 and confirm identical results**: same (or explicitly reconciled) test count, same drill pass count, same benchmark ballpark, same behavior on all 5 demo scenarios and the override flow, zero new console errors on the dashboard. Report the before/after diff explicitly.

## Verified ground truth (re-check before acting)

**Confirmed via `git clone` + `find` + `grep` on the real repository:**

- `reports/` (13 `.md` + 8 `.json` files, e.g. `MODEL_ABLATION.md`+`model_ablation.json`, `heldout_test/results.json`, `heldout_test/ACCESS_LOG.md`) is well-organized with zero redundancy — every file has a distinct purpose and a unique paired JSON artifact. **Do not touch anything inside `reports/`.**
- `docs/` contains 25 files. Most (`AGENTS.md`, `API.md`, `ARCHITECTURE_GUARDRAILS.md`, `DECISION_INTELLIGENCE.md`, `DEMO.md`, `ECONOMICS.md`, `FAILURE_MATRIX.md`, `FEATURES.md`, `JUDGE_QA.md`, `MODEL_GOVERNANCE.md`, `MODEL_LINEAGE.md`, `OBSERVABILITY.md`, `POLICY.md`, `SECURITY_MODEL.md`, `FINAL_DEMO_SCRIPT.md`, `SUBMISSION_CHECKLIST.md`) are genuinely distinct reference documents — **leave these as-is**, just confirm this yourself (distinct `# ` heading, no near-duplicate content).
- The following 9 files in `docs/` are redundant meta/status reports with **zero references from any `.py` file** (confirmed via `grep -rn "FILENAME" --include="*.py" .`) and are pure narrative overlap with each other: `FINAL_AUDIT.md`, `FINAL_HEALTH_CHECK.md`, `FINAL_PROJECT_EXCELLENCE_REPORT.md`, `FINAL_SUBMISSION_REPORT.md`, `FINAL_VALIDATION.md`, `PHASE9_FINAL_REPORT.md`, `PHASE9_GAP_ANALYSIS.md`, `PROJECT_ARTIFACT_INVENTORY.md`, `COMPETITIVE_GAP_ANALYSIS.md`.
- Two root-level files, `CURRENT_STATE_AUDIT.md` and `IMPLEMENTATION_AUDIT.md`, are the same kind of orphaned meta-report, also zero code references, also not linked from the current `README.md`.
- **However**, `README.md` §18 currently links to three of the 9 `docs/` files above: `FINAL_SUBMISSION_REPORT.md`, `FINAL_HEALTH_CHECK.md`, and `FINAL_AUDIT.md`. Those links must be repointed, not left broken.
- 8 root-level files — `ARCHITECTURE.md`, `PLAN.md`, `PRD.md`, `ROADMAP.md`, `SPEC.md`, `STATE.md`, `SUMMARY.md`, `TRD.md` — are **cited by name in docstrings/comments across 60+ real source files** (confirmed via `grep -rn "TRD.md\|SPEC.md\|PLAN.md\|STATE.md\|PRD.md\|ARCHITECTURE.md" --include="*.py" .` — e.g. `risk_manager/ml/cascade.py: """Implements ARCHITECTURE.md §6/§7..."""`, `risk_manager/domain/schemas/enums.py: """Calibrated risk probability bands (SPEC.md §18)."""`). These are the original specification documents the implementation was built against. **They must be preserved in full — relocated, never deleted or content-edited** — because the codebase's own documentation trail depends on them existing under those exact filenames.
- `frontend/` at repo root contains only a `.gitkeep` — the real, working frontend lives at `risk_manager/api/static/{app.js,index.html,styles.css}`, mounted directly by `risk_manager/api/app.py`. This root `frontend/` folder is dead and confusing.
- Top-level `demo/` package contains only `demo/__init__.py` (a docstring, no code) and is imported nowhere. **Do not confuse this with `risk_manager/api/routers/demo.py`, which is live and must not be touched** — the dead one is the top-level `demo/` folder only.
- `risk_manager/cache/__init__.py` and `risk_manager/streaming/__init__.py` are each a single docstring line with zero implementation and zero imports anywhere in the codebase (confirmed via `grep -rn "risk_manager.cache\|risk_manager.streaming" --include="*.py" .` returning nothing). Whatever caching/fallback logic actually runs today lives elsewhere (verify where — likely inline in `risk_manager/api/services/risk_service.py` or `risk_manager/core/config.py` — do not remove any of that real logic, only these two empty package stubs).
- `scripts/.gitkeep` is unnecessary — `scripts/` already contains 13 real, working scripts.
- `README.md`'s reproducibility guide instructs `pip install -r requirements.txt`, but **no `requirements.txt` exists anywhere in the repo** — the actual packaging is `pyproject.toml` with extras (`ml`, `dev`, `agents`, `all`). This is a real, broken instruction for anyone following the README today.

## The restructuring plan

Execute in this order. Commit after each phase so any issue can be isolated and reverted independently.

### Phase R0 — Baseline (see safety contract step 1)

Capture and save the full baseline output described above before making any change.

### Phase R1 — Remove confirmed-dead scaffold

After independently re-confirming each item above is genuinely unreferenced:
- Delete `frontend/` (root-level, `.gitkeep`-only folder).
- Delete the top-level `demo/` package (`demo/__init__.py`), **not** `risk_manager/api/routers/demo.py`.
- Delete `risk_manager/cache/` and `risk_manager/streaming/` packages — but first locate and note where the actual cache-fallback and event-handling logic that the README describes ("in-process bounded LRU cache fallback", "in-memory asynchronous pub/sub fallback") really lives, so nothing real is lost, only the empty stubs.
- Delete `scripts/.gitkeep`.
- Run the test suite. It must show the identical pass count as the Phase R0 baseline.

### Phase R2 — Relocate the specification documents (content unchanged)

Create `docs/spec/` and `git mv` these 8 files into it, with **zero content edits**: `ARCHITECTURE.md`, `PLAN.md`, `PRD.md`, `ROADMAP.md`, `SPEC.md`, `STATE.md`, `SUMMARY.md`, `TRD.md`. Add one sentence at the top of each, e.g. `> Relocated from repo root to docs/spec/ on <date> for repository organization; content unchanged. Cited throughout the codebase as "TRD.md §X" etc. — see docstrings.` This preserves the provenance trail while explaining the move to a future reader. Do not touch anything inside these files beyond that one added line.

### Phase R3 — Consolidate the redundant meta-reports (read first, never blind-delete)

Read the full content of all 11 files: root `CURRENT_STATE_AUDIT.md`, root `IMPLEMENTATION_AUDIT.md`, and `docs/FINAL_AUDIT.md`, `docs/FINAL_HEALTH_CHECK.md`, `docs/FINAL_PROJECT_EXCELLENCE_REPORT.md`, `docs/FINAL_SUBMISSION_REPORT.md`, `docs/FINAL_VALIDATION.md`, `docs/PHASE9_FINAL_REPORT.md`, `docs/PHASE9_GAP_ANALYSIS.md`, `docs/PROJECT_ARTIFACT_INVENTORY.md`, `docs/COMPETITIVE_GAP_ANALYSIS.md`.

Write one new file, `docs/PROJECT_STATUS.md`, that:
- States the current, real, final status of the project (test count, drill count, latency, economic figures — pulled from `reports/`, never re-typed by hand from memory).
- Preserves every genuinely unique fact, decision, or caveat found across the 11 source files (do not drop real content — only drop repeated framing and stale "as of Phase N" language that's since been superseded).
- Is organized clearly (e.g., sections: Current Status, Test & Quality Summary, Architecture Audit Summary, Known Gaps, Submission Readiness) so a reader gets everything the 11 files gave them from one place.

Then:
- Update `README.md` §18's three links (`FINAL_SUBMISSION_REPORT.md`, `FINAL_HEALTH_CHECK.md`, `FINAL_AUDIT.md`) to point to `docs/PROJECT_STATUS.md` instead.
- Search the whole repo once more for any other reference to any of the 11 filenames and fix or remove it.
- Only once you've confirmed zero remaining references, delete the 11 original files.

### Phase R4 — Fix the packaging instruction

Correct `README.md`'s reproducibility guide: replace `pip install -r requirements.txt` with the command that actually matches `pyproject.toml` (e.g. `pip install -e ".[all]"` for full dev+ml+agents, or the appropriate extras combination). Verify by actually running the corrected command in a clean virtual environment and confirming the app starts.

### Phase R5 — Final structure check

The clean root should now contain only: `README.md`, `Dockerfile`, `docker-compose.observability.yml`, `pyproject.toml`, `alembic.ini`, `.gitignore`, and the folders `alembic/`, `docs/`, `models/`, `monitoring/`, `reports/`, `risk_manager/`, `scripts/`, `tests/`. No stray `.gitkeep`-only folders, no orphaned root-level markdown.

### Phase R6 — Full re-verification against baseline (see safety contract step 6)

Re-run everything captured in Phase R0. Produce a short before/after report: file count at root before vs. after, total `.md` file count before vs. after, test pass count before vs. after (must match), failure-drill pass count before vs. after (must match), benchmark P95 before vs. after (should be in the same ballpark), and explicit confirmation that all 5 demo scenarios and the manual-override flow behave identically on the running dashboard.

## Manual action protocol

If you find anything that contradicts what's stated above (a reference I didn't catch, a file that turns out to be imported somewhere non-obvious, a piece of logic hiding inside `risk_manager/cache/` or `risk_manager/streaming/` that isn't just a docstring), **stop, do not delete it, and report it back to me** with what you found instead of proceeding on the assumption in this prompt. Same for any judgment call not covered here (e.g., whether `SUBMISSION_CHECKLIST.md` should be folded into `docs/PROJECT_STATUS.md` too, or kept standalone since it's a distinct artifact type) — flag it as:

```
## MANUAL DECISION NEEDED
What you found / what changed my assumption / the options / your recommendation
```

and continue with unrelated, unblocked work while you wait for my answer. Never delete something because it merely looks unused if your own re-verification doesn't confirm it — an incorrectly deleted file is a far worse outcome than an extra confirmation question.
