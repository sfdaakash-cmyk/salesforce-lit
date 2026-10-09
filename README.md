# Salesforce LIT

A Python-native Salesforce documentation assistant. It serves a Gradio documentation workspace, chats normally for general questions, and uses Salesforce Docs MCP to ground Salesforce-related answers in Salesforce literature.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_sflit.py
```

Open `http://127.0.0.1:7860`. The app uses the Salesforce Docs MCP endpoint used by the original CLI project. The UI is served by Gradio.

For concise, plain-English bullet answers, start Ollama and make sure the model is available:

```powershell
ollama pull llama-3.2
ollama serve
```

The app uses the OpenAI Python client against Ollama's local OpenAI-compatible endpoint. Set `LLM_MODEL=llama3.2:latest` for the installed lightweight model, or keep `LLM_MODEL=gpt-oss` if you prefer the larger model. The LLM first classifies each turn. Salesforce turns receive the live collection catalog and selected release, follow `search_guide.md` to prepare MCP searches, and fetch relevant documents before answering. Final answers stream into the chat, and a button in the left Controls pane downloads the completed response as a local PDF with its Salesforce source citations. An unset release uses `Latest release`.

## MCP Knowledge

The Knowledge section uses the MCP protocol to discover the live server schema (`tools/list`), inspect resources, and read `collection://list`. It displays collection document/chunk counts and supports source-prefix filtering, text filtering, and sorting by name, documents, or chunks. Selecting a collection scopes subsequent documentation searches.

The four application capabilities work together as follows:

1. Server schema explains which named tools and input contracts are available.
2. Collections show where indexed Salesforce knowledge lives.
3. Search identifies relevant document IDs, optionally within a selected collection.
4. Fetch retrieves the full document that may be used as answer evidence.

Questions about available tools or collections are answered from live MCP metadata rather than model memory.

## Test

```powershell
python -m pytest
```

The MVP supports Learner and Developer modes, release selection, LLM intent routing, normal multi-turn conversation, Salesforce MCP grounding, strict no-source refusal, and source links.
