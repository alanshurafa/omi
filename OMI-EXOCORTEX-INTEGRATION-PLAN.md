# Plan: Omi → ExoCortex Integration

**Author:** Alan Shurafa
**Status:** Review candidate (co-evolved: Codex critique → Claude adjudication)
**Date:** 2026-06-18

## Goal

A durable, near-real-time link that carries Omi's data into ExoCortex so ExoCortex stays the
single brain everything queries (via its MCP). The link must preserve what only Omi can
produce and let ExoCortex do the knowledge-layer work it does better.

## The decision this plan encodes

A code-level comparison of both enrichment pipelines settled the core question:

- **Omi owns the audio layer.** Voiceprint speaker identity (`person_id`), diarization,
  per-segment timing, and prosody/emotion come from raw audio and cannot be recomputed later
  from text. Omi's memory-extraction prompt is also genuinely strong.
- **ExoCortex owns the knowledge layer.** Atomization, multi-layer dedup, provenance/audit,
  importance scoring, a temporal knowledge graph, consolidation, and local-first sensitivity
  tiers are all stronger there, and it is multi-source by design.
- **ExoCortex is text-only.** It never sees audio, so feeding it *raw* transcripts throws away
  Omi's irreproducible audio layer and still owes the knowledge work.

Therefore: **feed Omi's *processed* output (conversations + memories) into ExoCortex's
enrichment; do not bypass Omi's processing for the main feed.** Omi's ears into ExoCortex's
brain.

## Direction: push-primary, pull-reconcile

- **Push** (Omi fires on new data → ExoCortex ingests) gives real-time and does not rot
  silently. The Limitless pull pipeline sat dormant ~9 months unnoticed; an unwatched cron is
  the known failure mode.
- **Pull** (ExoCortex periodically asks Omi for a trailing window) is the safety net for
  anything the webhook dropped, not the primary path.
- Convergence depends on a correct identity model (below), not on semantic dedup.

## Identity & idempotency model (the correctness core)

This is first-class, because push + pull + webhook retries + source edits all collide here.

- **Object identity:** a stable `import_key` per Omi object, in **separate namespaces** for
  the two object types — `omi:conversation:<id>` and `omi:memory:<id>`. Preserve whatever
  namespace already exists in ExoCortex (Phase 0 confirms it; e.g. `omi:conversation:self:<id>`)
  — do not introduce a second key format for the same object.
- **Replacement semantics:** carry Omi's `updated_at`/revision alongside the key. An incoming
  object replaces the stored one only if its revision is newer (no stale write clobbers newer
  data).
- **Ordering of dedup:** exact/deterministic idempotency by Omi object ID happens **first**,
  before content fingerprint or semantic reconcile. Semantic dedup is reserved for *cross-source*
  consolidation (e.g. an Omi memory that restates something captured elsewhere) — it is never
  the first line of defense against retries or push/pull collisions.
- **Omi memories are derived facts.** Ingest them with provenance pointing back to their source
  conversation (`omi:conversation:<id>`) when Omi provides it, so a fact is traceable to the
  utterance, not floating.
- **Source mutation:** updates propagate via the revision rule above. **Deletions are not
  propagated by default** — an explicit, documented choice for v1 (blind re-pull must never
  resurrect data Omi deleted). A later optional pass may mark previously-seen objects missing
  from the trailing window as stale after a grace period.

## Current state — verify before building (Phase 0)

Partly built already; confirm what is actually live, because silent rot is the main risk.

- `supabase/functions/omi-connector/index.ts` already **receives Omi webhooks**, reads
  `transcript_segments` (`speaker_name`/`speaker`/`speakerId`), flattens them to `"Speaker: text"`,
  and forwards to text ingest. **Verify it is wired to a live Omi integration**, not dormant.
- An MCP/REST import path also ingests Omi conversations (thoughts carry
  `import_key: omi:conversation:self:<id>`, `capture_mode: backfill|smart_ingest`). **Verify it
  still runs**, and on what trailing window.
- Confirm whether Omi **memories** are ingested today, or only the conversation transcript.
- Confirm the exact uniqueness/upsert behavior for `import_key` today, including whether
  `omi:conversation:self:<id>` vs `omi:conversation:<id>` would collide or duplicate.
- Confirm whether ExoCortex's `entities` schema has any external-identity field (it has
  `aliases`, `canonical_email`, unique `(entity_type, normalized_name)` — but no obvious
  external id), since Phase 3 depends on it.

Deliverable: a one-page "what fires, what polls, last-success timestamp, and current
idempotency/upsert behavior" so the real baseline is known.

## Target architecture

```
Omi wearable/app
   │  (audio → Omi cloud enrichment: diarization, person_id, summary, memories)
   ▼
Omi processed output ── push (signed webhook) ──► ExoCortex omi-connector ──┐
   │                                                                        ├─► ExoCortex ingest
   └── pull (scheduled, trailing window, reconcile) ────────────────────────┘   (exact-id idempotency →
                                                                                  atomize, dedup, score, KG, sensitivity)
                                                              one retrieval surface: ExoCortex MCP
```

Raw SDK capture (the "hearing primitive") is a deferred, separate side-stream (Phase 4).

## Phases

### Phase 0 — Audit current wiring (S, low risk)
Produce the baseline above. No code. Output: which paths are live, last success, exact
idempotency/upsert behavior, entity external-id capability, and the gap list.

### Phase 1 — Harden pull reconciliation + monitoring (S–M, low risk)
A dependable trailing-window pull of Omi conversations + memories, idempotent by `import_key`
with the revision rule. Two independent health checks (a single "zero for N days" alarm is
wrong — it false-alerts on quiet days and false-succeeds when auth has expired but the job
still runs):
1. **Run heartbeat** — every scheduled run records success/failure.
2. **Freshness check** — compare against the newest source-item timestamp or Omi cursor; alert
   if Omi has newer data than ExoCortex has ingested.
Acceptance: a deliberately dropped item is recovered next pull; a stalled or auth-expired run
alerts; re-pulling a window creates no duplicates and updates an object only if Omi's revision
is newer.

### Phase 2 — Confirm/upgrade the push path (M, medium risk)
Ensure the Omi integration fires on `memory_creation` and conversation/transcript triggers
into `omi-connector` in real time. Map each object to ingest using the namespaced `import_key`
+ revision. Ingest **both** the transcript (for atomization/recall) and Omi's memories
(high-precision facts, with source-conversation provenance). Exact-id idempotency absorbs
webhook retries and push/pull collisions before any semantic step runs.
Acceptance: a new Omi conversation appears in ExoCortex within seconds; re-delivery and a
later pull of the same object converge to one lineage with no duplicate.

### Phase 3 — `person_id` → entity bridge (M, medium risk) [highest-value new work]
The connector currently drops Omi's `person_id`, so ExoCortex re-guesses identity from the
name string. Pass Omi's speaker identity through to ExoCortex's **entity** layer, keyed on the
**stable `person_id`** (`omi:person:<person_id>`), never the display name (names aren't stable
identifiers). If Phase 0 shows no external-identity field on `entities`, add the smallest one
(e.g. an `external_ids` jsonb, or a typed alias) rather than overloading `canonical_name`.
Acceptance: a conversation with a known enrolled speaker links its thoughts/edges to the
existing entity by `person_id`, not a new name-only node; a name change in Omi does not fork
the entity.

### Phase 4 — Raw SDK "live hearing" side-stream (deferred, optional)
Only build if a concrete live-context workflow that cannot wait for Omi's processed output
actually exists. If so, use the PR #1 SDK sink to push raw transcripts to a **staging path
excluded from normal consolidation by default** (ephemeral; not persisted into the main
knowledge store unless a query explicitly promotes it). This stream accepts the loss of Omi's
audio-layer enrichment. Do not start it until Phases 1–3 are proven in real use.

## Security & privacy

- Push adds a public surface, so harden `omi-connector`: a dedicated Omi webhook secret;
  signature + timestamp verification if Omi supports it; a replay window; a payload size
  limit; idempotent processing so replays cannot duplicate; and logging of event IDs only,
  never raw transcript text.
- ExoCortex's local-first sensitivity tiering still applies: restricted PII is classified
  before any cloud enrichment and blocked if `restricted`.
- This design routes data through Omi's cloud (accepted tradeoff for the enrichment). The
  deferred raw side-stream is the only path that avoids it.

## Risks & open questions

- **Does Omi's integration payload include `person_id`/speaker identity?** Phase 3 needs it;
  if absent, fall back to enrolled speaker names and match on those (weaker).
- **Is the current pull live or dormant?** Phase 0 answers it; assume nothing.
- **Source mutation/deletion:** Phases 1–2 define update behavior; deletion is explicitly not
  propagated in v1.
- **Double-enrichment volume:** transcript + memories doubles input; exact-id idempotency
  first, then measure thought volume after Phase 2.
- **Single-user scope:** prefer the smallest reliable push/pull path over generic connector
  abstractions unless Phase 0 shows multiple sources already share the machinery.

## How the in-flight PRs connect

- **PR #2 (MCP memory search)** can enrich retrieval, but the reconciliation backbone in
  Phase 1 should be **list/cursor-based for completeness** — semantic search is a bonus, not
  the mechanism that guarantees nothing is missed.
- **PR #1 (SDK transcript sink)** is only relevant if Phase 4 survives the deferral test.

## What the co-evolution changed (Codex → Claude)

Codex raised 6 contested points and 2 clarifications; all were accepted or resolved:
1. Identity model upgraded: `import_key` + revision + separate conversation/memory namespaces.
2. Exact-id idempotency ordered *before* semantic dedup; memories treated as derived facts.
3. Monitoring split into run-heartbeat + freshness/cursor check (killed the "zero for N days" trap).
4. Source mutation/deletion semantics defined (updates propagate; deletions don't, by default).
5. Webhook security hardened (dedicated secret, signature/replay/size limits, event-id-only logs).
6. `person_id` bridge keyed on the stable id, not display name; smallest schema addition.
7. Phase 4 (raw side-stream) deferred and made ephemeral/staging-excluded — anti over-engineering.
8. Reconciliation backbone clarified as cursor/list-based; PR #2 is a retrieval bonus.
