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
    chat_schemas = [
        {"type": "function", "function": {"name": "list_project_files"}},
        {"type": "function", "function": {"name": "web_search"}},
    ]
    # The agent reads the LIVE web-search state from the registry (the quick
    # toggle flips it there without rebuilding runtimes).
    web_search_mode = "auto"
    web_search_network = "auto"

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
        # The vision model is a different family: no builtin search tool and no
        # thinking flag it may not support.
        self.assertNotIn("extra_body", request)
        self.assertNotIn(
            {"type": "builtin_function", "function": {"name": "$web_search"}},
            request["tools"],
        )
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

    def test_system_message_carries_current_date_every_run(self):
        # Without the real date the model's internal clock (training cutoff)
        # decides "that event has not happened yet" and skips searching.
        chunks_a = [SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="好"), finish_reason="stop")])]
        chunks_b = [SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="好"), finish_reason="stop")])]
        completions = FakeStreamingCompletions([chunks_a, chunks_b])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="kimi", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "date-audit")
        runtime = AgentRuntime(settings, registry, audit, client=client)

        import time as _time
        list(runtime.run_events("你好"))
        system_message = completions.requests[0]["messages"][0]
        self.assertEqual(system_message["role"], "system")
        self.assertIn(_time.strftime("%Y-%m-%d"), system_message["content"])
        self.assertIn("training data has a cutoff", system_message["content"])
        # Kimi runs must be told, in plain words, that they HAVE web search
        # (builtin preferred, local fallback) -- otherwise the model looks at
        # the exotic $web_search declaration and denies having search at all.
        self.assertIn("you HAVE it", system_message["content"])
        self.assertIn("$web_search", system_message["content"])
        self.assertIn("NEVER tell the user you lack web search", system_message["content"])
        # A cached runtime must refresh the date on the NEXT run too (sessions
        # stay cached across midnight): simulate staleness and re-run.
        runtime.messages[0] = {"role": "system", "content": "STALE"}
        list(runtime.run_events("再来"))
        self.assertIn(_time.strftime("%Y-%m-%d"), completions.requests[1]["messages"][0]["content"])

    @staticmethod
    def _tool_call_round(name, arguments, call_type="function", call_id="call-1"):
        return [
            SimpleNamespace(
                id="r",
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            index=0,
                            id=call_id,
                            type=call_type,
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )],
                    ),
                    finish_reason="tool_calls",
                )],
            ),
        ]

    def test_kimi_search_phase_pauses_thinking_then_restores_it(self):
        # Deep thinking is the default. Round 1: the model asks to search via
        # the local web_search -> the run enters the search phase (thinking
        # paused, builtin enabled) WITHOUT running the poor local scraper.
        # Round 2: the model redoes the query with $web_search -> echo the
        # arguments verbatim (Moonshot contract). Round 3: a non-search tool
        # round ends the gathering -> thinking restored. Round 4: final text.
        rounds = [
            self._tool_call_round("web_search", '{"query":"户晨风 街头采访","max_results":5,"recency":true}'),
            self._tool_call_round("$web_search", '{"search_id":"abc"}', call_type="builtin_function", call_id="call-ws"),
            self._tool_call_round("list_project_files", '{"pattern":"*","limit":3}', call_id="call-fs"),
            [SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="搜到了"), finish_reason="stop")])],
        ]
        completions = FakeStreamingCompletions(rounds)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        settings = Settings.load(self.root, provider="kimi", api_key="test-key")
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "builtin-search-audit")

        events = list(AgentRuntime(settings, registry, audit, client=client).run_events("调研户晨风"))
        self.assertEqual(events[-1]["answer"], "搜到了")

        builtin_decl = {"type": "builtin_function", "function": {"name": "$web_search"}}
        # Round 1 request: thinking ON (no extra_body), no builtin offered.
        self.assertNotIn("extra_body", completions.requests[0])
        self.assertNotIn(builtin_decl, completions.requests[0]["tools"])
        # The web_search call was intercepted as the phase switch, not scraped.
        self.assertEqual(registry.calls, [("list_project_files", {"pattern": "*", "limit": 3})])
        redirect = completions.requests[1]["messages"][-1]
        self.assertEqual(redirect["role"], "tool")
        self.assertIn("$web_search", redirect["content"])
        # Rounds 2-3 requests: search phase -> thinking paused, builtin offered,
        # and the poor local scraper is OFF the table so the model cannot loop
        # on garbage results instead of using the provider search.
        local_decl = {"type": "function", "function": {"name": "web_search"}}
        for index in (1, 2):
            self.assertEqual(completions.requests[index]["extra_body"], {"thinking": {"type": "disabled"}})
            self.assertIn(builtin_decl, completions.requests[index]["tools"])
            self.assertNotIn(local_decl, completions.requests[index]["tools"])
        # The $web_search echo went back verbatim.
        echo = completions.requests[2]["messages"][-1]
        self.assertEqual(echo["content"], '{"search_id":"abc"}')
        # Round 4 request: gathering ended (round 3 had no search calls) ->
        # thinking restored, builtin withdrawn, local web_search back in place.
        self.assertNotIn("extra_body", completions.requests[3])
        self.assertNotIn(builtin_decl, completions.requests[3]["tools"])
        self.assertIn(local_decl, completions.requests[3]["tools"])
        # Phase transitions surfaced as activity events for the UI.
        labels = [event.get("label", "") for event in events if event.get("type") == "activity"]
        self.assertTrue(any("暂停深度思考" in label for label in labels))
        self.assertTrue(any("恢复深度思考" in label for label in labels))

    def test_builtin_search_not_offered_when_search_disabled_or_unsupported(self):
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "builtin-flag-audit")
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeStreamingCompletions([])))
        # The live toggle flips the mode on the REGISTRY; the agent reads it
        # from there, so a cached runtime honors the switch immediately.
        registry_off = FakeRegistry()
        registry_off.web_search_mode = "off"
        kimi = Settings.load(self.root, provider="kimi", api_key="k")
        self.assertEqual(
            AgentRuntime(kimi, registry_off, audit, client=client)._chat_tools(),
            registry_off.chat_schemas,
        )
        registry_on = FakeRegistry()
        deepseek = Settings.load(self.root, provider="deepseek", api_key="d")
        self.assertEqual(
            AgentRuntime(deepseek, registry_on, audit, client=client)._chat_tools(),
            registry_on.chat_schemas,
        )

    def test_step_budget_pauses_gracefully_and_can_continue(self):
        # Long agentic skills hit the per-turn round budget mid-flight. That
        # must PAUSE the run (progress + conversation state kept, user replies
        # 继续) -- never raise and discard everything as a failure.
        def tool_round():
            return [SimpleNamespace(
                id="r",
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            index=0,
                            id="call-x",
                            type="function",
                            function=SimpleNamespace(name="list_project_files", arguments='{"pattern":"*","limit":3}'),
                        )],
                    ),
                    finish_reason="tool_calls",
                )],
            )]

        with patch.dict("os.environ", {"BNCT_AGENT_MAX_STEPS": "2"}, clear=False):
            settings = Settings.load(self.root, provider="deepseek", api_key="test-key")
        final_round = [
            SimpleNamespace(id="r", choices=[SimpleNamespace(delta=SimpleNamespace(content="继续完成了"), finish_reason="stop")]),
        ]
        completions = FakeStreamingCompletions([tool_round(), tool_round(), final_round])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = FakeRegistry()
        audit = AuditLogger(self.root / "tests" / "runtime_output" / "budget-audit")
        runtime = AgentRuntime(settings, registry, audit, client=client)

        events = list(runtime.run_events("做一个超长的调研"))
        answer = events[-1]["answer"]
        self.assertIn("暂停", answer)
        self.assertIn("继续", answer)
        # The transcript stays consistent: the pause is a normal assistant turn.
        self.assertEqual(runtime.messages[-1]["role"], "assistant")
        self.assertIn("暂停", runtime.messages[-1]["content"])
        # Two tool rounds actually ran before pausing.
        self.assertEqual(len(registry.calls), 2)
        # And the conversation can resume in the same runtime.
        events = list(runtime.run_events("继续"))
        self.assertEqual(events[-1]["answer"], "继续完成了")

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
