# Omi → ExoCortex Integration — Independent Review

**Reviewer:** automated adversarial reviewer (separate session; does NOT implement).
**Source of truth:** `OMI-EXOCORTEX-INTEGRATION-PLAN.md` (this worktree).
**Method:** verify actual code/state, not progress claims; try to BREAK each "done" phase.
**Verdict legend:** `REVISE` (blocking, fix next) · `ACCEPT` (meets criteria + survives break-tests) · `NOT STARTED` (no implementation to verify).

> **REVISE items go at the very top of this file.** As of the latest cycle there are none —
> because nothing has been built yet (see Cycle Log).

---

## Cycle Log

### Cycle 7 — 2026-06-21 ~05:07 EDT — **NO CHANGE** (clean at `cb051f73f`; no progress file; no code edits in 70 min).

### Cycle 6 — 2026-06-21 ~04:05 EDT — **NO CHANGE** (clean at `32465118d`; no progress file; no code edits in 70 min).

### Cycle 5 — 2026-06-21 ~03:03 EDT — **NO BUILD CHANGE** (clean at `3f5c5c667`; no progress file). Touched files were unrelated existing automation (weekly-import-reconciliation report, gmail token refresh), not the integration build.

### Cycle 4 — 2026-06-21 ~02:01 EDT — **NO CHANGE** (clean at `13522a1db`; no progress file; no code edits in 70 min).

### Cycle 3 — 2026-06-21 ~00:59 EDT — **NO CHANGE** (worktree clean at `4384103ed`; no progress file; no code edits in 70 min).

### Cycle 2 — 2026-06-20 ~23:54 EDT — verdict: **NO BUILD CHANGE**
- Worker worktree clean at `334656a97` (cycle-1 commit); no new commits, no untracked code, **still no progress file**.
- No code/migration changes in any ExoCortex worktree. Only runtime artifacts touched: ExoCortex `omi-sync` + `limitless-sync` **logs/state** (`data/import-state/omi-atomic-state.json`, `logs/*sync-20260620.log`) — the EXISTING pull jobs are **live/running**, not dormant. Reviewer note for Phase 0/1: when built, confirm last-success + cursor against `omi-atomic-state.json` rather than trusting a "ran today" claim.
- Build not started → nothing to ACCEPT/REVISE.

### Cycle 1 — 2026-06-20 ~23:05 EDT — verdict: **NOTHING TO VERIFY (build not started)**

**What I actually checked (not claims):**
- Worker worktree `Omi/.claude/worktrees/distracted-darwin-eed00f`: `git status` shows only **untracked** planning docs (`OMI-EXOCORTEX-INTEGRATION-PLAN.md`, `OMI-EXOCORTEX-CONTRIB-PLAN.md(.evolved)`). `git log` = main (`617e41cc9`); **no project commits, no code diff.**
- **No `OMI-EXOCORTEX-INTEGRATION-PROGRESS.md` exists** anywhere — the worker has not begun the progress-tracked build.
- ExoCortex `supabase/functions/omi-connector/index.ts` is the **pre-existing** connector named by Phase 0; it has **not** been modified for this project (no new commits referencing it).

**Conclusion:** The plan is written and sound; **implementation has not started.** No phase is claimed or done, so there is nothing to ACCEPT or REVISE this cycle. The review framework and baseline below are pre-loaded so later cycles can adversarially check the worker's claims fast.

**Process flags for the worker (not blocking, but fix early):**
1. **No progress file.** The build should maintain `OMI-EXOCORTEX-INTEGRATION-PROGRESS.md` (what phase, what's claimed done, where the code/migrations are). Without it, "done" claims can't be located.
2. **Plan was untracked** (at risk of loss). I have backed it up to the fork this cycle (see Push log) — not upstream.
3. **Code vs plan live in different repos.** The plan is in this Omi worktree; the implementation (omi-connector, migrations, entities) is in **ExoCortex**. State clearly *which ExoCortex worktree/branch* holds the build so the reviewer inspects the right tree.

---

## Baseline ground truth (for adversarial checks in later cycles)

Recorded from the **current** ExoCortex `supabase/functions/omi-connector/index.ts` (main checkout):
- **`person_id` is dropped today.** Segments are flattened to `"Speaker: text"` via `firstNonEmpty(speaker_name, speaker, speakerId)` (`index.ts:156-157`) — a **display-name string**, not the stable id. → Phase 3 premise is valid; when Phase 3 is claimed, verify the entity link keys on `omi:person:<person_id>`, survives a name change, and does NOT fork the entity.
- **Current `import_key` format = `omi:<surface>:<uid>:<sourceId>`** (`index.ts:345`), used in upserts at `:452,:472,:481,:560,:573`. → Phase 0/1/2 must **preserve this namespace** (the plan calls out `omi:conversation:self:<id>`); a second key format for the same object = duplication bug. Verify `omi:conversation:self:<id>` vs `omi:conversation:<id>` cannot both exist for one object.

---

## Per-phase status & the break-tests each must survive

| Phase | Status | When claimed done, I will try to break it with: |
|---|---|---|
| **0 — Audit current wiring** | NOT STARTED | Demand the one-pager: what fires, what polls, last-success timestamp, exact upsert behavior, entity external-id capability. Cross-check every claim against the actual code (don't trust the doc). |
| **1 — Pull reconcile + monitoring** | NOT STARTED | (a) Drop an item, confirm next pull recovers it. (b) Re-pull a window → **zero** duplicates (trace the `import_key` path). (c) Older revision must NOT overwrite newer (`updated_at`/revision rule). (d) **Two** independent health checks: a *killed* run AND an *auth-expired-but-still-running* job must BOTH alert — "zero for N days" alone = FAIL. |
| **2 — Push path** | NOT STARTED | (a) Duplicate webhook delivery → one record (exact-id idempotency runs **before** semantic dedup — prove the order in code). (b) A push overlapping a pull of the same object → one lineage, no dup. (c) Memories ingested **with source-conversation provenance**, not floating. |
| **3 — person_id → entity bridge** | NOT STARTED | (a) Keyed on `person_id`, NOT display name. (b) Renamed speaker does NOT fork the entity. (c) Smallest schema addition (e.g. `external_ids` jsonb), not `canonical_name` overload. |
| **4 — Raw SDK side-stream** | MUST NOT BE BUILT | Confirm it was **deferred**. If any Phase-4 code/SDK-sink wiring appears, that's a scope REVISE — flag immediately. Also watch for generic-connector over-engineering (plan says single-user, smallest reliable path). |

---

## The 8 non-negotiable invariants (from the plan's co-evolution outcomes)

All currently **n/a — not built**. Each cycle, for any claimed-done phase, confirm in the real code:
1. `import_key` + revision, **separate** `omi:conversation:<id>` / `omi:memory:<id>` namespaces; existing namespace preserved.
2. **Exact-id idempotency ordered BEFORE** content-fingerprint/semantic dedup; memories = derived facts (provenance to source conversation).
3. Monitoring = **run-heartbeat AND freshness/cursor check** (a single "zero for N days" alarm is a FAIL).
4. Source mutation: **updates propagate by revision; deletions do NOT** (blind re-pull must not resurrect deleted data).
5. Webhook security: dedicated secret, signature/timestamp + replay window + payload size limit, idempotent replays, **event-id-only logs** (never raw transcript).
6. `person_id` bridge keyed on the **stable id**, not display name; **smallest** schema addition.
7. Phase 4 deferred; if built, **ephemeral/staging-excluded** from normal consolidation.
8. Reconciliation backbone is **cursor/list-based** (complete); PR #2 semantic search is a retrieval bonus, not the dedup mechanism.

---

## What the worker should produce first (so the next cycle has something to verify)
1. `OMI-EXOCORTEX-INTEGRATION-PROGRESS.md` naming the build branch/worktree (esp. on the ExoCortex side).
2. Phase 0 baseline one-pager (then I verify it against the code).
3. First real code (Phase 1 pull-reconcile + the two health checks) — committed, so the diff is reviewable.
