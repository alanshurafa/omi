"""
Tests for the search_memories tool in the standalone MCP server.

Validates the REST helper builds correct URLs/params, handles HTTP errors,
does not log the raw query, and the Pydantic model enforces required args.
"""

from unittest.mock import patch, MagicMock
import logging

import pytest

from mcp_server_omi.server import (
    search_memories,
    SearchMemories,
    OmiTools,
)


class TestSearchMemoriesHelper:
    """Tests for the search_memories REST helper function."""

    def test_builds_correct_url_and_params(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "m1", "content": "Result 1", "category": "interesting", "relevance_score": 0.91},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("mcp_server_omi.server.requests.get", return_value=mock_response) as mock_get:
            logger = logging.getLogger("test")
            result = search_memories(logger, "omi_mcp_testkey", query="coffee preferences", limit=5)

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "memories/search" in call_args.args[0]
            assert call_args.kwargs["params"]["query"] == "coffee preferences"
            assert call_args.kwargs["params"]["limit"] == 5
            assert call_args.kwargs["headers"]["Authorization"] == "Bearer omi_mcp_testkey"

        assert result == [{"id": "m1", "content": "Result 1", "category": "interesting", "relevance_score": 0.91}]

    def test_default_limit(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("mcp_server_omi.server.requests.get", return_value=mock_response) as mock_get:
            logger = logging.getLogger("test")
            search_memories(logger, "omi_mcp_testkey", query="test")

            assert mock_get.call_args.kwargs["params"]["limit"] == 10

    def test_raises_on_http_error(self):
        from requests.exceptions import HTTPError

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")

        with patch("mcp_server_omi.server.requests.get", return_value=mock_response):
            logger = logging.getLogger("test")
            with pytest.raises(HTTPError):
                search_memories(logger, "omi_mcp_testkey", query="test")

    def test_does_not_log_raw_query(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("mcp_server_omi.server.requests.get", return_value=mock_response):
            logger = MagicMock(spec=logging.Logger)
            search_memories(logger, "key", query="my secret medical condition")

            log_message = logger.info.call_args[0][0]
            assert "my secret medical condition" not in log_message


class TestSearchMemoriesModel:
    """Tests for the SearchMemories Pydantic model."""

    def test_query_is_required(self):
        schema = SearchMemories.model_json_schema()
        assert "query" in schema.get("required", [])

    def test_defaults_are_correct(self):
        model = SearchMemories(query="test")
        assert model.limit == 10
        assert model.api_key is None

    def test_all_fields_accepted(self):
        model = SearchMemories(api_key="omi_mcp_test", query="search term", limit=5)
        assert model.query == "search term"
        assert model.limit == 5
        assert model.api_key == "omi_mcp_test"


class TestOmiToolsEnum:
    """Verify the enum includes the new tool."""

    def test_search_memories_in_enum(self):
        assert OmiTools.SEARCH_MEMORIES == "search_memories"
