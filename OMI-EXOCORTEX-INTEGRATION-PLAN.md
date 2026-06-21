# Plan: Omi → ExoCortex Integration

**Author:** Alan Shurafa
**Status:** **Revised against the Phase 0 audit (2026-06-21).** Original: co-evolved (Codex critique → Claude adjudication), 2026-06-18.
**What this revision does:** the Phase 0 audit found that several of the original plan's premises did not match the running code (the pull path is live and primary, dedup is by `content_fingerprint` not `import_key`, and there are two divergent ingest paths). This version corrects those premises, marks Phase 0 done, and reframes the remaining phases. The one open decision — pull-primary vs push-primary — is laid out at the end. Original is recoverable in git (commit `334656a97`).

## Goal (unchanged)

A durable, near-real-time link that carries Omi's data into ExoCortex so ExoCortex stays the single brain everything queries (via its MCP). The link must preserve what only Omi can produce and let ExoCortex do the knowledge-layer work it does better.

## The decision this plan encodes (unchanged — validated by the audit)

- **Omi owns the audio layer.** Voiceprint speaker identity (`person_id`), diarization, per-segment timing, prosody/emotion come from raw audio and cannot be recomputed from text. Omi's memory-extraction prompt is genuinely strong.
- **ExoCortex owns the knowledge layer.** Atomization, multi-layer dedup, provenance/audit, importance scoring, a temporal knowledge graph, consolidation, local-first sensitivity tiers — all stronger there, and multi-source by design.
- **ExoCortex is text-only.** Feeding it raw transcripts throws away Omi's irreproducible audio layer and still owes the knowledge work.

Therefore: **feed Omi's *processed* output (conversations + memories) into ExoCortex's enrichment.** Omi's ears into ExoCortex's brain. (The audit confirmed ExoCortex already atomizes Omi conversations + memories this way.)

## Phase 0 audit corrections (NEW — read this before the rest)

The build is in ExoCortex (`C:\Users\alan\Project\ExoCortex` Supabase + `ExoCortex-jobs` scheduled pull). Evidence with file:line is in `OMI-EXOCORTEX-INTEGRATION-PROGRESS.md`. Six corrections:

1. **The PULL is live and is the system of record — not a dormant safety net.** `ExoCortex-jobs/scripts/omi/import-omi.mjs` runs every 5 min (Task Scheduler `ExoCortex Omi Sync`), healthy (last run 2026-06-21 09:08, 537 conversations, both conversations + memories). → The original "push-primary because an unwatched cron rots" rationale is **moot for Omi**.
2. **Dedup is by `content_fingerprint`, not by Omi id.** `upsert_thought` keys on `sha256(normalized content)`; **there is no `import_key` unique index anywhere.** `import_key` lives only in `metadata`, used for a non-unique, race-prone job-level lookup. → The original "idempotency by `import_key`" backbone **does not exist; it must be built.**
3. **Two divergent ingest paths.** Pull writes directly to `brain_thoughts` via PostgREST with a salted fingerprint; push goes `omi-connector → smart-ingest → upsert_thought`. Different `source_type` values, duplicated code across `ExoCortex` and `ExoCortex-jobs`. → Same conversation via both = divergent rows. **Reconciliation is now a first-class task.**
4. **No revision guard.** Push can let an older payload overwrite a newer record (fingerprint-collision case); pull **conversations never re-import** after first capture (only pull *memories* compare `updated_at`). → Edited conversations are currently lost.
5. **Cursor is a single-file SPOF.** Pull's cursor is an ID-membership set in one local JSON (`data/import-state/omi-atomic-state.json`, 537 entries), **no persisted last-success timestamp**; the count-based `--max 50` window can silently miss a burst >50 between runs.
6. **Monitoring is effectively absent and `entities` has no external-id field.** No freshness check, nobody reads `connector_sync_state.last_success_at`, the job-health watcher omits the Omi task, and **no alert channel exists in either repo**; the pull swallows `429`/empty as `exit 0`. `entities` has `aliases`/`canonical_email`/unique `(entity_type, normalized_name)` but no external-id (Phase 3 needs a migration; live schema drift documented in `202606110014`).

## Direction — CORRECTED: pull-primary today; push is an optional enhancement

- **Recommended:** treat the **live pull as the canonical backbone** and harden it. Layer push on later as a real-time *accelerator* over the **same** idempotency model — not as a replacement. The original push-primary argument rested on dormancy, which the audit disproved.
- **Alternative (only if sub-minute latency is a real requirement):** commit to push-primary — wire/confirm the Omi webhook, harden the connector, demote pull to reconcile. More work, more risk, needs Omi-app config.
- Convergence depends on a correct identity model, which **does not exist yet** and is the core of Phase 1.

## Identity & idempotency model — target (must be built) vs current

**Current (audit):** `content_fingerprint` dedup only; no exact-id key; ID-set cursor in a local file; `self:` namespace ambiguity unresolved; no revision guard on push; pull conversations never re-import.

**Target (the goal):**
- **Object identity:** a stable `import_key` per Omi object, **separate namespaces** `omi:conversation:<id>` / `omi:memory:<id>`. Preserve the existing `omi:conversation:self:<id>` shape — pick ONE canonical form (resolve the `self:` ambiguity) so two key formats can't double-write.
- **Exact-id idempotency FIRST**, before content-fingerprint/semantic dedup. Add `import_key` as a real column + partial unique index; have the upsert match it before fingerprint.
- **Replacement by revision:** carry Omi's `updated_at`/revision; an incoming object replaces the stored one only if its revision is newer (no stale write clobbers newer data) — fix the "conversations never re-import" gap.
- **Memories are derived facts:** ingest with provenance to their source conversation (`omi:conversation:<id>`).
- **Deletions not propagated by default** (v1) — blind re-pull must never resurrect deleted data. Optional later: mark long-missing objects stale after a grace period.
- **Semantic dedup is for cross-source consolidation only**, never the first line against retries/collisions.

## Phases — UPDATED

### Phase 0 — Audit current wiring ✅ DONE
Baseline produced (see `OMI-EXOCORTEX-INTEGRATION-PROGRESS.md` + the six corrections above).

### Phase 1 — Harden the live pull + monitoring + real idempotency (S–M)
On the canonical pull path: (a) **two health checks** — run-heartbeat (every run records success/failure) AND freshness/cursor (alert if Omi has newer data than ExoCortex ingested); a single "zero for N days" alarm is wrong. (b) **Durable cursor** off the single-file SPOF, with a persisted last-success timestamp. (c) **Revision-guard** so edited conversations re-import (newer-only). (d) **Exact-id key** (`import_key` column + partial unique index) consulted before the fingerprint. (e) **Reconcile the two-path divergence** (one canonical write path / shared dedup key).
Acceptance: a dropped item is recovered next pull; a stalled OR auth-expired run alerts; re-pulling creates no duplicates and updates an object only if Omi's revision is newer; an edited conversation re-imports; the same object via pull and push converges to one lineage.

### Phase 2 — Push as real-time enhancement (M, medium risk)
Wire/confirm Omi fires `memory_creation` + conversation triggers into `omi-connector`, mapped through the **same** `import_key` + revision model so exact-id idempotency absorbs webhook retries and push/pull collisions. Harden the connector security gaps the audit found (constant-time secret, signature/replay/size limits, event-id-only logs). Push accelerates; it does not fork the model.
Acceptance: a new Omi conversation appears within seconds; re-delivery + a later pull converge to one lineage, no duplicate.

### Phase 3 — `person_id` → entity bridge (M) [highest-value new work]
The connector drops `person_id` (flattens to `"Speaker: text"`). Pass Omi's speaker identity to ExoCortex's **entity** layer keyed on the **stable `person_id`** (`omi:person:<person_id>`), never the display name. Add the smallest schema field (`omi_person_id TEXT` + partial unique index, mirroring `canonical_email`) — confirmed `entities` has no external-id today; verify live schema (`\d entities`) first due to documented drift.
Acceptance: a known enrolled speaker links thoughts/edges to the existing entity by `person_id`; a name change in Omi does not fork the entity.

### Phase 4 — Raw SDK "live hearing" side-stream (deferred, optional)
Unchanged: only build if a concrete live-context workflow that can't wait for Omi's processed output exists. Ephemeral, staging-excluded from normal consolidation. Do not start until Phases 1–3 are proven in real use.

## Two-path reconciliation (NEW — current top risk)
Pick the canonical write path and make the other defer to it (or share one dedup key + `source_type`). Resolve the duplicated `omi-connector`/`supabase`/`scripts` trees across `ExoCortex` and `ExoCortex-jobs` (confirm which is authoritative) before changing ingest, or fixes land in the wrong copy.

## Security & privacy (unchanged intent; gaps confirmed)
Harden `omi-connector` before exposing it publicly: dedicated webhook secret (constant-time compare, not via query string), signature + timestamp + replay window, payload size limit checked **before** full parse, idempotent processing, event-id-only logs. Local-first sensitivity tiering still applies (restricted PII blocked before cloud enrichment). The processed feed routes through Omi's cloud (accepted tradeoff); the deferred raw side-stream is the only path that avoids it.

## The 8 target invariants (goals — current status from the audit)
1. `import_key` + revision, separate conversation/memory namespaces — **UNMET (build in Phase 1).**
2. Exact-id idempotency before semantic dedup; memories as derived facts — **UNMET (Phase 1).**
3. Monitoring = run-heartbeat + freshness/cursor — **UNMET (Phase 1).**
4. Updates propagate by revision; deletions don't — **PARTIAL (memories only; conversations never re-import).**
5. Webhook security (secret/signature/replay/size/event-id-only logs) — **UNMET (Phase 2).**
6. `person_id` bridge keyed on stable id; smallest schema addition — **UNMET (Phase 3; needs migration).**
7. Phase 4 deferred + ephemeral/staging-excluded — **HELD (not built — correct).**
8. Reconciliation backbone cursor/list-based; semantic search a bonus — **PARTIAL (list/ID-set cursor exists but is a single-file SPOF; no freshness check).**

## Risks & open questions (updated)
- **Two-path divergence** is now the top risk (above).
- **Does Omi's payload include `person_id`?** Phase 3 needs it; the connector currently has the speaker name but drops the id — confirm the id is in the webhook/pull payload, else fall back to enrolled names (weaker).
- **`entities` live schema drift** (`202606110014`) — verify before the Phase 3 migration.
- **Cursor durability + burst window** — single-file SPOF, `--max 50` can miss bursts.
- **Single-user scope** — prefer the smallest reliable pull/push path over generic connector abstractions.

## Open decision for Alan
Pick the Phase 1 build direction now that the plan matches reality: **(A) harden the live pull as canonical** [recommended], or **(B) commit to push-primary**. Phase 1 edits the live ExoCortex pipeline, so this needs an explicit go before code.
