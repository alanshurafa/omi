Document written cleanly. Here's what changed in this final pass:

**TL;DR:** All 11 `[CONTESTED]` and 1 `[CLARIFY]` notes resolved and removed. Every technical claim now verified against the actual codebase. The plan reads as one clean document with zero open notes.

**In plain English:** The critic found real problems — the plan said Neo4j when Omi uses Firestore, claimed dedup was missing when it already exists in some paths, and understated the memory model's richness. I verified each claim by reading the source files, then rewrote the affected sections to match reality instead of leaving contested notes in place.

**Key resolutions:**
- **Neo4j → Firestore:** KG stores nodes/edges as Firestore user subcollections, not Neo4j. All references corrected.
- **Encryption:** "AES-256" → "AES-256-GCM" (AESGCM with 32-byte key, 12-byte nonce).
- **Dedup scope narrowed:** `check_memory_duplicate` already exists in `routers/memories.py` and `mcp_sse.py`. Contribution 3 retargeted to the uncovered paths (non-SSE MCP REST, batch) and standardizing match behavior. Effort downgraded from M to S.
- **KG extraction already incremental:** `process_conversation.py` already calls `extract_knowledge_from_memory`. Contribution 4 reframed to cover only the missing create paths.
- **Timestamp semantics settled:** Deepgram result window (`start`, `start + duration`), not word-level min/max.
- **Honorable mention corrected:** Listed the 9+ actual `MemoryDB` fields instead of claiming "just content + category + visibility."
- **WebhookSink kept out of SDK core:** HTTP posting lives in the example only.
