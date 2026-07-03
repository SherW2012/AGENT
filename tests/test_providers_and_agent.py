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

    def test_provider_vision_capabilities(self):
        self.assertEqual(get_provider("openai").vision, "native")
        self.assertEqual(get_provider("deepseek").vision, "none")
        kimi = get_provider("kimi")
        self.assertEqual(kimi.vision, "switch")
        self.assertTrue(kimi.resolve_vision_model())
        with patch.dict("os.environ", {"KIMI_VISION_MODEL": "custom-vision"}, clear=False):
            self.assertEqual(kimi.resolve_vision_model(), "custom-vision")

    def test_image_turns_route_to_the_vision_model(self):
        chunks = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="图里写着测试"), finish_reason="stop")]),
        ]
        completions = FakeStreamingCompletions([chunks])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="kimi", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "vision-audit")

        image = "data:image/png;base64,aGVsbG8="
        events = list(AgentRuntime(settings, registry, audit, client=client).run_events("图里写了什么", images=[image]))

        self.assertEqual(events[-1]["answer"], "图里写着测试")
        request = completions.requests[0]
        # Same API key, but the request auto-routes to the provider's vision model.
        self.assertEqual(request["model"], "moonshot-v1-32k-vision-preview")
        user_message = request["messages"][-1]
        self.assertIsInstance(user_message["content"], list)
        kinds = {part["type"] for part in user_message["content"]}
        self.assertEqual(kinds, {"text", "image_url"})

    def test_text_only_provider_gets_note_instead_of_image_blocks(self):
        chunks = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="收到"), finish_reason="stop")]),
        ]
        completions = FakeStreamingCompletions([chunks])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "vision-none-audit")

        list(AgentRuntime(settings, registry, audit, client=client).run_events(
            "图里写了什么", images=["data:image/png;base64,aGVsbG8="]
        ))
        request = completions.requests[0]
        self.assertEqual(request["model"], "deepseek-v4-pro")
        user_message = request["messages"][-1]
        self.assertIsInstance(user_message["content"], str)
        self.assertIn("不支持图片输入", user_message["content"])

    def test_vision_failure_falls_back_to_text_model_with_notice(self):
        class FlakyCompletions:
            def __init__(self, chunks):
                self.chunks = chunks
                self.requests = []
                self.calls = 0

            def create(self, **request):
                self.requests.append(request)
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("model not found: vision")
                return iter(self.chunks)

        chunks = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="退回文本模型"), finish_reason="stop")]),
        ]
        completions = FlakyCompletions(chunks)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="kimi", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "vision-fallback-audit")

        events = list(AgentRuntime(settings, registry, audit, client=client).run_events(
            "图里写了什么", images=["data:image/png;base64,aGVsbG8="]
        ))
        notices = [event for event in events if event["type"] == "notice"]
        self.assertTrue(notices)
        self.assertEqual(events[-1]["answer"], "退回文本模型")
        # Retry dropped the image blocks and returned to the configured model.
        self.assertEqual(completions.requests[1]["model"], "kimi-k2.6")
        self.assertIsInstance(completions.requests[1]["messages"][-1]["content"], str)

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

    def test_stream_usage_is_reported_in_done_event(self):
        chunks = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="好的"), finish_reason="stop")]),
            SimpleNamespace(id="r", choices=[], usage=SimpleNamespace(prompt_tokens=120, completion_tokens=45)),
        ]
        completions = FakeStreamingCompletions([chunks])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "usage-audit")

        events = list(AgentRuntime(settings, registry, audit, client=client).run_events("你好"))
        done = events[-1]
        self.assertEqual(done["usage"], {"promptTokens": 120, "completionTokens": 45})
        self.assertTrue(completions.requests[0]["stream_options"]["include_usage"])

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

    def test_mid_task_steering_is_injected_before_next_round(self):
        round_one = [
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
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="收到"), finish_reason="stop")]),
        ]
        completions = FakeStreamingCompletions([round_one, round_two])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "provider-steer-audit")

        queue = ["顺便只看 src 目录"]

        def pop_steering():
            items, queue[:] = list(queue), []
            return items

        # Steering queued before round 2 must appear in round 2's request messages.
        events = list(
            AgentRuntime(settings, registry, audit, client=client).run_events(
                "检查工程", pop_steering=pop_steering
            )
        )
        self.assertEqual(events[-1]["answer"], "收到")
        second_request_messages = completions.requests[1]["messages"]
        steer_texts = [m["content"] for m in second_request_messages if m.get("role") == "user"]
        self.assertTrue(any("顺便只看 src 目录" in str(text) for text in steer_texts))


if __name__ == "__main__":
    unittest.main()
