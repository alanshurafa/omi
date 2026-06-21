# Plan: Upstreaming ExoCortex Patterns into Omi

**Target repo:** BasedHardware/Omi (this repo). Not OB1.
**Author:** Alan Shurafa
**Status:** Review candidate
**Date:** 2026-06-17

## Why these, and why now

I run three capture systems (Omi, Limitless, ExoCortex) but treat Omi as a source
that feeds one retrieval brain - ExoCortex - which everything queries through its MCP.
So the contributions worth making are not a wishlist of features. They are the things
that make Omi a cleaner, richer capture source, plus the retrieval plumbing I have
already proven in production (~85K thoughts).

Omi is more built-out than a first glance suggests. It already has a Firestore-backed
knowledge graph (nodes and edges stored as user subcollections), Pinecone semantic search,
optional per-user AES-256-GCM data protection, and an agentic RAG layer. That maturity is
the point: it narrows the list to specific gaps where ExoCortex has a working reference
implementation, which is what a maintainer wants to see in a PR.

Two of these (1 and 2) also serve my own architecture directly: a clean export path out
of Omi, and richer retrieval through the MCP I have standardized on. They are not charity
PRs.

## Scope and non-goals

In scope: three candidate PR-grade contributions (1, 2, 3), plus two design-only topics
(4, 5) that should not be coded until maintainers explicitly accept the direction.

Out of scope (Omi already has it, or I do not have a mergeable reference):
- Pinecone semantic search over conversations - present.
- Memory vector plumbing in the backend and hosted MCP transport - present; local MCP
  package parity is the gap.
- Per-user enhanced encryption - present for protected data paths.
- Agentic RAG - present.
- Proactive surfacing / daily briefings - this is ExoCortex's own top gap, so there is
  nothing to donate.

## Contributions, ranked

### 1. SDK: structured transcript callback + STT config + backend sink example
**Leverage: highest. Effort: S-M. Risk: low-medium.**

Problem. `sdks/python/omi/transcribe.py` hands the integrator a bare
`on_transcript: Callable[[str], None]` - text only, no timestamps, speaker, or
final/interim flag. The Deepgram URL hardcodes `nova` / `en-US` / `linear16` / `16000`.
The only example (`sdks/python/examples/main.py`) prints to console. Every integrator
hand-rolls the push-to-backend glue. I built exactly that for Supabase.

ExoCortex reference. The `handle_transcript -> own backend` pattern, in production.

Proposed change.
- A `Transcript` dataclass: `text, is_final, start, end, speaker, confidence, language, raw`.
- Callback accepts the dataclass; support sync and async callbacks.
- A minimal `TranscriptSink` protocol with `async def write(self, t: Transcript)`, plus
  `ConsoleSink` as the default to preserve current behavior.
- A new `examples/backend_sink.py`: POST transcripts to the integrator's own HTTP endpoint
  (the Supabase pattern, genericized). HTTP posting lives in the example only, not in the
  SDK core.
- `TranscribeConfig(model, language, encoding, sample_rate)` so STT params are arguments,
  not a hardcoded URL.

Timestamp semantics: `start` and `end` are the Deepgram result window (`result.start`,
`result.start + result.duration`) when available, `None` otherwise. Word-level timestamps
stay in `raw` for callers that need them.

PR boundary. Backward compatible. Bare-string callback keeps working via a shim, or bump a
minor version. Split if needed: (1a) structured callback + config, (1b) sink protocol + example.

Acceptance criteria.
- Existing console example behaves identically.
- New backend example runs end-to-end against a local echo server.
- Callback receives a structured `Transcript`.
- Model/language change without touching the URL string.

### 2. MCP: local package parity for memory search, then KG read access
**Leverage: high. Effort: S-M for search parity, M for KG. Risk: low-medium.**

Problem. The local stdio MCP package (`mcp/src/mcp_server_omi/server.py`) ships 7 tools
and lacks `search_memories`. The hosted streamable HTTP MCP (`backend/routers/mcp_sse.py`)
already has `search_memories` backed by `vector_db.find_similar_memories`. The non-SSE
backend MCP REST router (`backend/routers/mcp.py`) also lacks memory search and KG
access. The KG read endpoint exists at `GET /v1/knowledge-graph` but is not exposed through
any MCP surface.

ExoCortex reference. The ExoCortex MCP (`search_thoughts`, `graph_search`, `graph_traverse`,
`graph_shortest_path`, `entity_detail`, `trace_provenance`) is the proven tool surface and
the protocol I query everything through.

Proposed change.
- Add `search_memories` to the local MCP package, matching hosted MCP semantics and
  locked-memory handling.
- Add the minimal backend MCP REST endpoint needed by the local package, likely
  `/v1/mcp/memories/search`, wired to `vector_db.find_similar_memories`.
- Add `get_knowledge_graph` as a read-only MCP tool only after search parity lands.
- Defer entity traversal and shortest path until maintainers accept the read snapshot.
  Traversal needs pagination, depth limits, and node identity semantics against the
  Firestore edge shape - too much for a first MCP PR.

PR boundary. Split: (2a) local MCP `search_memories` parity, (2b) KG read snapshot. Read-only;
no write paths.

Acceptance criteria.
- An MCP client using the local package can semantically search memories.
- Hosted MCP and local MCP return compatible `search_memories` shapes.
- If 2b lands, an MCP client can fetch the KG snapshot without adding traversal semantics.

### 3. Near-duplicate suppression for manually created memories
**Leverage: medium. Effort: S. Risk: medium.**

Problem. Exact duplicate content already maps to the same Firestore document ID via
`document_id_from_seed(memory.content)` (SHA-256 -> UUID), so identical creates are
effectively upserts. Semantic near-duplicate checking also exists: `check_memory_duplicate`
(a thin wrapper around `find_similar_memories`) is already called in the REST memories
router and hosted MCP. However, coverage is inconsistent: the non-SSE MCP REST router
(`backend/routers/mcp.py`) and batch creation do not call the duplicate check, and where
it is called, behavior on a positive match varies.

ExoCortex reference. Content-fingerprint + `import_key` dedup is a core mechanism, in
production at scale.

Proposed change.
- Wire `check_memory_duplicate` into the remaining uncovered create paths (non-SSE MCP,
  batch).
- Standardize behavior on a positive near-duplicate match: return the existing memory
  instead of inserting.
- Do not backfill existing memories in this PR.
- Do not add a new `fingerprint` schema field: the existing content-derived document ID
  and vector similarity check are sufficient for the first PR. Add a normalized fingerprint
  only if tests prove the existing mechanisms inadequate.

PR boundary. Dedup-on-create only for uncovered paths. No consolidation, no destructive
merge, no backfill.

Acceptance criteria.
- A near-duplicate manual or MCP memory above the configured threshold returns the existing
  record instead of inserting.
- Exact duplicate creation remains idempotent and does not silently reset existing metadata
  (verify that the content-derived ID upsert preserves `reviewed`, `scoring`, `kg_extracted`).
- Existing memory tests pass; focused dedup tests are added to `backend/test.sh`.

### 4. Fill knowledge-graph extraction gaps + query API
**Leverage: medium. Effort: M-L. Risk: medium-high.**

Problem. Conversation-extracted memories already trigger incremental KG extraction in
`process_conversation.py` via `extract_knowledge_from_memory`, with a `kg_extracted` flag
to track state. But manual `/v3/memories`, batch memory creation, and MCP memory creation
do not call this extractor. `POST /v1/knowledge-graph/rebuild` is a destructive
delete-and-rebuild that re-extracts from up to 500 non-locked memories. The only read is
`GET /v1/knowledge-graph`, which returns the entire graph - no per-entity query or
traversal.

ExoCortex reference. Incremental entity/edge upserts on capture, with provenance, plus
traversal and shortest-path queries.

Proposed change.
- Trigger best-effort KG extraction after manual, batch, and MCP memory creation, using the
  existing `extract_knowledge_from_memory` extractor and existing executor patterns.
- Ensure no request blocks on LLM work (use `postprocess_executor` or equivalent background
  dispatch).
- Add query endpoints separately: entity neighbors and N-hop traversal.

PR boundary. Extraction coverage and traversal are separable PRs. Guard LLM cost on the
write path by using background/postprocess execution and respecting existing executor pools.

Acceptance criteria.
- A manually created memory can update the graph without a full rebuild.
- MCP-created memories follow the same KG extraction policy as app-created memories.
- A traversal endpoint returns an N-hop neighborhood for an entity.

### 5. Sleep-time consolidation / synthesis pass
**Leverage: medium. Effort: L. Risk: high.**

Problem. Omi has `daily_summaries` and memory conflict handling during conversation
extraction, but no periodic cross-memory consolidation pass: no auditable `supersedes`
relationship, no scheduled merge of near-duplicate or evolving facts, no synthesis memory.

ExoCortex reference. A consolidation engine that merges/supersedes related memories and
writes syntheses (`capture_synthesis`).

Proposed change.
- Open a design issue before writing code.
- Start with a dry-run job/report that finds related or near-duplicate memories and proposes
  `supersedes` links.
- Only after maintainer approval, add a flagged periodic job that writes auditable supersession
  metadata. No hard deletes.

PR boundary. Design issue first. Any implementation must be behind a feature flag,
non-destructive, auditable, and reversible. A cold PR extending cron consolidation is too
risky for an OSS maintainer to review without prior alignment: it changes user trust
semantics and can silently rewrite a second brain.

Acceptance criteria.
- The dry run identifies candidate duplicates without writing.
- If later implemented, no memory is hard-deleted; supersession is auditable and reversible.

## Honorable mention

Provenance + importance/quality/sensitivity tiers on memories. The existing `MemoryDB`
model already carries more than basic content: `tags`, `headline`, `reviewed`/`user_review`,
`is_locked`, `data_protection_level`, `scoring`, `kg_extracted`, and `app_id`. What is
missing is source provenance metadata (which system or integration created this memory, via
what import) that would support dedup, audit, and future consolidation. This fits Omi's
"a 2nd brain you trust" tagline but is a schema addition that should follow the simpler
contributions.

## Sequencing and process

1. Land 1 first - small SDK surface, no backend coupling.
2. Land 2a next - local MCP `search_memories` parity with hosted MCP.
3. Land the narrowed 3 only after confirming exact duplicate behavior and API semantics
   with a spike that exercises `document_id_from_seed` upsert and `check_memory_duplicate`
   across all create paths.
4. Open design issues for 4 and 5 before writing code.
5. One concern per PR. Keep each diff small enough to review in one sitting.

## Risks and open questions

- **Target confirmation.** Treat BasedHardware/Omi as fixed. OB1 is out of scope for this plan.
- **Maintainer alignment.** Omi has its own roadmap. The big items (4, 5) need a signal before
  investment.
- **MCP surface duplication.** Omi has a local stdio MCP package and a hosted streamable HTTP MCP
  implementation. Any new tool needs an explicit parity decision.
- **Backend MCP API coupling.** Contribution 2 requires backend `/v1/mcp/` changes, not just
  the MCP server package.
- **Existing dedup behavior.** `check_memory_duplicate` is already called in some create paths
  but not all, and behavior on match is inconsistent. A spike must map coverage before proposing
  changes.
- **Write-path cost.** Contributions 4 and 5 add LLM work near user writes; they must respect
  Omi's async executor rules (`postprocess_executor`, `llm_executor`) and not block the event
  loop.

## HUMAN SUMMARY

- composer, pass 2: Resolved all [CONTESTED] and [CLARIFY] notes by integrating verified codebase facts (Firestore KG not Neo4j, AES-256-GCM, existing check_memory_duplicate coverage, incremental KG extraction in process_conversation), narrowed contribution 3 to uncovered create paths only, settled timestamp semantics, and corrected the honorable mention to acknowledge the full MemoryDB field set.
