import unittest
from pathlib import Path
from unittest.mock import patch

from bnct_tps_agent.audit import AuditLogger
from bnct_tps_agent.safety import SafetyPolicy
from bnct_tps_agent.tool_registry import ToolRegistry
from bnct_tps_agent.web_search import (
    _proxy_maps,
    fetch_url,
    looks_sensitive_url,
    looks_sensitive_web_query,
    parse_bing_html,
    parse_duckduckgo_html,
    parse_duckduckgo_rss,
    web_search,
)


class FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        return self.body


HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpaper">BNCT latest review</a>
  <a class="result__snippet">A recent public summary of boron neutron capture therapy.</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.org/standard">BNCT standard</a>
  <div class="result__snippet">Guidance and release notes.</div>
</div>
</body></html>
"""

RSS = """
<rss><channel>
  <item>
    <title>前沿技术最新动态</title>
    <link>https://example.com/frontier-tech</link>
    <description>Latest public frontier technology update.</description>
  </item>
</channel></rss>
"""

BING = """
<html><body>
<li class="b_algo">
  <h2><a href="https://example.net/news">Frontier technology news</a></h2>
  <p>Fresh public news result.</p>
</li>
</body></html>
"""


class WebSearchTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def setUp(self):
        # Search results are TTL-cached in-process; tests must stay isolated.
        from bnct_tps_agent import web_search as ws
        ws._SEARCH_CACHE.clear()

    def test_duckduckgo_html_results_are_parsed(self):
        results = parse_duckduckgo_html(HTML, 3)
        self.assertEqual(results[0]["title"], "BNCT latest review")
        self.assertEqual(results[0]["url"], "https://example.com/paper")
        self.assertIn("boron neutron capture", results[0]["snippet"])
        self.assertEqual(results[1]["url"], "https://example.org/standard")

    def test_duckduckgo_rss_results_are_parsed(self):
        results = parse_duckduckgo_rss(RSS, 3)
        self.assertEqual(results[0]["title"], "前沿技术最新动态")
        self.assertEqual(results[0]["url"], "https://example.com/frontier-tech")

    def test_bing_html_results_are_parsed(self):
        results = parse_bing_html(BING, 3)
        self.assertEqual(results[0]["title"], "Frontier technology news")
        self.assertEqual(results[0]["snippet"], "Fresh public news result.")

    def test_sensitive_queries_are_detected(self):
        self.assertTrue(looks_sensitive_web_query(r"D:\wsr\secret\plan.py"))
        self.assertTrue(looks_sensitive_web_query("患者 姓名 张三 BNCT"))
        self.assertTrue(looks_sensitive_web_query("OPENAI_API_KEY sk-test1234567890"))
        self.assertFalse(looks_sensitive_web_query("latest BNCT dose calculation paper"))
        self.assertTrue(looks_sensitive_url("https://example.com/callback?access_token=abc"))
        self.assertFalse(looks_sensitive_url("https://github.com/example/repo"))

    def test_fetch_url_extracts_readable_text_and_links(self):
        html = """
        <html><head><title>Example Repo</title><script>secret()</script></head>
        <body><main><h1>HuChenFeng</h1><p>Readable project summary.</p>
        <a href="/example/repo/blob/main/README.md">README</a></main></body></html>
        """
        with patch("bnct_tps_agent.web_search._open_url", return_value=FakeResponse(html)):
            result = fetch_url(self.root, "https://github.com/example/repo", max_chars=200)
        self.assertEqual(result["url"], "https://github.com/example/repo")
        self.assertEqual(result["title"], "Example Repo")
        self.assertIn("Readable project summary", result["text"])
        self.assertNotIn("secret()", result["text"])
        self.assertEqual(result["links"][0]["url"], "https://github.com/example/repo/blob/main/README.md")

    def test_fetch_url_blocks_local_addresses(self):
        with self.assertRaises(ValueError):
            fetch_url(self.root, "http://127.0.0.1:8765/api/config")

    def test_web_search_uses_fetcher_and_returns_bounded_results(self):
        with patch("bnct_tps_agent.web_search._open_url", return_value=FakeResponse(HTML)):
            result = web_search(self.root, "latest BNCT paper", max_results=1)
        self.assertEqual(result["source"], "duckduckgo-html")
        self.assertEqual(result["network"], "auto")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.com/paper")

    def test_web_search_direct_network_bypasses_proxy_candidates(self):
        self.assertEqual(_proxy_maps("direct"), [{}])
        self.assertNotIn({}, _proxy_maps("system"))
        with patch("bnct_tps_agent.web_search._open_url", return_value=FakeResponse(HTML)) as open_url:
            result = web_search(self.root, "latest BNCT paper", max_results=1, network="direct")
        self.assertEqual(result["network"], "direct")
        self.assertEqual(open_url.call_args.kwargs["network"], "direct")

    def test_web_search_falls_back_when_first_source_is_empty(self):
        # recency=True consults news feeds first (bing-news-rss, then google-news-rss).
        with patch("bnct_tps_agent.web_search._open_url", side_effect=[FakeResponse("<html></html>"), FakeResponse(RSS)]):
            result = web_search(self.root, "前沿技术最新动态", max_results=2, recency=True)
        self.assertEqual(result["source"], "google-news-rss")
        self.assertTrue(result["recency"])
        self.assertEqual(result["results"][0]["url"], "https://example.com/frontier-tech")

    def test_web_search_query_is_not_split_into_fragments(self):
        # A natural-language CJK question must reach the engine verbatim.
        bing_relevant = """
        <html><body>
        <li class="b_algo">
          <h2><a href="https://example.net/bnct">硼中子俘获治疗临床进展综述</a></h2>
          <p>最新临床研究与试验进展。</p>
        </li>
        </body></html>
        """
        with patch("bnct_tps_agent.web_search._fetch_text", return_value=bing_relevant) as fetch_text:
            result = web_search(self.root, "硼中子俘获治疗的最新临床进展是什么", max_results=3)
        # First source consulted is bing-html with the full query in the URL.
        first_url = fetch_text.call_args_list[0].args[0]
        self.assertIn("bing.com/search", first_url)
        self.assertEqual(result["source"], "bing-html")
        self.assertEqual(result["results"][0]["url"], "https://example.net/bnct")

    def test_anti_bot_garbage_results_are_treated_as_channel_failure(self):
        # A blocked engine often "answers" with unrelated cards (restaurants,
        # appliances, weather). Sharing zero material with the query must count
        # as an ENGINE failure with explicit diagnostics -- never as success.
        garbage = """
        <html><body>
        <li class="b_algo"><h2><a href="https://example.com/food">城中十家人气餐厅推荐</a></h2><p>美食攻略。</p></li>
        <li class="b_algo"><h2><a href="https://example.com/wash">滚筒洗衣机选购指南</a></h2><p>家电评测。</p></li>
        </body></html>
        """
        with patch("bnct_tps_agent.web_search._fetch_text", return_value=garbage):
            result = web_search(self.root, "BNCT GPU 蒙特卡罗剂量计算 加速算法", max_results=3)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["source"], "none")
        self.assertTrue(any(d["errorType"] == "IrrelevantResults" for d in result["diagnostics"]))
        # The tool tells the model to report honestly instead of retry-looping.
        self.assertIn("不要反复更换关键词", result["message"])

    def test_mixed_language_results_pass_the_relevance_gate(self):
        # A Chinese query answered by English results still passes when the
        # query's latin tokens (BNCT, GPU) appear -- the gate must be lenient.
        english = """
        <html><body>
        <li class="b_algo"><h2><a href="https://example.com/gmcc">GPU-accelerated Monte Carlo for BNCT dose</a></h2><p>Nuclear engineering paper.</p></li>
        </body></html>
        """
        with patch("bnct_tps_agent.web_search._fetch_text", return_value=english):
            result = web_search(self.root, "BNCT 和 GPU 相结合的应用算法", max_results=3)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["source"], "bing-html")

    def test_successful_searches_are_cached(self):
        with patch("bnct_tps_agent.web_search._open_url", return_value=FakeResponse(HTML)) as open_url:
            first = web_search(self.root, "latest BNCT paper cached", max_results=1)
            calls_after_first = open_url.call_count
            second = web_search(self.root, "latest BNCT paper cached", max_results=1)
        self.assertEqual(open_url.call_count, calls_after_first)
        self.assertNotIn("cached", first)
        self.assertTrue(second["cached"])
        self.assertEqual(second["results"], first["results"])

    def test_search_self_test_reports_per_channel_verdicts(self):
        from bnct_tps_agent.web_search import search_self_test

        relevant = """
        <html><body>
        <li class="b_algo"><h2><a href="https://example.com/bnct">Boron neutron capture therapy overview</a></h2><p>BNCT basics.</p></li>
        </body></html>
        """

        def fake_fetch(url, timeout=8, network="auto"):
            if "bing.com/search" in url:
                return relevant
            raise OSError("blocked")

        with patch("bnct_tps_agent.web_search._fetch_text", side_effect=fake_fetch):
            report = search_self_test(network="auto")
        self.assertTrue(report["healthy"])
        by_channel = {check["channel"]: check for check in report["checks"]}
        self.assertTrue(by_channel["bing-html"]["ok"])
        self.assertFalse(by_channel["duckduckgo-html"]["ok"])
        self.assertIn("无法访问", by_channel["duckduckgo-html"]["detail"])

    def test_search_api_provider_is_used_when_configured(self):
        bocha_payload = {
            "data": {"webPages": {"value": [
                {"name": "峰哥亡命天涯 - 户外UP主", "url": "https://example.com/fengge", "summary": "知名户外探险UP主介绍"},
            ]}}
        }
        import json as jsonlib

        class FakeJsonResponse:
            def __init__(self, payload):
                self.body = jsonlib.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return self.body

        with patch("bnct_tps_agent.web_search._open_url", return_value=FakeJsonResponse(bocha_payload)):
            result = web_search(
                self.root, "峰哥亡命天涯是谁", max_results=3,
                search_provider="bocha", search_api_key="test-key",
            )
        self.assertEqual(result["source"], "api:bocha")
        self.assertEqual(result["results"][0]["url"], "https://example.com/fengge")

    def test_search_api_failure_falls_back_to_scraping(self):
        # First call (API) raises, subsequent scraping calls return usable HTML.
        responses = [OSError("api down"), FakeResponse(HTML), FakeResponse(HTML), FakeResponse(HTML)]

        def fake_open(*_args, **_kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("bnct_tps_agent.web_search._open_url", side_effect=fake_open):
            result = web_search(
                self.root, "latest BNCT paper", max_results=1,
                search_provider="tavily", search_api_key="k",
            )
        self.assertTrue(result["results"])
        self.assertNotEqual(result["source"], "api:tavily")

    def test_tool_registry_hides_search_when_disabled(self):
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(),
            AuditLogger(self.root / "tests" / "runtime_output" / "web-search-off-audit"),
            web_search_mode="off",
        )
        self.assertNotIn("web_search", {schema["name"] for schema in registry.schemas})
        self.assertNotIn("fetch_url", {schema["name"] for schema in registry.schemas})

    def test_tool_registry_exposes_fetch_url_when_web_is_enabled(self):
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(),
            AuditLogger(self.root / "tests" / "runtime_output" / "fetch-url-audit"),
            web_search_mode="auto",
        )
        self.assertIn("fetch_url", {schema["name"] for schema in registry.schemas})

    def test_local_web_search_stays_as_fallback_beside_builtin(self):
        # Capability must never depend on the model recognizing the exotic
        # $web_search builtin declaration: with search enabled, a tool named
        # web_search is ALWAYS in the list (described as the fallback), so the
        # model can never truthfully claim it lacks web search.
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(),
            AuditLogger(self.root / "tests" / "runtime_output" / "builtin-search-registry-audit"),
            web_search_mode="auto",
            builtin_search=True,
        )
        names = {schema["name"] for schema in registry.schemas}
        self.assertIn("web_search", names)
        self.assertIn("fetch_url", names)
        description = next(s for s in registry.schemas if s["name"] == "web_search")["description"]
        self.assertIn("$web_search", description)
        self.assertIn("fallback", description)

    def test_sensitive_auto_search_requires_approval(self):
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(),
            AuditLogger(self.root / "tests" / "runtime_output" / "web-search-sensitive-audit"),
            web_search_mode="auto",
        )
        result = registry.execute("web_search", {"query": r"D:\internal\case", "max_results": 3})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "PolicyDenied")


if __name__ == "__main__":
    unittest.main()
