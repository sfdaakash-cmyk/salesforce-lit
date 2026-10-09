import asyncio
from pathlib import Path
from types import SimpleNamespace

import sflit_app.service as service_module
import gradio as gr
from sflit_app.app import create_app
from sflit_app.mcp_client import Collection
from sflit_app.service import LitAnswer, SalesforceLitService


def build_service(monkeypatch, docs_client, llm_client):
    monkeypatch.setattr(service_module, "SalesforceDocsClient", lambda: docs_client)
    monkeypatch.setattr(service_module, "OpenAIClient", lambda: llm_client)
    return SalesforceLitService()


class FakeClient:
    def search(self, query, release=None, limit=6, collections=None):
        return [
            {
                "documentPath": "release-notes/spring-26/apex.html",
                "url": "https://developer.salesforce.com/docs/apex",
                "metadata": {"title": "Apex Spring '26 Release Notes"},
                "content": "Apex now supports the documented feature for this release.",
            }
        ]

    def fetch(self, document_id):
        assert document_id == "release-notes/spring-26/apex.html"
        return {
            "metadata": {"title": "Apex Spring '26 Release Notes"},
            "content": "The fetched article contains the full documented feature details.",
            "url": "https://developer.salesforce.com/docs/apex",
        }


class SalesforceFormatter:
    def is_salesforce_question(self, question, history=None):
        return True

    def answer_general(self, question, history=None):
        return "general answer"

    def answer_salesforce(
        self,
        question,
        release,
        collections,
        available_collections,
        history,
        tools,
        tool_executor,
        reading_context=None,
    ):
        results = tool_executor("search", {"query": question})
        document = tool_executor("fetch", {"document_id": results[0]["document_id"]})
        return document["excerpt"]


def test_answer_salesforce_contains_grounded_evidence_and_source(monkeypatch):
    result = build_service(monkeypatch, FakeClient(), SalesforceFormatter()).answer(
        "What changed for Apex?", "Spring '26"
    )

    assert "full documented feature details" in result.answer
    assert result.sources[0].title == "Apex Spring '26 Release Notes"
    assert result.sources[0].url.startswith("https://")


def test_salesforce_llm_can_search_and_fetch_through_service_tools(monkeypatch):
    class ToolFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            tool_names = {tool["function"]["name"] for tool in tools}
            assert {"search", "fetch"}.issubset(tool_names)
            results = tool_executor("search", {"query": question})
            document = tool_executor("fetch", {"document_id": results[0]["document_id"]})
            return document["excerpt"]

    result = build_service(monkeypatch, FakeClient(), ToolFormatter()).answer(
        "What changed for Apex?", "Spring '26"
    )

    assert "full documented feature details" in result.answer
    assert result.sources[0].document_id == "release-notes/spring-26/apex.html"


def test_answer_fetches_articles_through_salesforce_tools(monkeypatch):
    class FetchTrackingClient(FakeClient):
        def __init__(self):
            self.fetched = []

        def fetch(self, document_id):
            self.fetched.append(document_id)
            return super().fetch(document_id)

    docs_client = FetchTrackingClient()
    result = build_service(monkeypatch, docs_client, SalesforceFormatter()).answer(
        "What changed for Apex?", "Spring '26"
    )

    assert docs_client.fetched == ["release-notes/spring-26/apex.html"]
    assert "full documented feature details" in result.answer


def test_service_accepts_documentation_tool_alias_names(monkeypatch):
    class AliasFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            results = tool_executor("search_documentation", {"query": question})
            document = tool_executor("fetch_document", {"document_id": results[0]["document_id"]})
            return document["excerpt"]

    result = build_service(monkeypatch, FakeClient(), AliasFormatter()).answer(
        "What changed for Apex?", "Spring '26"
    )

    assert "full documented feature details" in result.answer
    assert result.sources[0].document_id == "release-notes/spring-26/apex.html"


def test_tool_definitions_use_canonical_names_and_fetch_handles_query_safe(monkeypatch):
    service = build_service(monkeypatch, FakeClient(), SalesforceFormatter())

    assert {tool["function"]["name"] for tool in service.tool_definitions()} == {"search", "fetch"}
    results = service.execute_tool("fetch", {"query": "What changed for Apex?"})
    assert results[0]["document_id"] == "release-notes/spring-26/apex.html"


def test_out_of_scope_question_does_not_call_mcp(monkeypatch):
    class UnexpectedClient:
        def search(self, query, release=None, limit=6, collections=None):
            raise AssertionError("MCP should not be called for general chat")

        def fetch(self, document_id):
            raise AssertionError("MCP should not be called for general chat")

    class ScopeFormatter:
        def is_salesforce_question(self, question, history=None):
            assert history == [{"role": "user", "content": "Hello"}]
            return False

        def answer_general(self, question, history=None, on_token=None):
            assert history == [{"role": "user", "content": "Hello"}]
            if on_token:
                on_token("Nice ")
                on_token("to meet you.")
            return "Nice to meet you."

    tokens = []
    result = build_service(monkeypatch, UnexpectedClient(), ScopeFormatter()).answer(
        "How are you?",
        "Latest release",
        [{"role": "user", "content": "Hello"}],
        on_token=tokens.append,
    )

    assert result.answer == "Nice to meet you."
    assert result.sources == []
    assert tokens == ["Nice ", "to meet you."]


def test_collection_catalog_and_selected_scope_reach_search(monkeypatch):
    class CollectionClient(FakeClient):
        def __init__(self):
            self.selected = None

        def search(self, query, release=None, limit=6, collections=None):
            self.selected = (release, collections)
            return super().search(query, release, limit)

    class CollectionFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            assert collections == ["developer/apex"]
            assert available_collections == ["developer/apex", "admin/security"]
            results = tool_executor("search", {"query": question, "collections": ["admin/security"]})
            return results[0]["title"]

    docs_client = CollectionClient()
    result = build_service(monkeypatch, docs_client, CollectionFormatter()).answer(
        "What changed for Apex?",
        "Spring '26",
        collections=["developer/apex"],
        available_collections=["developer/apex", "admin/security"],
    )

    assert docs_client.selected == ("Spring '26", ["developer/apex"])
    assert result.answer == "Apex Spring '26 Release Notes"


def test_mulesoft_collections_are_filtered_out_of_salesforce_catalog(monkeypatch):
    class CatalogFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            assert available_collections == ["developer/apex", "admin/security"]
            results = tool_executor("search", {"query": question})
            return results[0]["title"]

    result = build_service(
        monkeypatch,
        FakeClient(),
        CatalogFormatter(),
    ).answer(
        "What changed for Apex?",
        "Spring '26",
        available_collections=[
            "developer/apex",
            "admin/security",
            "mulesoft/salesforce-connector",
        ],
    )

    assert result.answer == "Apex Spring '26 Release Notes"


def test_root_source_names_are_expanded_to_full_collection_names(monkeypatch):
    class RootSourceClient(FakeClient):
        def __init__(self):
            self.search_collections = None

        def search(self, query, release=None, limit=6, collections=None):
            self.search_collections = collections
            return super().search(query, release, limit)

    class RootSourceFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            assert collections == ["developer", "legacydeveloper"]
            assert available_collections == ["developer/apex", "legacydeveloper/record-types"]
            results = tool_executor("search", {"query": question, "collections": ["developer", "legacydeveloper"]})
            return results[0]["title"]

    docs_client = RootSourceClient()
    result = build_service(
        monkeypatch,
        docs_client,
        RootSourceFormatter(),
    ).answer(
        "What changed for Apex?",
        "Spring '26",
        collections=["developer", "legacydeveloper"],
        available_collections=["developer/apex", "legacydeveloper/record-types"],
    )

    assert docs_client.search_collections == ["developer/apex", "legacydeveloper/record-types"]
    assert result.answer == "Apex Spring '26 Release Notes"


def test_missing_release_defaults_to_latest_and_llm_can_choose_catalog_collection(monkeypatch):
    class CollectionClient(FakeClient):
        def __init__(self):
            self.search_arguments = None

        def search(self, query, release=None, limit=6, collections=None):
            self.search_arguments = (release, collections)
            return super().search(query, release, limit, collections)

    class CollectionFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            assert release == "Latest release"
            assert collections == []
            assert available_collections == ["developer/apex"]
            results = tool_executor("search", {"query": question, "collections": ["developer/apex"]})
            return results[0]["title"]

    docs_client = CollectionClient()
    result = build_service(monkeypatch, docs_client, CollectionFormatter()).answer(
        "What changed for Apex?", None, available_collections=["developer/apex"]
    )

    assert result.answer == "Apex Spring '26 Release Notes"
    assert docs_client.search_arguments == ("Latest release", ["developer/apex"])


def test_selected_document_context_uses_salesforce_path(monkeypatch):
    class ContextFormatter(SalesforceFormatter):
        def answer_salesforce(
            self,
            question,
            release,
            collections,
            available_collections,
            history,
            tools,
            tool_executor,
            reading_context=None,
        ):
            assert reading_context == "Selected article text"
            return "Context answer"

    result = build_service(monkeypatch, FakeClient(), ContextFormatter()).answer(
        "Explain this article", "Spring '26", reading_context="Selected article text"
    )

    assert result.answer == "Context answer"
    assert result.sources == []


def test_app_builds_with_collection_catalog_and_left_pane_pdf_download():
    class WorkspaceService:
        def knowledge(self):
            return [], [Collection("developer/apex")]

    demo = create_app(chat_service=object(), workspace_service=WorkspaceService())

    assert isinstance(demo, gr.Blocks)
    pdf_download = next(
        block for block in demo.blocks.values() if isinstance(block, gr.DownloadButton)
    )
    assert pdf_download.parent.parent.children[0] is pdf_download.parent
    assert not any(isinstance(block, gr.File) for block in demo.blocks.values())


def test_collection_selection_loads_documents_without_search_box():
    class WorkspaceService:
        def __init__(self):
            self.search_calls = []

        def knowledge(self):
            return [], [Collection("developer/apex"), Collection("platform/events")]

        def search_documents(self, query, release, collections):
            self.search_calls.append((query, release, collections))
            return [SimpleNamespace(title="Apex Guide", document_id="apex-guide")]

    workspace_service = WorkspaceService()
    demo = create_app(chat_service=object(), workspace_service=workspace_service)
    load_documents = next(
        function.fn
        for function in demo.fns.values()
        if getattr(function.fn, "__name__", None) == "load_documents"
    )

    document_update, _ = load_documents(
        "Latest release", ["developer/apex", "platform/events"]
    )

    assert workspace_service.search_calls == [
        ("Salesforce documentation", "Latest release", ["developer/apex", "platform/events"])
    ]
    assert document_update["choices"] == [("Apex Guide", "apex-guide")]
    assert sum(isinstance(block, gr.Textbox) for block in demo.blocks.values()) == 1


def test_chat_streams_response_and_updates_pdf_download():
    class ChatService:
        def answer(self, *args, on_token=None):
            on_token("Streamed ")
            on_token("answer")
            return LitAnswer("Streamed answer", [])

    class WorkspaceService:
        def knowledge(self):
            return [], [Collection("developer/apex")]

    demo = create_app(chat_service=ChatService(), workspace_service=WorkspaceService())
    chat_answer = next(
        function.fn
        for function in demo.fns.values()
        if getattr(function.fn, "__name__", None) == "chat_answer"
    )

    async def collect_updates():
        updates = []
        async for update in chat_answer(
            "Question", [], "Latest release", [], "", ["developer/apex"]
        ):
            updates.append(update)
        return updates

    updates = asyncio.run(collect_updates())
    pdf_path = updates[-1][2]["value"]
    try:
        assert [update[0] for update in updates] == [
            "",
            "Streamed ",
            "Streamed answer",
            "Streamed answer",
        ]
        assert Path(pdf_path).read_bytes().startswith(b"%PDF-")
        assert updates[-1][2]["interactive"] is True
    finally:
        Path(pdf_path).unlink()


def test_blank_document_search_does_not_call_mcp(monkeypatch):
    class UnexpectedClient:
        def search(self, query, release=None, limit=6, collections=None):
            raise AssertionError("MCP should not be called for a blank search")

    service = build_service(monkeypatch, UnexpectedClient(), object())

    assert service.search_documents("  \t", "Winter '27") == []
