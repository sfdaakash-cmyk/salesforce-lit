from types import SimpleNamespace

from sflit_app.llm_client import OpenAIClient


def test_salesforce_prompt_includes_both_reference_documents(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    captured = {}

    def create_completion(**request):
        captured.update(request)
        message = SimpleNamespace(content="Grounded answer", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)

    answer = client.answer_salesforce(
        "What changed in Apex?",
        "Latest release",
        available_collections=["developer/apex"],
    )

    system_prompt = captured["messages"][0]["content"]
    assert answer == "Grounded answer"
    assert captured["temperature"] == 0
    assert "Target a specific collection" in system_prompt
    assert "Available collection catalog: developer/apex" in system_prompt
    assert "Cite supporting fetched documents by title" in system_prompt


def test_general_prompt_includes_response_formatting_instructions(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    captured = {}

    def create_completion(**request):
        captured.update(request)
        message = SimpleNamespace(content="General answer")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)

    assert client.answer_general("Say hello") == "General answer"
    assert captured["temperature"] == 0
    assert "Cite supporting fetched documents by title" in captured["messages"][0]["content"]


def test_general_answer_streams_final_response_tokens(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    captured = {}

    def create_completion(**request):
        captured.update(request)
        return iter(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"))]
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=" there."))]
                ),
            ]
        )

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)
    tokens = []

    answer = client.answer_general("Say hello", on_token=tokens.append)

    assert answer == "Hello there."
    assert tokens == ["Hello", " there."]
    assert captured["stream"] is True


def test_salesforce_final_answer_streams_after_tool_decision(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    requests = []

    def create_completion(**request):
        requests.append(request)
        if request.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="Grounded"))]
                    ),
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=" answer"))]
                    ),
                ]
            )
        message = SimpleNamespace(content="Initial answer", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)
    tokens = []

    answer = client._complete_with_tools(
        [{"role": "user", "content": "What changed?"}],
        tools=None,
        tool_executor=None,
        on_token=tokens.append,
    )

    assert answer == "Grounded answer"
    assert tokens == ["Grounded", " answer"]
    assert requests[-1]["stream"] is True


def test_salesforce_empty_completion_is_retried_once(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    requests = []

    def create_completion(**request):
        requests.append(request)
        content = None if len(requests) == 1 else "Grounded answer"
        message = SimpleNamespace(content=content, tool_calls=[])
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice])

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)

    answer = client.answer_salesforce("What changed in Apex?", "Latest release")

    assert answer == "Grounded answer"
    assert len(requests) == 2
    assert all(request["temperature"] == 0 for request in requests)
    assert "previous response was empty" in requests[1]["messages"][-1]["content"]


def test_salesforce_classification_uses_zero_temperature(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    captured = {}

    def create_completion(**request):
        captured.update(request)
        message = SimpleNamespace(content="SALESFORCE")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)

    assert client.is_salesforce_question("What is Apex?")
    assert captured["temperature"] == 0


def test_salesforce_finalization_uses_zero_temperature(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")
    captured = {}

    def create_completion(**request):
        captured.update(request)
        message = SimpleNamespace(content="Grounded answer")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)

    assert client._finalize_tool_response([]) == "Grounded answer"
    assert captured["temperature"] == 0


def test_general_answer_streams_visible_reasoning_before_final_tokens(monkeypatch):
    client = OpenAIClient(api_key="test", base_url="http://localhost:11434/v1")

    def create_completion(**request):
        assert request["stream"] is True
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="I should answer politely.")
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"))]
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=" there."))]
                ),
            ]
        )

    monkeypatch.setattr(client.client.chat.completions, "create", create_completion)
    tokens = []

    answer = client.answer_general("Say hello", on_token=tokens.append)

    assert answer == "Hello there."
    assert tokens == ["I should answer politely.", "Hello", " there."]