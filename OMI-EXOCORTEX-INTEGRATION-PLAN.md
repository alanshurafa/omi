# Plan: Omi → ExoCortex Integration

**Author:** Alan Shurafa
**Status:** **v3 — co-evolved (Codex critique → Claude adjudication, 2026-06-21), grounded in the Phase 0 code audit.** v1 (2026-06-18) was co-evolved on assumptions; v2 corrected premises against the audit; **v3 fixes two correctness flaws Codex caught** (identity granularity, two-path convergence) and adopts a HYBRID direction. Earlier versions recoverable in git (`334656a97`, `58c4f0c1f`).

## Goal (unchanged)

A durable, near-real-time link that carries Omi's data into ExoCortex so ExoCortex stays the single brain everything queries (via its MCP), preserving what only Omi can produce.

## The decision this plan encodes (unchanged — validated by the audit)

- **Omi owns the audio layer** (`person_id`/voiceprint, diarization, timing, prosody) — irreproducible from text.
- **ExoCortex owns the knowledge layer** (atomization, multi-layer dedup, provenance, importance, temporal KG, consolidation, local-first sensitivity).
- **Feed Omi's *processed* output** (conversations + memories) into ExoCortex's enrichment. (Audit confirmed it already atomizes both.)

## What the audit + co-evolution established (read first)

Build target: ExoCortex (`C:\Users\alan\Project\ExoCortex` Supabase) + `ExoCortex-jobs` (the live pull). Evidence with file:line in `OMI-EXOCORTEX-INTEGRATION-PROGRESS.md`.

1. **Pull is the live path** (`import-omi.mjs`, ~5-min Task Scheduler, ID-set cursor in one local JSON, 537 conversations, both conversations + memories). Healthy by state-file mtime (exact last-run time unverifiable — scheduler query blocked).
2. **Dedup is by `content_fingerprint`, not Omi id.** `upsert_thought` keys on `sha256(normalized content)` → `original_fingerprints` fallback. **No `import_key` unique index.** `import_key` is metadata/job-level only.
3. **Two transports diverge in output** (pull: direct PostgREST, salted per-atom fingerprint, `source_type='omi'`; push: `omi-connector→smart-ingest→upsert_thought`, `source_type='omi_conversation'`). The `omi-connector`/`smart-ingest` *file copies* across the two repos are **identical today** (`git diff --no-index`) — a future-drift risk, not active divergence.
4. **No conversation revision guard** (pull skips by id after first import; only memories compare `updated_at`). Cursor is a single-file SPOF, no last-success timestamp; `--max 50` can miss bursts.
5. **No Omi monitoring; no alert channel anywhere. `entities` has no external-id field** (Phase 3 needs a migration; live drift documented in `202606110014`). Webhook accepts secret via query string.

## Direction — HYBRID over one shared identity ledger (co-evolution verdict)

Neither pure push (v1) nor pure pull (v2) is right:
- **Pull** is proven-live but a weak permanent backbone (5-min latency, single-machine SPOF, burst loss).
- **Push** removes latency + the local-scheduler SPOF but has setup/security risk and unconfirmed liveness.

**Decision: HYBRID.** Pull = reconciler/backfill (completeness). Push = real-time transport (latency). **Both write through ONE shared exact-id ledger + one canonical atomization contract** — which is also what makes the two paths converge instead of double-writing. The ledger is the load-bearing primitive; the transports are thin over it.

## Identity & idempotency model — a ledger at the right granularity (Codex P0 fix)

**Do NOT put a unique `import_key` on `brain_thoughts`** — one conversation becomes many atoms, so an object-level key per row would fail or collapse atoms. Instead:

- **Object ledger `imported_objects`** keyed by object: `omi:conversation:<id>` / `omi:memory:<id>` (resolve the `self:` form to ONE canonical shape). Columns: `import_key` (unique), `source_type`, `source_revision`/`updated_at`, `source_hash`, `first_seen_at`, `last_seen_at`, `tombstoned_at`, and a link to the produced atoms.
- **Atom-level keys** for the thoughts a single object expands into: `omi:conversation:<id>:atom:<n>` (stable across re-import), so re-processing updates atoms in place rather than duplicating.
- **Exact-id (ledger) match runs BEFORE content-fingerprint/semantic dedup.** Fingerprint stays as the cross-source consolidation layer, not the first line against retries.
- **One canonical atomization/write contract** both transports call (same atom boundaries, `source_type`, fingerprint inputs, metadata) — otherwise pull's salted fingerprint and push's normalized fingerprint never reconcile.
- **Revision:** replace a stored object only if `source_revision`/`source_hash` is newer (fixes "conversations never re-import"). **Deletions:** not propagated by default, but record tombstones + `last_seen_at`; never direct-insert around ExoCortex's delete guards, and never let local-state loss resurrect a user-deleted row.
- **Memories** = derived facts, ingested with provenance to their source conversation.

## Phases — UPDATED (sequencing fixed: de-risk the hard part early)

### Phase 0 — Audit ✅ DONE (baseline in PROGRESS.md)

### Phase 1 — Shared ledger + reconcile the live pull onto it (the core)
Re-sequenced so the highest-risk step (identity) is dry-run early, not deferred behind "safe" monitoring:
1. **Read-only inventory** of current Omi rows (counts by `source_type`, atoms per conversation, existing `metadata` keys).
2. **Define the canonical atomization/write contract + `imported_objects` ledger schema** (object + atom keys, revision/hash/tombstone fields).
3. **Backfill DRY-RUN** mapping existing thoughts → ledger; prove no collisions / no atom collapse on live data BEFORE any migration commits.
4. **Route the pull through the contract + ledger** (reconcile/backfill), exact-id before fingerprint.
5. **Durable cursor + revision/deletion handling** (off the single-file SPOF; persisted last-success; newer-only revision; tombstones).
6. **Monitoring/alerting** — run-heartbeat AND freshness/cursor check; stop swallowing `429`/empty as success; one real alert channel. (Not "zero risk" — a monitor that calls Omi can false-alert or burn rate budget; build it to fail loud, not silent.)
Acceptance: dropped item recovered next pull; stalled OR auth-expired run alerts; re-pull creates no duplicates and updates only on newer revision; an edited conversation re-imports; pull and push (when added) converge to one lineage via the ledger.

### Phase 2 — Push as a real-time transport over the SAME ledger (M)
Wire/confirm Omi fires into `omi-connector`, mapped through the **same** contract + ledger so exact-id idempotency absorbs retries and push/pull collisions. Harden connector security (constant-time secret, no secret-in-query, signature/replay/size, event-id-only logs). Until the shared contract exists, **disable whichever path overlaps** to avoid double-writes.

### Phase 3 — `person_id` → entity bridge (M) [highest-value, but verify the premise first]
**First confirm a stable `person_id` actually exists in the Omi payload** — code currently shows `speaker_id`/`speaker_name` and the connector drops them; `person_id` is not proven. Step 1: capture the raw speaker identifiers into thought `metadata` and inspect real payloads. Only then add the smallest indexed `entities` external-id (`omi_person_id TEXT` + partial unique index, mirroring `canonical_email`; verify live schema first). Keyed on the stable id, never the display name.
Acceptance: a known speaker links to the existing entity by stable id; a name change doesn't fork it.

### Phase 4 — Raw SDK side-stream (deferred, optional; unchanged)
Ephemeral/staging-excluded; only if a concrete can't-wait workflow exists; not before Phases 1–3 prove out.

## Two-path reconciliation (resolved by the ledger, not by "sharing a key")
Pull's and push's fingerprints/atoms/source_types are not comparable, so semantic matching is not an idempotency contract. The fix is structural: **one canonical atomization/write contract + the shared ledger**; both transports call it. Also collapse the duplicated `omi-connector`/`smart-ingest` trees to one authoritative copy (identical now — pick one before they drift).

## The 8 target invariants — current status
1. Exact-id ledger (object+atom) + revision, separate namespaces — **UNMET (Phase 1 core).**
2. Exact-id before semantic; memories as derived facts — **UNMET (Phase 1).**
3. Run-heartbeat + freshness/cursor monitoring — **UNMET (Phase 1).**
4. Updates by revision; deletions tombstoned not propagated — **PARTIAL (memories only).**
5. Webhook security — **UNMET (Phase 2).**
6. `person_id` bridge on stable id — **UNMET + premise unverified (Phase 3).**
7. Phase 4 deferred/ephemeral — **HELD (correct).**
8. Cursor/list reconciliation backbone — **PARTIAL (ID-set cursor exists but single-file SPOF; no freshness).**

## Risks (updated)
- **Identity migration/backfill on the live `brain_thoughts`** is the highest-risk step → dry-run first, never big-bang.
- **Two transports** must converge through the contract+ledger or they double-write.
- **person_id may not exist** in the payload (could be `speaker_id`) — verify before Phase 3.
- **entities live schema drift** (`202606110014`) — `\d entities` before migrating.
- **Cursor SPOF + burst window**; single-machine scheduler.
- Keep it single-user-minimal: the ledger is the one necessary new primitive; avoid generic-connector abstractions beyond it.

## Open decision for Alan
Lock the direction from this stress-tested plan: **HYBRID over a shared ledger** [co-evolution verdict; recommended], or override to pull-only / push-only. Phase 1 starts with read-only inventory + a ledger dry-run (no live mutation) — that first step is safe to run as soon as you pick HYBRID.
