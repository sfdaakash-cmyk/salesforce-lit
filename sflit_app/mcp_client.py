"""JSON-RPC client for the Salesforce Docs MCP server."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MCP_ENDPOINT = "https://salesforce-docs-76258744c9d7.herokuapp.com/api/mcp"


class McpClientError(RuntimeError):
    """Raised when the Salesforce Docs MCP server cannot answer a request."""


@dataclass(frozen=True)
class Collection:
    """Indexed Salesforce documentation collection metadata."""

    name: str
    document_count: int = 0
    chunk_count: int = 0
    last_indexed: str = ""

    @property
    def source(self) -> str:
        return self.name.split("/", 1)[0]


class SalesforceDocsClient:
    """Call the Salesforce Docs MCP tools over JSON-RPC."""

    def __init__(self, endpoint: str = MCP_ENDPOINT, timeout: int = 30) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": 1,
        }
        if params:
            payload["params"] = params
        logger.info("mcp: calling method=%s | params=%s", method, params or {})
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload_text = response.read().decode("utf-8")
                result = json.loads(payload_text)
                logger.info("mcp: method=%s response received | payload_chars=%s", method, len(payload_text))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.exception("mcp: method=%s call failed", method)
            raise McpClientError(f"Salesforce Docs MCP is unavailable: {exc}") from exc

        if "error" in result:
            message = result["error"].get("message", "Unknown MCP error")
            logger.error("mcp: method=%s returned error=%s", method, message)
            raise McpClientError(message)
        return result.get("result", {})

    @staticmethod
    def _content(result: dict[str, Any]) -> dict[str, Any]:
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for item in result.get("content", result.get("contents", [])):
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                try:
                    parsed = json.loads(item.get("text", ""))
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return {}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._content(self._request("tools/call", {"name": name, "arguments": arguments}))

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list").get("tools", [])

    def list_resources(self) -> list[dict[str, Any]]:
        return self._request("resources/list").get("resources", [])

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self._content(self._request("resources/read", {"uri": uri}))

    def collections(self) -> list[Collection]:
        content = self.read_resource("collection://list")
        entries = content.get("collections", content.get("items", content))
        if isinstance(entries, dict):
            entries = entries.get("data", [])
        if not isinstance(entries, list):
            return []
        return [
            Collection(
                name=str(item.get("collection", item.get("name", ""))),
                document_count=int(item.get("document_count", item.get("docs", 0)) or 0),
                chunk_count=int(item.get("chunk_count", item.get("chunks", 0)) or 0),
                last_indexed=str(item.get("last_indexed", "")),
            )
            for item in entries
            if isinstance(item, dict) and item.get("collection", item.get("name"))
        ]

    def search(
        self,
        query: str,
        release: str | None = None,
        limit: int = 6,
        collections: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        search_query = query.strip()
        if release and release != "Latest release":
            search_query = f"{release} release notes: {search_query}"
        logger.info("mcp.search: query=%r | release=%r | limit=%s", search_query, release, limit)
        arguments: dict[str, Any] = {"query": search_query, "limit": limit, "search_mode": "hybrid"}
        if collections:
            arguments["collections"] = collections
        content = self.call_tool("salesforce_docs_search", arguments)
        chunks = content.get("chunks", [])
        logger.info("mcp.search: returned %s chunks", len(chunks))
        return chunks

    def fetch(self, document_id: str) -> dict[str, Any]:
        logger.info("mcp.fetch: document_id=%r", document_id)
        return self.call_tool("salesforce_docs_fetch", {"id": document_id})


def filter_collections(
    collections: list[Collection], source: str = "All sources", text: str = ""
) -> list[Collection]:
    """Filter collections using the CLI's source-prefix and text semantics."""

    normalized_text = text.strip().lower()
    return [
        item
        for item in collections
        if (source == "All sources" or item.source == source)
        and (not normalized_text or normalized_text in item.name.lower())
    ]


def sort_collections(collections: list[Collection], sort_by: str = "name") -> list[Collection]:
    """Return collections sorted by a supported Knowledge metric."""

    key = {
        "docs": lambda item: item.document_count,
        "chunks": lambda item: item.chunk_count,
        "name": lambda item: item.name.lower(),
    }.get(sort_by, lambda item: item.name.lower())
    return sorted(collections, key=key, reverse=sort_by in {"docs", "chunks"})
