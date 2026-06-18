"""Tests for the MCP REST memory search endpoint (routers.mcp.search_memories).

Verifies parity with the hosted MCP (mcp_sse) semantics:
- rank by vector similarity and sort results by relevance score,
- map each match's score onto its memory,
- truncate locked memory content,
- return [] (without a DB fetch) when there are no matches.

Calls the real router function directly; heavy deps are stubbed before import,
the same pattern used by test_lock_bypass_fixes.py.
"""

from unittest.mock import MagicMock
import os
import sys
from types import ModuleType

os.environ.setdefault('OPENAI_API_KEY', 'sk-test-not-real')
os.environ.setdefault('ENCRYPTION_SECRET', 'omi_ZwB2ZNqB2HHpMK6wStk7sTpavJiPTFg7gXUHnc4tFABPU6pZ2c2DKgehtfgi4RZv')

# ---- Stub heavy deps before importing application code ----


class _AutoMockModule(ModuleType):
    """Module stub that returns MagicMock for any missing attribute."""

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        mock = MagicMock()
        setattr(self, name, mock)
        return mock


_stubs = [
    'database._client',
    'database.redis_db',
    'database.conversations',
    'database.memories',
    'database.vector_db',
    'database.apps',
    'database.mcp_api_key',
    'firebase_admin',
    'firebase_admin.messaging',
    'firebase_admin.auth',
    'google.cloud.firestore',
    'google.cloud.firestore_v1',
    'google.cloud.firestore_v1.FieldFilter',
    'pinecone',
    'typesense',
    'opuslib',
    'pydub',
    'pusher',
    'modal',
    'utils.executors',
    'utils.other.storage',
    'utils.other.endpoints',
    'utils.conversations.render',
    'utils.apps',
    'utils.llm.memories',
]
for mod_name in _stubs:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = _AutoMockModule(mod_name)

sys.modules['firebase_admin.auth'].InvalidIdTokenError = type('InvalidIdTokenError', (Exception,), {})


def _make_memory(memory_id, content, category='interesting', locked=False):
    return {
        'id': memory_id,
        'uid': 'test-uid',
        'is_locked': locked,
        'content': content,
        'category': category,
    }


class TestMcpRestMemorySearch:
    def test_ranks_and_sorts_by_relevance(self):
        import database.vector_db as vector_db
        import database.memories as memories_db

        vector_db.find_similar_memories = MagicMock(
            return_value=[
                {'memory_id': 'mem-1', 'category': 'interesting', 'score': 0.712345},
                {'memory_id': 'mem-2', 'category': 'work', 'score': 0.95},
            ]
        )
        # get_memories_by_ids may return in any order; the endpoint must sort by score.
        memories_db.get_memories_by_ids = MagicMock(
            return_value=[
                _make_memory('mem-1', 'coffee notes'),
                _make_memory('mem-2', 'work meeting', category='work'),
            ]
        )

        from routers.mcp import search_memories

        results = search_memories(query='coffee', limit=10, uid='test-uid')

        assert [r.id for r in results] == ['mem-2', 'mem-1']
        assert results[0].relevance_score == 0.95
        assert results[1].relevance_score == 0.7123  # rounded to 4 dp
        vector_db.find_similar_memories.assert_called_once_with('test-uid', 'coffee', threshold=0.0, limit=10)

    def test_empty_matches_returns_empty_without_db_fetch(self):
        import database.vector_db as vector_db
        import database.memories as memories_db

        vector_db.find_similar_memories = MagicMock(return_value=[])
        memories_db.get_memories_by_ids = MagicMock()

        from routers.mcp import search_memories

        results = search_memories(query='nothing here', uid='test-uid')

        assert results == []
        memories_db.get_memories_by_ids.assert_not_called()

    def test_locked_memory_content_truncated(self):
        import database.vector_db as vector_db
        import database.memories as memories_db

        long_secret = 'x' * 200
        vector_db.find_similar_memories = MagicMock(
            return_value=[{'memory_id': 'mem-locked', 'category': 'interesting', 'score': 0.88}]
        )
        memories_db.get_memories_by_ids = MagicMock(return_value=[_make_memory('mem-locked', long_secret, locked=True)])

        from routers.mcp import search_memories

        results = search_memories(query='secret', uid='test-uid')

        assert len(results) == 1
        assert results[0].content == long_secret[:70] + '...'
        assert results[0].relevance_score == 0.88
