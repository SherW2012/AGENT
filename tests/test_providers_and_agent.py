import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bnct_tps_agent.agent import AgentRuntime
from bnct_tps_agent.audit import AuditLogger
from bnct_tps_agent.config import Settings
from bnct_tps_agent.providers import get_provider


class FakeMessage:
    def __init__(self, *, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=True):
        result = {"role": "assistant"}
        if self.content is not None:
            result["content"] = self.content
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return result


class FakeCompletions:
    def __init__(self, messages):
        self.messages = list(messages)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(id="fake-response", choices=[SimpleNamespace(message=self.messages.pop(0))])


class FakeStreamingCompletions:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return iter(self.chunks.pop(0))


class FakeRegistry:
    chat_schemas = [{"type": "function", "function": {"name": "list_project_files"}}]

    def __init__(self):
        self.calls = []

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": True, "result": {"files": ["README.md"]}}


class ProviderAndAgentTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_provider_defaults_and_key_environment_are_isolated(self):
        with patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "deepseek-test", "OPENAI_API_KEY": "openai-test"},
            clear=True,
        ):
            settings = Settings.load(self.root, provider="deepseek")
        self.assertEqual(settings.provider, "deepseek")
        self.assertEqual(settings.api_key, "deepseek-test")
        self.assertEqual(settings.base_url, "https://api.deepseek.com")
        self.assertEqual(settings.model, "deepseek-v4-pro")

    def test_default_provider_does_not_require_openai(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings.load(self.root)
        self.assertEqual(settings.provider, "deepseek")
        self.assertIsNone(settings.api_key)

    def test_all_three_providers_are_available(self):
        self.assertEqual(get_provider("openai").transport, "responses")
        self.assertEqual(get_provider("deepseek").transport, "chat_completions")
        self.assertEqual(get_provider("kimi").base_url, "https://api.moonshot.cn/v1")

    def test_chat_provider_executes_tool_call_then_returns_text(self):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="list_project_files", arguments='{"pattern":"*","limit":3}'),
        )
        completions = FakeCompletions(
            [FakeMessage(tool_calls=[tool_call]), FakeMessage(content="检查完成")]
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "provider-audit")

        result = AgentRuntime(settings, registry, audit, client=client).run("检查工程")

        self.assertEqual(result, "检查完成")
        self.assertEqual(registry.calls[0][0], "list_project_files")
        self.assertEqual(completions.requests[1]["messages"][-1]["role"], "tool")

    def test_chat_provider_streams_text_events(self):
        chunks = [
            SimpleNamespace(
                id="stream-response",
                choices=[SimpleNamespace(delta=SimpleNamespace(content="流"), finish_reason=None)],
            ),
            SimpleNamespace(
                id="stream-response",
                choices=[SimpleNamespace(delta=SimpleNamespace(content="式"), finish_reason="stop")],
            ),
        ]
        completions = FakeStreamingCompletions([chunks])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "provider-stream-audit")

        events = list(AgentRuntime(settings, registry, audit, client=client).run_events("检查工程"))

        self.assertEqual([event["text"] for event in events if event["type"] == "delta"], ["流", "式"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["answer"], "流式")
        self.assertTrue(completions.requests[0]["stream"])

    def test_consecutive_reasoning_rounds_are_separated_by_blank_line(self):
        # Round 1: a thinking sentence + a tool call. Round 2: the final answer.
        round_one = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="我先查一下"), finish_reason=None)]),
            SimpleNamespace(
                id="r",
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            index=0,
                            id="call-1",
                            type="function",
                            function=SimpleNamespace(name="list_project_files", arguments='{"pattern":"*","limit":3}'),
                        )],
                    ),
                    finish_reason="tool_calls",
                )],
            ),
        ]
        round_two = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="查完了"), finish_reason="stop")]),
        ]
        completions = FakeStreamingCompletions([round_one, round_two])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "provider-rounds-audit")

        events = list(AgentRuntime(settings, registry, audit, client=client).run_events("做个 PPT"))
        deltas = [event["text"] for event in events if event["type"] == "delta"]
        # A blank line separates round 1's thinking from round 2's text.
        self.assertEqual(deltas, ["我先查一下", "\n\n", "查完了"])
        # The stored answer stays clean (no leading separator).
        self.assertEqual(events[-1]["answer"], "查完了")


if __name__ == "__main__":
    unittest.main()
