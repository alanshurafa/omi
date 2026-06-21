# Omi → ExoCortex Integration — Build Progress

**Builder note:** the independent-reviewer session took over as builder for the Phase 0+1 unblock (per Alan, 2026-06-21 ~06:40 EDT), because the original build session never started overnight. The reviewer/builder separation is temporarily collapsed for Phase 0–1; hand back to the split for the risky Phases 2–3.

**Build location (code):** ExoCortex (`C:\Users\alan\Project\ExoCortex`, Supabase) + `ExoCortex-jobs` (scheduled pull). Planning/coordination docs: this Omi worktree.

---

## Phase status

| Phase | Status |
|---|---|
| 0 — Audit current wiring | ✅ **DONE** (baseline below) |
| 1 — Harden pull reconcile + monitoring | ⏸ **BLOCKED on one decision** (canonical path — see below) |
| 2 — Push path | NOT STARTED |
| 3 — person_id → entity bridge | NOT STARTED (needs `entities` migration — confirmed) |
| 4 — Raw SDK side-stream | NOT BUILT (correct — deferred) |

---

## Phase 0 baseline (the one-pager the plan asked for)

**What fires / what polls / last success:**
- **PULL = the live system of record.** `ExoCortex-jobs/scripts/omi/import-omi.mjs`, scheduled by Windows Task Scheduler task **`ExoCortex Omi Sync`** every **5 min** (`install-omi-sync-task.ps1`). Healthy: last run 2026-06-21 09:08, exit 0. Pulls **both** conversations and memories. Newest imported conversation `started_at` = `2026-06-20T03:47Z` (no newer Omi data since).
- **PUSH = `omi-connector` edge function** (`supabase/functions/omi-connector/index.ts`): accepts memory/conversation/daily-summary webhooks → `smart-ingest` → `upsert_thought`. **Liveness unconfirmed** (no evidence the Omi app is actually firing it; the pull is what's keeping ExoCortex current).

**Current idempotency/upsert behavior (the correctness core):**
- **Dedup is by `content_fingerprint`, NOT by Omi id.** `upsert_thought` keys on `sha256(normalized content)` (unique index `thoughts_content_fingerprint_idx`), then an `original_fingerprints` fallback, then insert. **It never reads `import_key`.**
- `import_key` (`omi:<surface>:<uid>:<sourceId>`) exists only inside `metadata`, used only for a **non-unique, race-prone job-level** lookup in `smart-ingest` (`:1063-1077`). **No unique index on `import_key` anywhere.**
- Pull path doesn't use `import_key` at all — conversation identity is a salted fingerprint (`wearable-atomize.mjs:46-50`); its cursor is an **ID-membership set in one local JSON file** (`data/import-state/omi-atomic-state.json`, 537 entries) — a SPOF, with **no persisted last-success timestamp**.
- **`omi:conversation:self:<id>` vs `omi:conversation:<id>` would NOT collide** (different strings) → they'd create two captures; only a content-hash coincidence would merge them.

**Revision/mutation:** Push path has **no `updated_at` guard** (older payload can overwrite newer on fingerprint collision). Pull **conversations never re-import** after first capture (pure id-skip); only pull *memories* compare `updated_at` (`import-omi.mjs:94`).

**Entities external-id (Phase 3):** `entities` has `aliases` (jsonb), `canonical_email`, unique `(entity_type, normalized_name)` — **no external-id field**. A stable Omi `person_id` needs either `metadata->>'omi_person_id'` (works now, unindexed) or a 1-line migration mirroring `canonical_email` (recommended). Live schema drift documented in `202606110014` — verify with `\d entities` before the migration.

**Monitoring:** effectively **none** for Omi. No freshness check, nobody reads `connector_sync_state.last_success_at`, the generic job-health watcher omits `ExoCortex Omi Sync`, and there is **no alert channel of any kind** in either repo. The pull swallows `429`/empty as `exit 0` (a broken auth looks identical to a quiet day).

*(Full evidence with file:line is in the audit; key files: `omi-connector/index.ts`, `smart-ingest/index.ts`, `import-omi.mjs`, migrations `202606110003`/`202603220001`/`202603290001`/`202604210004`.)*

---

## The decision Phase 1 hinges on (the plan needs a small revision)

The plan assumed **push-primary + idempotency-by-`import_key`**. Reality: **pull is the live path**, dedup is by `content_fingerprint`, `import_key` isn't a real key, and there are **two divergent implementations**. So "harden the pull, idempotent by `import_key`" isn't a tweak — it's a choice:

- **Option A (recommended): harden the live PULL path.** Add the two health checks (run-heartbeat + freshness/cursor), move the cursor off the single-file SPOF, add a revision-guard so edited conversations re-import, and introduce a real exact-id dedup key (`import_key` column + partial unique index) that runs *before* the fingerprint. Lowest risk — improve what's already running and is the system of record.
- **Option B: make PUSH primary** (as the plan's diagram says). Wire/confirm the Omi webhook, harden the connector's security gaps, demote pull to reconcile. More work + more risk; needs Omi-app config.
- **Either way:** reconcile the two-path divergence (duplicated code in `ExoCortex` vs `ExoCortex-jobs`; different `source_type` values; different dedup keys) or the same conversation via both paths makes divergent rows.

**Builder recommendation:** Option A. The plan's dormancy worry is already moot (pull runs every 5 min), so the real gaps are monitoring, cursor durability, revision handling, and a true exact-id key — all additive to the running pull. Start Phase 1 with the **monitoring** (purely additive, zero risk to ingestion), then the cursor/revision/key hardening. Defer push-primary (Option B) unless real-time latency is needed.

**Blocked because:** Phase 1 modifies Alan's *live, every-5-min* data pipeline (system of record). Need a nod on Option A vs B before touching it.
</content>
