## Salesforce LIT Plan

Use the Confluence page Salesforce LIT as the discussion anchor. Rovo search located it at https://sfdaakash.atlassian.net/wiki/spaces/SD/pages/15040520/Salesforce+LIT.

### Findings

- The product is described as a GUI application that helps users learn from Salesforce literature.
- It uses MCP tools to search and fetch the intended Salesforce documentation topic.
- Example user query: “What’s new in the current release?”
- GUI objective: help users stay current with Salesforce release updates without wrestling with difficult vocabulary.
- Future CLI/AI-agent objective: provide more context to reduce hallucinations while AI tools work on Salesforce codebases.
- Related links named on the page include Docs MCP and Agentforce Labs.

### Decisions

- The product should support Salesforce learners, developers, and AI coding agents.
- The first interface is a web GUI.
- Answers should include plain-language explanations, source links/citations, code examples where relevant, release/version context, and related topics.
- When Salesforce documentation does not support an answer, the system should say so rather than speculate.
- Initial success measures are document retrieval quality, factual grounding, and improved learner understanding.
- The web GUI should use explicit audience modes: Learner, Developer, and Agent, even though agent-specific output capabilities are deferred to future releases.
- Initial content scope is Salesforce release notes.
- The experience should support multi-turn follow-up questions against the active context.
- MVP authentication is not required.
- Learner and Developer are the active MVP modes; Agent is deferred as a functional mode/placeholder.
- Modes change prompting and presentation rather than retrieval sources or filters.
- Users select the release/version; the primary prototype task is explaining the latest release changes.
- Conversation context lasts for one browser session only.
- The UI should follow Salesforce styling conventions.
- Implementation must be Python-native only: use Gradio for the UI and do not author JavaScript, React, or a separate frontend.
- Third-party Python dependencies are allowed; standard-library-only is not a requirement.

### Integration Flow

- The LLM client receives the user's latest turn and recent browser-session history.
- It classifies the turn as `SALESFORCE` or `GENERAL`.
- `SALESFORCE` turns call Salesforce Docs MCP search with the selected release context, then fetch the relevant articles by document ID. Only fetched article content can be summarized.
- `GENERAL` turns never call MCP. The LLM answers normally using the recent conversation.
- Salesforce answers are generated only from MCP evidence. If no evidence is returned, the assistant refuses to speculate.
- If the local LLM is unavailable, recognized Salesforce keywords preserve the MCP route and the service falls back to grounded source bullets. General chat reports that the LLM is unavailable.

### Integration Responsibilities

1. `sflit_app/llm_client.py` owns intent classification, general chat, and grounded answer presentation through the OpenAI Python client.
2. `sflit_app/service.py` owns routing policy, MCP invocation, evidence validation, conversation context, and no-speculation behavior.
3. `sflit_app/mcp_client.py` owns Salesforce Docs MCP JSON-RPC calls, schema discovery, resource reads, collection normalization, and collection-scoped search.
4. `sflit_app/app.py` owns Gradio state and source-link rendering.

### Knowledge and MCP capabilities

The Knowledge panel loads live MCP metadata on demand. It uses `tools/list` for server schema, `resources/list` and `resources/read` for resource discovery, and `collection://list` for indexed collection statistics. Users can filter by source prefix or collection text, sort the results, and select one collection for the next search.

The application combines schema/info, collection discovery, search, and fetch. Search only identifies candidate documents; fetch supplies the full content accepted by the grounded answer workflow. Knowledge questions are sent to the LLM with bounded live schema and collection context.

## Scope Boundary

The assistant is general-purpose for conversation, but Salesforce knowledge claims are a grounded workflow: Salesforce-related turns must use Salesforce Docs MCP evidence, and unsupported Salesforce questions must not be answered from model memory.
