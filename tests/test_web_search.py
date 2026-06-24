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
        with patch("bnct_tps_agent.web_search._open_url", side_effect=[FakeResponse("<html></html>"), FakeResponse(RSS)]):
            result = web_search(self.root, "前沿技术最新动态", max_results=2)
        self.assertEqual(result["source"], "bing-news-rss")
        self.assertEqual(result["results"][0]["url"], "https://example.com/frontier-tech")

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
