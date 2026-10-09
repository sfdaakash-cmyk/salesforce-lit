# End-to-End Flow of Salesforce LIT

## 1. Project Summary

This project is a Python-based Salesforce documentation assistant with a Gradio UI. It is designed to answer two categories of questions:

1. General non-Salesforce questions using a normal LLM conversation path.
2. Salesforce-related questions using a grounded documentation path that searches and fetches Salesforce documentation through the Salesforce Docs MCP server before generating an answer.

The application flow is:

User input -> Gradio UI -> SalesforceLitService -> LLM classifier -> either general chat or Salesforce documentation retrieval -> evidence-based answer -> UI display

---

## 2. High-Level File and Layer Map

| Layer | File Path | Role | Key Dependency |
|---|---|---|---|
| Bootstrap | `run_sflit.py` | Starts logging and launches the app | imports `sflit_app.app.launch` |
| UI Layer | `sflit_app/app.py` | Builds the Gradio interface and event handlers | uses `gradio`, `SalesforceLitService`, `McpClientError` |
| Service Orchestrator | `sflit_app/service.py` | Routes requests, decides Salesforce vs general, calls search/fetch, composes final answer | depends on `OpenAIClient`, `SalesforceDocsClient` |
| LLM Adapter | `sflit_app/llm_client.py` | Classifies questions and makes answer calls to OpenAI-compatible endpoints | depends on the `openai` package and environment variables |
| MCP Integration | `sflit_app/mcp_client.py` | Calls JSON-RPC MCP methods for list/search/fetch resource operations | depends on `urllib`, `json`, remote Salesforce docs endpoint |
| Dependency File | `requirements.txt` | Declares runtime packages | `openai`, `gradio`, `pytest` |
| Tests | `tests/test_service.py`, `tests/test_mcp_client.py` | Validates routing and MCP behavior | imports application modules |

---

## 3. Dependency Overview

### 3.1 External Dependencies

| Package | Purpose | Used In |
|---|---|---|
| `openai` | Connects Python code to OpenAI-compatible APIs (including Ollama local endpoint) | `sflit_app/llm_client.py` |
| `gradio` | Provides UI blocks, chat interface, dropdowns, markdown panels | `sflit_app/app.py` |
| `pytest` | Runs unit tests | `tests/*.py` |

### 3.2 Internal Dependency Chain

| Caller | Imports / Uses | Purpose |
|---|---|---|
| `run_sflit.py` | `from sflit_app.app import launch` | Starts application |
| `sflit_app/app.py` | `from .mcp_client import McpClientError` and `from .service import SalesforceLitService` | Handles UI and service integration |
| `sflit_app/service.py` | `from .llm_client import LlmClientError, OpenAIClient, build_evidence` and `from .mcp_client import Collection, McpClientError, SalesforceDocsClient` | Controls business logic |
| `sflit_app/llm_client.py` | `from openai import OpenAI` | Calls LLM server |
| `sflit_app/mcp_client.py` | `import urllib.request`, `urllib.error`, `json` | Makes remote MCP JSON-RPC calls |

---

## 4. Runtime Startup Flow

### File: `run_sflit.py`

| Line / Block | Code | Explanation |
|---|---|---|
| 1-2 | `"""Launch Salesforce LIT locally."""` and imports | File docstring and standard imports for logging and `Path` operations. |
| 4-11 | `logging.basicConfig(...)` | Configures logging to console and a log file named `sflit.log` in the project folder. This is useful for debugging service calls and request flow. |
| 13 | `from sflit_app.app import launch` | Imports the app launcher from the UI module. |
| 16-17 | `if __name__ == "__main__":` then `launch()` | Ensures the app only launches when this file is executed directly, not when imported. |

### Execution path

`run_sflit.py` -> `sflit_app.app.launch()` -> Gradio UI starts in browser mode

---

## 5. UI Layer Flow

### File: `sflit_app/app.py`

#### 5.1 Imports and constants

| Code Block | Meaning |
|---|---|
| `from __future__ import annotations` | Enables postponed evaluation of type hints for cleaner type references. |
| `import gradio as gr` | Brings in Gradio library responsible for app UI elements. |
| `from typing import Any` | Type hint support for dynamic output values. |
| `from .mcp_client import McpClientError` | Imports the MCP error type so the app can gracefully handle missing knowledge data. |
| `from .service import SalesforceLitService` | Connects the UI to the central logic layer. |
| `RELEASES = [...]` | Defines the release dropdown choices shown in the UI. |

#### 5.2 App factory: `create_app(service: SalesforceLitService | None = None)`

| Code Block | Explanation |
|---|---|
| `service = service or SalesforceLitService()` | Creates the main service instance if one is not injected. |
| `try: _, initial_collections = service.knowledge()` | Asks the service for available MCP collections and stores them for the Knowledge panel. If the MCP server cannot respond, it falls back to an empty list. |
| `except McpClientError:` | Handles MCP connectivity issues without crashing the UI. |

#### 5.3 Document loading helper

| Function | Purpose |
|---|---|
| `load_documents(release, collection)` | Searches broadly within the selected collection(s), then builds dropdown choices for documents. |
| `documents = service.search_documents(...)` | Calls the service to perform MCP search and fetch full doc content for matching records. |
| `choices = [(document.title, document.document_id) for document in documents]` | Builds the dropdown options as title + document ID pairs. |
| `gr.update(...)` | Updates the document dropdown and article viewer values. |

#### 5.4 Refresh helper

| Function | Purpose |
|---|---|
| `refresh_everything(release, selected_collection)` | Reloads collection metadata and document results when release or collection changes. |
| `_, collections = service.knowledge()` | Pulls the latest collections from the MCP server. |
| `collection_choices = [item.name for item in collections]` | Converts collection metadata into dropdown values. |
| `collection = selected_collection if selected_collection in collection_choices else None` | Preserves or clears the current collection based on validity. |

#### 5.5 Fetching article content

| Function | Purpose |
|---|---|
| `fetch_document(document_id)` | Takes a selected document ID and retrieves the full article from the service. |
| `document = service.fetch_document(document_id or "")` | Calls the service to fetch full content. |
| `link = f"\n\n[Open source]({document.url})" if document.url else ""` | Adds a clickable source link if available. |
| `gr.update(value=f"## {document.title}\n\n{document.excerpt}{link}", visible=True)` | Shows the full fetched content in the reading pane. |

#### 5.6 Chat answer handler

| Function | Purpose |
|---|---|
| `chat_answer(question, history, release, collection, reading_context)` | Sends the question and history to the service in a background worker while forwarding streamed answer tokens to the chat. |
| `if not question.strip(): return` | Avoids empty submissions. |
| `yield answer, gr.skip()` | Updates the chat with each streamed token without changing the PDF control. |
| `create_response_pdf(result.answer, result.sources)` | Creates the downloadable PDF after the answer is complete. |

#### 5.7 Gradio layout

| Layout Block | Meaning |
|---|---|
| `with gr.Blocks(title="Salesforce LIT") as demo:` | Creates the app root container. |
| `gr.Markdown("# Salesforce LIT\nDocumentation workspace for Salesforce developers")` | Header text. |
| `with gr.Row(...)` | Splits the UI into control pane and reading/chat pane. |
| `gr.DownloadButton(...)` | Shows the completed response PDF download button in the left Controls pane. |
| `release = gr.Dropdown(...)` | Release selector. |
| `collection_status = gr.Markdown(...)` | Shows the number of available collections above the collection selector. |
| `collection = gr.Dropdown(...)` | Collection filter. |
| `document = gr.Dropdown([], ...)` | Result document selector. |
| `article = gr.Markdown(...)` | Reading panel for article content. |
| `chat_interface = gr.ChatInterface(...)` | Creates the streaming chat experience and updates the left-pane PDF download button when the response completes. |

#### 5.8 Event wiring

| Event | Trigger | Action |
|---|---|---|
| `refresh.click(...)` | Button click | Reloads collection and document metadata |
| `release.change(...)` | Release dropdown changes | Refreshes data for selected release |
| `collection.change(...)` | Collection selection changes | Loads documents in that collection |
| `document.change(...)` | Document selection changes | Fetches and displays article |
| `show_chat.click(...)` | Switch to chat view | Hides reading panel, shows chat panel |
| `close_chat.click(...)` | Close chat view | Reverses display state |

#### 5.9 Launch function

| Code Block | Meaning |
|---|---|
| `def launch() -> None:` | Defines local launch entry point. |
| `create_app().launch(inbrowser=True)` | Starts the Gradio app in the user’s browser. |

---

## 6. Service Layer Flow

### File: `sflit_app/service.py`

This is the central orchestration layer. It sits between the UI and the LLM/MCP subsystems.

#### 6.1 Imports and data contracts

| Code Block | Meaning |
|---|---|
| `import inspect` | Used to check whether an LLM method accepts a `tools` and `tool_executor` signature. |
| `import logging` | Writes logs for routing and request state. |
| `from dataclasses import dataclass` | Supports lightweight structured data classes. |
| `from typing import Any, Protocol` | Enables protocols and flexible typing. |
| `from .llm_client import LlmClientError, OpenAIClient, build_evidence` | Pulls the LLM adapter and evidence builder. |
| `from .mcp_client import Collection, McpClientError, SalesforceDocsClient` | Pulls the Salesforce MCP client and collection type. |

#### 6.2 Dataclasses: `Source` and `LitAnswer`

| Dataclass | Fields | Purpose |
|---|---|---|
| `Source` | `title`, `document_id`, `url`, `excerpt` | Normalizes a single Salesforce document source for UI display and evidence building. |
| `LitAnswer` | `answer`, `sources` | Final answer payload returned to the UI. |

#### 6.3 LLM protocol contract

The `LlmClient` protocol defines the expected methods, even though the real implementation is `OpenAIClient`:

| Method | Purpose |
|---|---|
| `is_salesforce_question(...)` | Determines whether the question belongs in the Salesforce docs route. |
| `answer_general(...)` | Handles ordinary chat. |
| `format_answer(...)` | Formats evidence into a final answer. |
| `answer_knowledge(...)` | Answers metadata questions by using live MCP knowledge context. |
| `answer_salesforce(...)` | Handles Salesforce research with tool-based search/fetch support. |

This keeps the service independent from the concrete LLM implementation.

#### 6.4 `SalesforceLitService.__init__`

| Code Block | Meaning |
|---|---|
| `self.docs_client = SalesforceDocsClient()` | Creates the Salesforce Docs MCP client. |
| `self.llm_client = OpenAIClient()` | Creates the OpenAI-compatible LLM client. |

This is the moment the application wires its two main external integrations together.

#### 6.5 Entry method: `answer(...)`

This is the main request pipeline.

| Step | Code / Logic | Meaning |
|---|---|---|
| 1 | `question = question.strip()` | Removes extra spaces around the user prompt. |
| 2 | `if not question:` | Prevents unnecessary retrieval on empty input. |
| 3 | `if reading_context and reading_context.strip():` | Handles the case where the user selects a document and asks a question using its contents as context. |
| 4 | `is_salesforce = self._is_salesforce_question(question, history)` | Uses the LLM classifier when available; otherwise uses a fallback keyword list. |
| 5 | if not Salesforce -> `answer_general(...)` | Sends the question into the general conversation flow without MCP. |
| 6 | if Salesforce -> route into `answer_salesforce` or legacy retrieval | Performs document search and fetch before answering. |

#### 6.6 `reading_context` special case

| Logic | Meaning |
|---|---|
| `context_source = Source("Selected Salesforce document", "", "", reading_context.strip())` | Creates a temporary source record for the selected document content. |
| `self.llm_client.format_answer(...)` | Formats the answer using the selected article content as the evidence source. |
| `return LitAnswer(answer, [context_source])` | Provides a grounded answer without performing remote doc search. |

This covers the “document reading + question” interaction in the UI.

#### 6.7 `Salesforce` path

| Internal Step | Meaning |
|---|---|
| `answer_salesforce = getattr(self.llm_client, "answer_salesforce", None)` | Checks whether the LLM adapter supports the tool-based Salesforce mode. |
| `execute_and_record(...)` | Wraps tool execution and keeps the source list for display. |
| `self.execute_tool(...)` | Invokes the service-level functions `search` and `fetch`. |
| `sources.append(self._source_from_tool_result(result))` | Saves any fetched document metadata for UI source links. |
| `return LitAnswer(answer, sources)` | Returns the final answer and supporting sources. |

#### 6.8 Knowledge route

| Logic | Meaning |
|---|---|
| `if self._is_knowledge_question(question):` | Detects questions like “what collections are available?” |
| `context = self._knowledge_context()` | Builds tool and collection metadata from the live server. |
| `answer_knowledge(...)` | Allows the LLM to answer using live knowledge context instead of memory. |

#### 6.9 Legacy fallback

| Method | Purpose |
|---|---|
| `_answer_with_legacy_retrieval(...)` | Older compatibility branch that does document search + fetch + evidence formatting without newer tools. |

---

## 7. Search and Fetch Methods in the Service

### 7.1 `search_documents(...)`

| Step | Meaning |
|---|---|
| `if collection: chunks = self.docs_client.search(..., collection=collection)` | Uses a narrowed collection when selected. |
| `else: chunks = self.docs_client.search(...)` | Uses general search across collections. |
| `for chunk in chunks[:10]:` | Limits the number of records processed. |
| `search_source = self._source_from_chunk(chunk)` | Converts the raw MCP chunk result into a normalized source object. |
| `if not search_source.document_id: continue` | Ignores chunk entries with no document ID. |
| `document = self.docs_client.fetch(search_source.document_id)` | Fetches the full document content for grounding. |
| `documents.append(self._source_from_document(...))` | Saves the full article content as a usable source. |

### 7.2 `search(...)`

This method is used for tool execution by the LLM. It returns a smaller list of document metadata to the model.

| Block | Meaning |
|---|---|
| `return [{...}]` | Produces a dictionary list with title, document_id, url, excerpt. |
| `if source.document_id` | Only includes documents with real IDs. |

### 7.3 `fetch_document(...)`

| Block | Meaning |
|---|---|
| `if not document_id: return None` | Rejects empty document IDs. |
| `document = self.docs_client.fetch(document_id)` | Retrieves the full document from the MCP server. |
| `return self._source_from_document(...)` | Converts the full document into a normalized source object. |

### 7.4 `tool_definitions()`

This defines the LLM tool contract used by the tool-calling Salesforce flow.

| Tool | Purpose |
|---|---|
| `search` | Searches Salesforce docs for relevant matches. |
| `fetch` | Retrieves the complete document by document ID. |

Both tool schemas are intentionally strict to keep the model within the supported workflow.

---

## 8. LLM Client Layer

### File: `sflit_app/llm_client.py`

#### 8.1 Imports

| Import | Purpose |
|---|---|
| `import logging` | Logs LLM errors and request progress. |
| `import json` | Serializes tool call arguments and message payloads. |
| `import os` | Reads environment variables such as `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, and `LLM_MAX_TOKENS`. |
| `from collections.abc import Callable` | Provides type hints for tool execution functions. |
| `from typing import Any, cast` | Supports flexible JSON payload typing. |
| `from openai import OpenAI` | Connects Python code to OpenAI-compatible models, including local Ollama. |
| `from openai.types.chat import ChatCompletionMessageParam` | Provides type annotation support for chat message payloads. |

#### 8.2 Environment configuration

| Attribute | Value Source | Default |
|---|---|---|
| `self.api_key` | `LLM_API_KEY` or `OPENAI_API_KEY` | `ollama` |
| `self.base_url` | `LLM_BASE_URL` | `http://localhost:11434/v1` |
| `self.model` | `LLM_MODEL` | `gpt-oss` |
| `self.timeout` | `LLM_TIMEOUT_SECONDS` | `120` |
| `self.max_tokens` | `LLM_MAX_TOKENS` | `512` |

This means the app can run against a local Ollama endpoint without adding a cloud API key.

#### 8.3 `OpenAIClient.__init__`

| Code Block | Meaning |
|---|---|
| `self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)` | Creates the OpenAI-compatible client used for all LLM calls. |

#### 8.4 `format_answer(...)`

This function turns evidence into the final answer text.

| Part | Meaning |
|---|---|
| `system_prompt` | Tells the model to answer using only the evidence supplied in the prompt. |
| `messages=[...]` | Sends a system message and user message with audience, release, question, and raw evidence. |
| `response = self.client.chat.completions.create(...)` | Calls the LLM to produce the final answer. |
| `answer = (response.choices[0].message.content or "").strip()` | Extracts the answer from the API response. |
| `if not answer: raise LlmClientError(...)` | Prevents empty or invalid output from being passed to the UI. |

#### 8.5 `answer_knowledge(...)`

| Purpose | Meaning |
|---|---|
| Uses live metadata from MCP | Builds system prompt instructions to answer only from the provided server tool and collection information. |
| Supports tool calling | If tools and tool_executor are supplied, the model can call `search` and/or `fetch`. |
| Handles multiple rounds | Loops up to 5 times to let the model decide whether more evidence is needed. |

#### 8.6 `answer_salesforce(...)`

| Part | Meaning |
|---|---|
| `system_prompt` | Tells the model to search the Salesforce docs before answering. |
| `messages = [...]` | Includes conversation history and the current question. |
| `_complete_with_tools(...)` | Runs the tool-based turn loop. |

This branch is used only when the service has determined the user question is Salesforce-specific.

#### 8.7 `_complete_with_tools(...)`

| Logic | Meaning |
|---|---|
| `for _ in range(8):` | Allows repeated tool usage in one turn. |
| `request = {"model": ..., "messages": ...}` | Builds the OpenAI-compatible chat request. |
| `if tools and tool_executor:` | Includes tool schemas and executor binding for tool calling. |
| `tool_calls = getattr(message, "tool_calls", None) or []` | Reads any tool-call requests from the model. |
| `result = tool_executor(call.function.name, arguments)` | Executes a service tool such as `search` or `fetch`. |
| `messages.append({"role": "tool", ...})` | Provides tool output back to the model as evidence. |

This loop is the core of the grounded Salesforce research workflow.

---

## 9. MCP Client Layer

### File: `sflit_app/mcp_client.py`

This file is the transport layer between the application and the remote Salesforce documentation server.

#### 9.1 Imports and endpoint

| Import / Constant | Meaning |
|---|---|
| `import json` | Encodes the JSON-RPC payload. |
| `import urllib.error` and `import urllib.request` | Execute HTTP POST requests to the remote MCP endpoint. |
| `MCP_ENDPOINT = "https://salesforce-docs-76258744c9d7.herokuapp.com/api/mcp"` | Remote endpoint for Salesforce documentation access. |

This is the external service that provides search and fetch capabilities.

#### 9.2 `McpClientError`

| Item | Meaning |
|---|---|
| `class McpClientError(RuntimeError)` | Standard exception for any transport, parsing, or server-side MCP problem. |

#### 9.3 `Collection` dataclass

| Field | Meaning |
|---|---|
| `name` | Name of the collection, for example `developer/apex` |
| `document_count` | Number of documents in that collection |
| `chunk_count` | Number of indexed chunks |
| `last_indexed` | Timestamp of last indexing |
| `source` property | Extracts the source prefix before the first `/` |

#### 9.4 `_request(method, params)`

This is the central low-level method.

| Step | Meaning |
|---|---|
| `payload = {"jsonrpc": "2.0", "method": method, "id": 1}` | Standard JSON-RPC request frame. |
| `payload["params"] = params` | Adds method arguments when needed. |
| `urllib.request.Request(...)` | Builds the HTTP call to the MCP endpoint. |
| `response.read().decode("utf-8")` | Reads raw response JSON. |
| `json.loads(payload_text)` | Parses the JSON payload. |
| `if "error" in result:` | Raises `McpClientError` when the remote server reports an error. |

This method normalizes the connection layer so the rest of the application can use a clean Python API.

#### 9.5 `_content(result)`

| Logic | Meaning |
|---|---|
| `structured = result.get("structuredContent")` | Uses the preferred MCP format if present. |
| `for item in result.get("content", ...)` | Falls back to content arrays and tries to parse embedded JSON text. |
| `json.loads(item.get("text", ""))` | Extracts JSON embedded in content blocks. |

This is important because MCP servers can reply with different payload layouts depending on the tool.

#### 9.6 Public client methods

| Method | Purpose |
|---|---|
| `call_tool(name, arguments)` | Calls an MCP tool by name and arguments. |
| `list_tools()` | Returns the server schema (`tools/list`). |
| `list_resources()` | Returns the server resource metadata (`resources/list`). |
| `read_resource(uri)` | Reads a specific resource such as `collection://list`. |
| `collections()` | Converts resource data into `Collection` objects. |
| `search(...)` | Executes `salesforce_docs_search` with a query, release, limit, and optional collection. |
| `fetch(document_id)` | Executes `salesforce_docs_fetch` using a document ID. |

#### 9.7 Search logic

| Line / Block | Meaning |
|---|---|
| `search_query = query.strip()` | Removes whitespace. |
| `if release and release != "Latest release":` | Adds release context to the search when a specific release is selected. |
| `arguments = {"query": ..., "limit": limit, "search_mode": "hybrid"}` | Uses hybrid search mode for better result quality. |
| `if collection:` | Applies a collection filter if the user selected one. |
| `content = self.call_tool("salesforce_docs_search", arguments)` | Calls the remote tool. |
| `chunks = content.get("chunks", [])` | Extracts the search result document chunks. |

A chunk is not necessarily a final article; it is usually a semantic slice of a document that still needs fetching.

---

## 10. Data Normalization and Safety Rules

### File: `sflit_app/service.py`

The service normalizes raw search data into `Source` objects.

| Method | Purpose |
|---|---|
| `_source_from_chunk(chunk)` | Converts a raw chunk into a document-like record with title, ID, URL, and excerpt. |
| `_source_from_document(search_source, document)` | Replaces the search snippet with the full article content while preserving document metadata and URL. |
| `build_evidence(sources)` | Creates a compact evidence block passed to the LLM. |

### Safety rules in project behavior

| Rule | Why It Exists |
|---|---|
| If no Salesforce evidence is found, answer with a refusal instead of speculation. | Prevents hallucinated documentation claims. |
| Use the LLM only after search and fetch steps for Salesforce turns. | Keeps answers grounded in actual Salesforce docs. |
| General questions do not call MCP. | Avoids unnecessary calls and keeps non-Salesforce chat natural. |
| `reading_context` is treated as evidence when a document is selected. | Supports direct document-based question answering. |

---

## 11. End-to-End Request Lifecycle

### 11.1 General question flow

| Step | Module | Action |
|---|---|---|
| 1 | UI (`app.py`) | User submits a question from the chat interface. |
| 2 | Service (`service.py`) | Calls `_is_salesforce_question(...)`. |
| 3 | LLM (`llm_client.py`) | Returns `False` for normal non-Salesforce prompts. |
| 4 | Service | Calls `answer_general(...)`. |
| 5 | UI | Displays the result without sources. |

### 11.2 Salesforce question flow

| Step | Module | Action |
|---|---|---|
| 1 | UI (`app.py`) | User enters a Salesforce prompt and optional release/collection. |
| 2 | Service (`service.py`) | Determines that the question is Salesforce-related. |
| 3 | Service | Uses `self.docs_client.search(...)` to find relevant docs. |
| 4 | MCP client (`mcp_client.py`) | Calls remote MCP `salesforce_docs_search`. |
| 5 | Service | Uses `_source_from_chunk(...)` to normalize result chunks. |
| 6 | Service | Calls `self.docs_client.fetch(document_id)` for candidate documents. |
| 7 | LLM (`llm_client.py`) | Receives evidence and formats the answer with `format_answer(...)` or tool-driven Salesforce mode. |
| 8 | UI | Displays the answer and source links. |

---

## 12. Important File Paths and Their Exact Roles

| File Path | Exact Role |
|---|---|
| `run_sflit.py` | Launch script for the local application. |
| `sflit_app/__init__.py` | Package marker; no heavy logic in this project. |
| `sflit_app/app.py` | Browser UI and event binding layer. |
| `sflit_app/service.py` | Traffic controller, search/fetch orchestration, and safety checks. |
| `sflit_app/llm_client.py` | OpenAI-compatible client and prompt routing logic. |
| `sflit_app/mcp_client.py` | Salesforce docs MCP communication layer over JSON-RPC. |
| `requirements.txt` | Declares package dependencies. |
| `tests/test_service.py` | Validates service routing and grounded-answer logic. |
| `tests/test_mcp_client.py` | Validates MCP list/search/fetch behavior and collection formatting. |

---

## 13. Summary

The application follows a classic layered architecture:

- UI layer: `sflit_app/app.py`
- Service orchestration: `sflit_app/service.py`
- LLM integration: `sflit_app/llm_client.py`
- Remote documentation access: `sflit_app/mcp_client.py`
- Startup/bootstrap: `run_sflit.py`

The most important architectural rule is that Salesforce questions are not answered from general model memory alone. They are routed through a retrieval pipeline that searches the Salesforce Docs MCP server, fetches relevant full documents, and then summarizes only the grounded evidence.

This makes the project suitable for documentation-grounded Q&A while keeping the user experience simple through a local Gradio interface.
