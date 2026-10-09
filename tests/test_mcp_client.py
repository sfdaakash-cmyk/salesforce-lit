import json

from sflit_app.mcp_client import (
    Collection,
    SalesforceDocsClient,
    filter_collections,
    sort_collections,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_discovery_and_resource_methods(monkeypatch):
    responses = {
        "tools/list": {"result": {"tools": [{"name": "salesforce_docs_search"}]}},
        "resources/list": {"result": {"resources": [{"uri": "collection://list"}]}},
        "resources/read": {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "collections": [
                                {"collection": "developer/apex", "document_count": 3, "chunk_count": 8}
                            ]
                        }),
                    }
                ]
            }
        },
    }

    def open_request(request, timeout):
        payload = json.loads(request.data)
        return FakeResponse(responses[payload["method"]])

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    client = SalesforceDocsClient()

    assert client.list_tools()[0]["name"] == "salesforce_docs_search"
    assert client.list_resources()[0]["uri"] == "collection://list"
    assert client.collections() == [Collection("developer/apex", 3, 8)]


def test_collections_accepts_mcp_resource_contents(monkeypatch):
    response = {
        "result": {
            "contents": [
                {
                    "uri": "collection://list",
                    "mimeType": "application/json",
                    "text": json.dumps(
                        {
                            "collections": [
                                {
                                    "collection": "admin/ai",
                                    "document_count": "1360",
                                    "chunk_count": "7012",
                                    "last_indexed": "2026-05-19T18:57:15.361Z",
                                }
                            ]
                        }
                    ),
                }
            ]
        }
    }
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse(response))

    assert SalesforceDocsClient().collections() == [
        Collection("admin/ai", 1360, 7012, "2026-05-19T18:57:15.361Z")
    ]


def test_search_forwards_selected_collection(monkeypatch):
    captured = {}

    def fake_call_tool(name, arguments):
        captured.update(name=name, arguments=arguments)
        return {"chunks": []}

    client = SalesforceDocsClient()
    monkeypatch.setattr(client, "call_tool", fake_call_tool)

    client.search("Apex changes", collections=["developer/apex"])

    assert captured == {
        "name": "salesforce_docs_search",
        "arguments": {
            "query": "Apex changes",
            "limit": 6,
            "search_mode": "hybrid",
            "collections": ["developer/apex"],
        },
    }


def test_collection_filters_and_sorting():
    collections = [
        Collection("developer/lwc", 4, 20),
        Collection("admin/security", 9, 12),
        Collection("developer/apex", 7, 30),
    ]

    assert [item.name for item in filter_collections(collections, "developer", "apex")] == [
        "developer/apex"
    ]
    assert [item.name for item in sort_collections(collections, "docs")] == [
        "admin/security",
        "developer/apex",
        "developer/lwc",
    ]
