"""Grounded answer orchestration for Salesforce LIT."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

from .llm_client import LlmClientError, OpenAIClient
from .mcp_client import Collection, McpClientError, SalesforceDocsClient


@dataclass(frozen=True)
class Source:
    """One normalized Salesforce release-note result returned by the docs search client."""

    title: str
    document_id: str
    url: str
    excerpt: str


@dataclass(frozen=True)
class LitAnswer:
    """Response payload returned to the UI or API: answer text plus supporting sources."""

    answer: str
    sources: list[Source]


class LlmClient(Protocol):
    """Static contract for the LLM adapter used by the service.

    This is not a runtime class that the application instantiates directly. It exists mainly for
    typing and for documenting the LLM implementation used by the service. The real runtime object
    is OpenAIClient and is responsible for:
    1) deciding whether a prompt is about Salesforce,
    2) answering non-Salesforce prompts, and
    3) answering Salesforce prompts through MCP-backed tools.
    """

    def is_salesforce_question(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> bool:
        ...

    def answer_general(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        ...

    def answer_salesforce(
        self,
        question: str,
        release: str,
        collections: list[str] | None = None,
        available_collections: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any | None = None,
        reading_context: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        ...


class SalesforceLitService:
    """Orchestrates the Salesforce release-note answer flow.

    This service is the main entry point used by the app. It decides whether a user
    request is Salesforce-related, then delegates either general chat or grounded
    Salesforce tool use to its configured LLM client.
    """

    def __init__(self) -> None:
        self.docs_client = SalesforceDocsClient()
        self.llm_client = OpenAIClient()

    def answer(
        self,
        question: str,
        release: str | None,
        history: list[dict[str, str]] | None = None,
        collections: list[str] | str | None = None,
        reading_context: str | None = None,
        available_collections: list[str] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> LitAnswer:
        """Return a grounded answer and the supporting docs used to form it."""

        logger.info("answer: start request | release=%s | history=%s", release, bool(history))
        logger.debug("answer: question=%r", question)

        release = release.strip() if release else ""
        if not release:
            logger.info("answer: no release specified; using latest release")
            release = "Latest release"

        available_catalog = self._filter_salesforce_collections(available_collections or [])
        selected_collections = self._filter_salesforce_collections(
            [collections] if isinstance(collections, str) else list(collections or [])
        )
        logger.info(
            "answer: collection scope | selected=%s | available=%s",
            selected_collections,
            available_catalog,
        )

        question = question.strip()
        # A blank question is a harmless interaction and should not trigger any docs lookup.
        if not question:
            logger.info("answer: empty question received; returning help text")
            return LitAnswer("How can I help?", [])

        is_salesforce = self._is_salesforce_question(question, history)
        logger.info("answer: Salesforce routing decision=%s | question=%r", is_salesforce, question)
        if not is_salesforce:
            try:
                if on_token:
                    answer = self.llm_client.answer_general(
                        question, history, on_token=on_token
                    )
                else:
                    answer = self.llm_client.answer_general(question, history)
                return LitAnswer(answer, [])
            except LlmClientError as exc:
                logger.exception("answer: general chat failed")
                return LitAnswer(f"I could not answer that right now: {exc}", [])

        try:
            logger.info("answer: handing Salesforce request to tool-enabled LLM")
            sources: list[Source] = []

            def execute_and_record(name: str, arguments: dict[str, Any]) -> Any:
                tool_name = name
                logger.info("answer: LLM tool call | name=%s | arguments=%s", tool_name, arguments)
                if tool_name == "search":
                    requested_collections = selected_collections or arguments.get(
                        "collections", available_catalog
                    )
                    requested_collections = requested_collections or []
                    invalid_collections = set(requested_collections) - set(available_catalog)
                    if invalid_collections:
                        logger.warning(
                            "answer: rejecting search collection names | requested=%s | available=%s",
                            requested_collections,
                            available_catalog,
                        )
                        return {
                            "error": "Unknown collection name(s): "
                            + ", ".join(sorted(invalid_collections)),
                            "valid_collections": available_catalog,
                            "instruction": "Retry search using exact names from valid_collections.",
                        }
                    logger.info("answer: search collection names accepted | names=%s", requested_collections)
                    arguments = {**arguments, "collections": requested_collections}
                result = self.execute_tool(
                    tool_name,
                    {
                        **arguments,
                        "release": arguments.get("release", release),
                    }
                    if tool_name == "search"
                    else arguments,
                )
                if tool_name == "fetch" and result:
                    sources.append(self._source_from_tool_result(result))
                return result

            salesforce_arguments: dict[str, Any] = {
                "question": question,
                "release": release,
                "collections": selected_collections,
                "available_collections": available_catalog,
                "history": history,
                "tools": self.tool_definitions(available_catalog),
                "tool_executor": execute_and_record,
                "reading_context": (
                    reading_context.strip()
                    if reading_context and reading_context.strip()
                    else None
                ),
            }
            if on_token:
                salesforce_arguments["on_token"] = on_token
            answer = self.llm_client.answer_salesforce(**salesforce_arguments)
            return LitAnswer(answer, sources)
        except McpClientError as exc:
            logger.exception("answer: MCP retrieval failed")
            return LitAnswer(f"I could not reach the Salesforce documentation service: {exc}", [])
        except LlmClientError as exc:
            logger.exception("answer: Salesforce LLM flow failed")
            return LitAnswer(f"I could not answer that right now: {exc}", [])

    def knowledge(self) -> tuple[list[dict[str, Any]], list[Collection]]:
        """Return the server schema and indexed collections for the Knowledge UI."""

        try:
            return self.docs_client.list_tools(), self.docs_client.collections()
        except McpClientError:
            logger.exception("knowledge: unable to load MCP metadata")
            raise

    def search_documents(
        self,
        query: str,
        release: str = "Latest release",
        collections: list[str] | None = None,
    ) -> list[Source]:
        """Search and fetch complete Salesforce documents for the document workspace."""

        if not query.strip():
            return []
        if collections:
            chunks = self.docs_client.search(
                query, release=release, limit=10, collections=collections
            )
        else:
            chunks = self.docs_client.search(query, release=release, limit=10)
        documents: list[Source] = []
        for chunk in chunks[:10]:
            search_source = self._source_from_chunk(chunk)
            if not search_source.document_id:
                continue
            try:
                document = self.docs_client.fetch(search_source.document_id)
            except McpClientError:
                logger.warning("search_documents: unable to fetch %r", search_source.document_id)
                continue
            documents.append(self._source_from_document(search_source, document))
        return documents

    def search(
        self,
        query: str,
        release: str = "Latest release",
        collections: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Search Salesforce documents for an LLM tool call."""

        if collections:
            chunks = self.docs_client.search(
                query, release=release, limit=10, collections=collections
            )
        else:
            chunks = self.docs_client.search(query, release=release, limit=10)
        return [
            {
                "title": source.title,
                "document_id": source.document_id,
                "url": source.url,
                "excerpt": source.excerpt,
            }
            for source in (self._source_from_chunk(chunk) for chunk in chunks[:10])
            if source.document_id
        ]

    def fetch_document(self, document_id: str) -> Source | None:
        """Fetch one complete document by its MCP document identifier."""

        if not document_id:
            return None
        document = self.docs_client.fetch(document_id)
        return self._source_from_document(
            Source("Salesforce document", document_id, "", ""), document
        )

    def fetch(self, document_id: str) -> dict[str, str] | None:
        """Fetch one complete Salesforce document for an LLM tool call."""

        document = self.fetch_document(document_id)
        if not document:
            return None
        return {
            "title": document.title,
            "document_id": document.document_id,
            "url": document.url,
            "excerpt": document.excerpt,
        }

    def tool_definitions(
        self, available_collections: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return the service tools that the LLM may invoke for Salesforce knowledge."""

        search_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "release": {"type": "string"},
                "collections": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        **({"enum": available_collections} if available_collections else {}),
                    },
                    "description": "Best-matching collection names from the supplied collection catalog.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        fetch_schema = {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
            "additionalProperties": False,
        }

        return [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search Salesforce documentation and return matching documents.",
                    "parameters": search_schema,
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch",
                    "description": "Fetch the complete Salesforce document by document identifier.",
                    "parameters": fetch_schema,
                },
            },
        ]

    @staticmethod
    def _normalize_tool_name(name: str) -> str:
        """Normalize the alternative tool names emitted by the LLM to the canonical service names."""

        aliases = {
            "search_documentation": "search",
            "search_documents": "search",
            "fetch_document": "fetch",
            "fetch_documentation": "fetch",
        }
        return aliases.get(name.strip(), name.strip())

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute an LLM tool through the MCP-backed service methods only."""

        tool_name = self._normalize_tool_name(name)
        if tool_name == "search":
            if "document_id" in arguments and "query" not in arguments:
                logger.warning(
                    "execute_tool: search request unexpectedly included document_id=%r; retrying as fetch",
                    arguments.get("document_id"),
                )
                return self.fetch(**arguments)
            return self.search(**arguments)
        if tool_name == "fetch":
            if "query" in arguments and "document_id" not in arguments:
                logger.warning(
                    "execute_tool: fetch request unexpectedly included query=%r; retrying as search",
                    arguments.get("query"),
                )
                return self.search(**arguments)
            return self.fetch(**arguments)
        raise ValueError(f"Unknown Salesforce service tool: {name}")

    @staticmethod
    def _source_from_tool_result(result: dict[str, Any]) -> Source:
        return Source(
            str(result.get("title", "Salesforce document")),
            str(result.get("document_id", "")),
            str(result.get("url", "")),
            str(result.get("excerpt", "")),
        )

    def _is_salesforce_question(
        self, question: str, history: list[dict[str, str]] | None
    ) -> bool:
        """Check whether this turn should follow the Salesforce docs workflow."""

        try:
            # Prefer the LLM classifier because it uses conversational context to correctly
            # resolve follow-up Salesforce questions.
            #self.llm_client.is_salesforce_question(question, history)
            isSalesforce = 1
            return isSalesforce ==1
        except LlmClientError:
            # If the classifier is unavailable, use a conservative keyword fallback so we do not
            # accidentally route a Salesforce question into the general chat path.
            return any(
                term in question.lower()
                for term in (
                    "salesforce",
                    "apex",
                    "lightning",
                    "soql",
                    "sobject",
                    "force.com",
                    "trailhead",
                    "sales cloud",
                    "service cloud",
                    "what's new in salesforce",
                )
            )

    @staticmethod
    def _filter_salesforce_collections(collections: list[str] | None) -> list[str]:
        """Limit the collection catalog to Salesforce documentation roots and prevent unrelated product catalogs from being used as evidence."""

        allowed_roots = {"admin", "developer", "legacydeveloper", "architect", "tableau"}
        if not collections:
            return []
        filtered = [name for name in collections if name.split("/", 1)[0] in allowed_roots]
        return filtered

    @staticmethod
    def _source_from_chunk(chunk: dict[str, Any]) -> Source:
        """Normalize a raw search result into the Source object used by the service."""

        metadata = chunk.get("metadata", {})
        excerpt = " ".join(chunk.get("content", "").split())
        return Source(
            title=metadata.get("title", chunk.get("documentPath", "Salesforce release note")),
            document_id=chunk.get("documentPath", ""),
            url=chunk.get("url", ""),
            excerpt=excerpt[:900],
        )

    @staticmethod
    def _source_from_document(search_source: Source, document: dict[str, Any]) -> Source:
        """Use fetched article content while preserving search result citation metadata."""

        metadata = document.get("metadata", {})
        content = document.get("content", document.get("text", ""))
        excerpt = str(content).strip()
        return Source(
            title=metadata.get("title", search_source.title),
            document_id=search_source.document_id,
            url=document.get("url", search_source.url),
            excerpt=excerpt,
        )
