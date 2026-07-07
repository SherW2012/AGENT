from __future__ import annotations

import json
import os
import base64
import ipaddress
import re
import socket
import time
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote_plus, urlencode, urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener, getproxies


DEFAULT_MAX_RESULTS = 5
MAX_MAX_RESULTS = 8
MAX_QUERY_CHARS = 320
DEFAULT_FETCH_CHARS = 40_000
MAX_FETCH_CHARS = 80_000
MAX_FETCH_URL_CHARS = 2048
WEB_SEARCH_NETWORKS = {"auto", "direct", "system"}
# Real search APIs (configured with the user's own key) come first; the free
# scraping backends remain as the zero-config fallback.
SEARCH_API_PROVIDERS = {"none", "bocha", "tavily", "brave"}

# NOTE: Recency / time-sensitivity is decided by the model via the web_search
# tool's `recency` argument, NOT by a hardcoded keyword whitelist. Different
# users phrase "I want the latest information" in countless ways, so judging it
# in code with a fixed term list is both brittle and wrong. The model reads the
# question and sets recency=True when fresh sources are warranted.
#
# The query itself is always sent to the search engine verbatim as a natural
# language string. We never tokenize it into single characters; the engine's
# own ranking decides relevance. Bing is the primary backend because it handles
# Chinese (and other non-Latin) natural-language queries well and is reachable
# without a VPN; DuckDuckGo is only a fallback.

# These patterns are a privacy guardrail (keep secrets / patient identifiers out
# of outbound queries), which is a deliberate safety boundary -- not a heuristic
# for guessing user intent.
SENSITIVE_QUERY_PATTERNS = [
    re.compile(r"\b[A-Za-z]:\\"),
    re.compile(r"\\\\[A-Za-z0-9_.-]+\\"),
    re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|api[_ -]?key|secret|token|password|bearer)\b"),
    re.compile(r"(?i)\b(?:patient|mrn|medical record|accession number|dicom uid)\b"),
    re.compile(r"\b(?:10\.|127\.|192\.168\.|172\.(?:1[6-9]|2\d|3[0-1])\.)"),
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"(患者|姓名|身份证|住院号|病历号|病案号|手机号|出生日期|床号|检查号|影像号)"),
]
SENSITIVE_URL_PARAM_RE = re.compile(
    r"(?i)(?:[?&](?:api[_-]?key|access[_-]?token|auth|signature|sig|secret|password|token|x-amz-signature)=)"
)


def looks_sensitive_web_query(query: str) -> bool:
    text = str(query)
    return any(pattern.search(text) for pattern in SENSITIVE_QUERY_PATTERNS)


def looks_sensitive_url(url: str) -> bool:
    text = str(url)
    return looks_sensitive_web_query(text) or bool(SENSITIVE_URL_PARAM_RE.search(text))


def _validate_public_fetch_url(url: str) -> str:
    clean_url = str(url or "").strip()
    if not clean_url:
        raise ValueError("fetch_url url cannot be empty")
    if len(clean_url) > MAX_FETCH_URL_CHARS:
        raise ValueError(f"fetch_url url is too long; keep it under {MAX_FETCH_URL_CHARS} characters")
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("fetch_url only supports public http and https URLs")
    if parsed.username or parsed.password:
        raise ValueError("fetch_url does not allow credentials embedded in URLs")
    host = parsed.hostname
    if not host:
        raise ValueError("fetch_url URL must include a host")
    lowered_host = host.lower().strip("[]")
    if lowered_host in {"localhost", "local"} or lowered_host.endswith((".localhost", ".local")):
        raise ValueError("fetch_url blocks local hostnames")
    try:
        address = ipaddress.ip_address(lowered_host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("fetch_url blocks private, local, and reserved IP addresses")
    return clean_url


def _strip_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _normalize_duckduckgo_url(value: str) -> str:
    url = unescape(value).strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return url


def _normalize_bing_url(value: str) -> str:
    url = unescape(value).strip()
    parsed = urlparse(url)
    if "bing.com" not in parsed.netloc or not parsed.path.startswith("/ck/"):
        return url
    encoded = parse_qs(parsed.query).get("u", [""])[0]
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    if not encoded:
        return url
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, OSError):
        return url
    return decoded if decoded.startswith(("http://", "https://")) else url


def parse_duckduckgo_html(html: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.split(r'<div[^>]+class="[^"]*\bresult\b[^"]*"', html)
    for block in blocks[1:]:
        link = re.search(
            r'<a[^>]+class="[^"]*\bresult__a\b[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not link:
            continue
        snippet_match = re.search(
            r'<(?:a|div)[^>]+class="[^"]*\bresult__snippet\b[^"]*"[^>]*>(.*?)</(?:a|div)>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        url = _normalize_duckduckgo_url(link.group(1))
        title = _strip_tags(link.group(2))
        snippet = _strip_tags(snippet_match.group(1)) if snippet_match else ""
        if not title or not url:
            continue
        if any(item["url"] == url for item in results):
            continue
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def parse_duckduckgo_rss(xml_text: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return results
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        snippet = _strip_tags(item.findtext("description") or "")
        if title and url and not any(result["url"] == url for result in results):
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def parse_bing_html(html: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.split(r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"', html)
    for block in blocks[1:]:
        link = re.search(r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*</h2>", block, re.IGNORECASE | re.DOTALL)
        if not link:
            continue
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.IGNORECASE | re.DOTALL)
        title = _strip_tags(link.group(2))
        url = _normalize_bing_url(link.group(1))
        snippet = _strip_tags(snippet_match.group(1)) if snippet_match else ""
        if title and url and not any(result["url"] == url for result in results):
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _windows_proxy_server() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return None
    if not enabled or not server:
        return None
    parts = [part.strip() for part in str(server).split(";") if part.strip()]
    for part in parts:
        if "=" in part:
            scheme, address = part.split("=", 1)
            if scheme.lower() in {"http", "https"}:
                server = address
                break
        else:
            server = part
            break
    server = str(server).strip()
    if not server:
        return None
    if not re.match(r"^[a-z]+://", server, re.IGNORECASE):
        server = "http://" + server
    return server


def _loopback_proxy_is_listening(proxy_url: str) -> bool:
    parsed = urlparse(proxy_url)
    host = parsed.hostname
    port = parsed.port
    if host not in {"127.0.0.1", "localhost", "::1"} or port is None:
        return True
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _valid_proxy_map(proxies: dict[str, str]) -> dict[str, str]:
    result = {key: value for key, value in proxies.items() if key in {"http", "https"} and value}
    return {key: value for key, value in result.items() if _loopback_proxy_is_listening(value)}


def _proxy_label(proxies: dict[str, str]) -> str:
    return "direct" if not proxies else ",".join(sorted(set(proxies.values())))


def _proxy_maps(network: str = "auto") -> list[dict[str, str]]:
    network = str(network or "auto").strip().lower()
    if network not in WEB_SEARCH_NETWORKS:
        network = "auto"
    if network == "direct":
        return [{}]

    candidates: list[dict[str, str]] = []
    env_proxies = _valid_proxy_map(getproxies())
    if env_proxies:
        candidates.append(env_proxies)
    windows_proxy = _windows_proxy_server()
    if windows_proxy and _loopback_proxy_is_listening(windows_proxy):
        windows_map = {"http": windows_proxy, "https": windows_proxy}
        if windows_map not in candidates:
            candidates.append(windows_map)
    if network == "auto":
        candidates.append({})
    return candidates


def _proxy_map() -> dict[str, str]:
    return _proxy_maps()[0]


def _open_url(request: Request, timeout: float, network: str = "auto"):
    errors = []
    for proxies in _proxy_maps(network):
        opener = build_opener(ProxyHandler(proxies))
        try:
            return opener.open(request, timeout=timeout)
        except HTTPError as exc:
            label = _proxy_label(proxies)
            hint = ""
            if exc.code == 410 and any("127.0.0.1" in value or "localhost" in value for value in proxies.values()):
                hint = " (local proxy returned 410; try web search network=direct)"
            errors.append(f"{label}: HTTP {exc.code}{hint}")
        except OSError as exc:
            errors.append(f"{_proxy_label(proxies)}: {exc}")
    raise TimeoutError("; ".join(errors))


def _fetch_text(url: str, timeout: float = 12, network: str = "auto") -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BNCT-TPS-Agent/0.1",
            "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with _open_url(request, timeout=timeout, network=network) as response:
        headers = getattr(response, "headers", None)
        charset = headers.get_content_charset() if headers is not None else None
        charset = charset or "utf-8"
        return response.read(1_500_000).decode(charset, errors="replace")


def _html_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return _strip_tags(match.group(1)) if match else ""


def _html_to_readable_text(html: str) -> str:
    cleaned = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    return _strip_tags(cleaned)


def _extract_links(html: str, base_url: str, limit: int = 24) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"<a\b[^>]*\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        href = unescape(match.group(2)).strip()
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or absolute in seen:
            continue
        text = _strip_tags(match.group(3)) or parsed.path.rsplit("/", 1)[-1] or parsed.netloc
        if not text:
            continue
        seen.add(absolute)
        links.append({"text": text[:160], "url": absolute})
        if len(links) >= limit:
            break
    return links


def fetch_url(_root: Path, url: str, max_chars: int = DEFAULT_FETCH_CHARS, network: str = "auto") -> dict[str, Any]:
    clean_url = _validate_public_fetch_url(url)
    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = DEFAULT_FETCH_CHARS
    limit = min(max(limit, 1_000), MAX_FETCH_CHARS)
    network = str(network or "auto").strip().lower()
    if network not in WEB_SEARCH_NETWORKS:
        network = "auto"

    request = Request(
        clean_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BNCT-TPS-Agent/0.1",
            "Accept": "text/html,application/xhtml+xml,text/plain,text/markdown,application/json,application/xml;q=0.9,*/*;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    # Fail fast: blocked/slow pages (common for overseas sites reached from a
    # CN network) should time out quickly so the model moves to another source
    # instead of stalling the run.
    with _open_url(request, timeout=10, network=network) as response:
        headers = getattr(response, "headers", None)
        content_type = headers.get("Content-Type", "") if headers is not None else ""
        charset = headers.get_content_charset() if headers is not None else None
        charset = charset or "utf-8"
        raw = response.read(1_500_000)
        final_url = getattr(response, "url", clean_url)
        status = int(getattr(response, "status", getattr(response, "code", 200)) or 200)

    text = raw.decode(charset, errors="replace")
    is_html = "html" in content_type.lower() or re.search(r"<html[\s>]", text[:600], re.IGNORECASE)
    title = _html_title(text) if is_html else ""
    readable = _html_to_readable_text(text) if is_html else re.sub(r"\s+\n", "\n", text).strip()
    truncated = len(readable) > limit
    if truncated:
        readable = readable[:limit] + "\n...[content truncated]"

    return {
        "url": clean_url,
        "finalUrl": final_url,
        "status": status,
        "contentType": content_type,
        "title": title,
        "text": readable,
        "links": _extract_links(text, final_url) if is_html else [],
        "chars": len(readable),
        "truncated": truncated,
        "network": network,
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _search_sources(query: str, recency: bool) -> list[tuple[str, str]]:
    """Return ordered (source_id, url) pairs for the verbatim query.

    The query is passed to each engine unchanged. Bing leads because it handles
    natural-language and CJK queries far better than DuckDuckGo's HTML endpoint
    and is reachable without a VPN. News/RSS feeds are only consulted first when
    the model flagged the question as time-sensitive (recency=True)."""
    encoded = urlencode({"q": query})
    plus_query = quote_plus(query)
    sources: list[tuple[str, str]] = []
    if recency:
        sources.extend(
            [
                ("bing-news-rss", f"https://www.bing.com/news/search?q={plus_query}&format=rss"),
                (
                    "google-news-rss",
                    "https://news.google.com/rss/search?"
                    + urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}),
                ),
            ]
        )
    sources.extend(
        [
            ("bing-html", f"https://www.bing.com/search?q={plus_query}&setlang=zh-CN"),
            ("duckduckgo-html", "https://duckduckgo.com/html/?" + encoded),
            ("duckduckgo-rss", "https://duckduckgo.com/rss/?" + encoded),
        ]
    )
    return sources


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    network: str = "auto",
) -> Any:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json", "User-Agent": "BNCT-TPS-Agent/0.1"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = Request(url, data=payload, headers=request_headers, method=method)
    with _open_url(request, timeout=14, network=network) as response:
        return json.loads(response.read(1_500_000).decode("utf-8", errors="replace"))


def _search_via_api(
    provider: str,
    api_key: str,
    query: str,
    limit: int,
    recency: bool,
    network: str,
) -> list[dict[str, str]]:
    """Query a proper search API. Each provider gets the query verbatim as
    natural language — no tokenizing, same principle as the scraping path."""
    results: list[dict[str, str]] = []
    if provider == "bocha":
        payload = _http_json(
            "https://api.bochaai.com/v1/web-search",
            method="POST",
            headers={"Authorization": f"Bearer {api_key}"},
            body={
                "query": query,
                "count": limit,
                "freshness": "oneMonth" if recency else "noLimit",
                "summary": True,
            },
            network=network,
        )
        for item in (((payload.get("data") or {}).get("webPages") or {}).get("value") or [])[:limit]:
            results.append({
                "title": str(item.get("name") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("summary") or item.get("snippet") or ""),
            })
    elif provider == "tavily":
        payload = _http_json(
            "https://api.tavily.com/search",
            method="POST",
            body={
                "api_key": api_key,
                "query": query,
                "max_results": limit,
                "topic": "news" if recency else "general",
            },
            network=network,
        )
        for item in (payload.get("results") or [])[:limit]:
            results.append({
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or ""),
            })
    elif provider == "brave":
        params = {"q": query, "count": str(limit)}
        if recency:
            params["freshness"] = "pw"
        payload = _http_json(
            "https://api.search.brave.com/res/v1/web/search?" + urlencode(params),
            headers={"X-Subscription-Token": api_key},
            network=network,
        )
        for item in (((payload.get("web") or {}).get("results")) or [])[:limit]:
            results.append({
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("description") or ""),
            })
    return [item for item in results if item["title"] and item["url"]]


def _parse_results(source: str, body: str, limit: int) -> list[dict[str, str]]:
    if source in {"duckduckgo-rss", "google-news-rss", "bing-news-rss"}:
        return parse_duckduckgo_rss(body, limit)
    if source == "bing-html":
        return parse_bing_html(body, limit)
    return parse_duckduckgo_html(body, limit)


_CJK_RUN_RE = re.compile(r"[一-鿿]+")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+-]{1,}")


def _query_evidence(query: str) -> tuple[set[str], set[str]]:
    """Deterministic evidence tokens for the relevance gate: latin words and
    CJK character bigrams from the query. This is NOT intent guessing -- it is
    a quality boundary, like the sensitive-content patterns: results that share
    zero material with the query are anti-bot/consent-page garbage, and passing
    them to the model as \"search results\" sends it into retry spirals."""
    lowered = str(query).lower()
    latin = set(_LATIN_TOKEN_RE.findall(lowered))
    bigrams: set[str] = set()
    for run in _CJK_RUN_RE.findall(lowered):
        if len(run) == 1:
            bigrams.add(run)
        for index in range(len(run) - 1):
            bigrams.add(run[index : index + 2])
    return latin, bigrams


def _result_supported_by_query(result: dict[str, str], latin: set[str], bigrams: set[str]) -> bool:
    if not latin and not bigrams:
        return True
    text = f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}".lower()
    if any(token in text for token in latin):
        return True
    return any(bigram in text for bigram in bigrams)


def _filter_relevant(results: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    latin, bigrams = _query_evidence(query)
    return [item for item in results if _result_supported_by_query(item, latin, bigrams)]


# Small in-process TTL cache: repeated/near-retry searches (the model often
# re-queries mid-task) must not hammer the engines or trip anti-bot faster.
_SEARCH_CACHE: dict[tuple[str, bool, int], tuple[float, dict[str, Any]]] = {}
_SEARCH_CACHE_TTL_SECONDS = 900
_SEARCH_CACHE_MAX_ENTRIES = 32


def _cache_get(key: tuple[str, bool, int]) -> dict[str, Any] | None:
    entry = _SEARCH_CACHE.get(key)
    if entry is None or time.time() - entry[0] > _SEARCH_CACHE_TTL_SECONDS:
        return None
    return {**entry[1], "cached": True}


def _cache_put(key: tuple[str, bool, int], payload: dict[str, Any]) -> None:
    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX_ENTRIES:
        oldest = min(_SEARCH_CACHE, key=lambda item: _SEARCH_CACHE[item][0])
        _SEARCH_CACHE.pop(oldest, None)
    _SEARCH_CACHE[key] = (time.time(), payload)


def search_self_test(
    network: str = "auto",
    search_provider: str = "none",
    search_api_key: str | None = None,
) -> dict[str, Any]:
    """One-click observability for the whole search pipeline (the claw-doctor
    idea): run a fixed diagnostic query through every channel and report each
    stage -- reachable? parsed? relevant? -- so "搜索效果差" turns into a
    concrete per-channel verdict instead of a mystery."""
    query = "boron neutron capture therapy BNCT"
    network = str(network or "auto").strip().lower()
    if network not in WEB_SEARCH_NETWORKS:
        network = "auto"
    checks: list[dict[str, Any]] = []

    provider = str(search_provider or "none").strip().lower()
    if provider in SEARCH_API_PROVIDERS and provider != "none" and search_api_key:
        try:
            api_results = _search_via_api(provider, search_api_key, query, 3, False, network)
            checks.append({
                "channel": f"搜索 API（{provider}）",
                "ok": bool(api_results),
                "detail": f"返回 {len(api_results)} 条结果" if api_results else "连通但没有结果",
            })
        except Exception as exc:
            checks.append({
                "channel": f"搜索 API（{provider}）",
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
            })

    for source, url in _search_sources(query, False):
        try:
            body = _fetch_text(url, timeout=8, network=network)
        except OSError as exc:
            checks.append({"channel": source, "ok": False, "detail": f"无法访问：{str(exc)[:200]}"})
            continue
        parsed = _parse_results(source, body, 5)
        if not parsed:
            checks.append({"channel": source, "ok": False, "detail": "可访问，但解析不到任何结果（页面结构变化或验证页）"})
            continue
        relevant = _filter_relevant(parsed, query)
        if not relevant:
            checks.append({
                "channel": source,
                "ok": False,
                "detail": f"解析到 {len(parsed)} 条，但全部与测试查询无关（疑似被风控）",
            })
            continue
        sample = relevant[0].get("title", "")[:60]
        checks.append({
            "channel": source,
            "ok": True,
            "detail": f"正常：{len(relevant)}/{len(parsed)} 条相关（示例：{sample}）",
        })

    healthy = any(check["ok"] for check in checks)
    return {
        "query": query,
        "network": network,
        "checkedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "healthy": healthy,
        "checks": checks,
        "summary": (
            "至少一个搜索通道工作正常。"
            if healthy
            else "所有本地搜索通道都不可用（Kimi 自带搜索不受影响，它在 Kimi 服务端执行）。"
        ),
    }


def web_search(
    _root: Path,
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    network: str = "auto",
    recency: bool = False,
    search_provider: str = "none",
    search_api_key: str | None = None,
) -> dict[str, Any]:
    clean_query = str(query or "").strip()
    if not clean_query:
        raise ValueError("web_search query cannot be empty")
    if len(clean_query) > MAX_QUERY_CHARS:
        raise ValueError(f"web_search query is too long; keep it under {MAX_QUERY_CHARS} characters")
    try:
        limit = int(max_results)
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_RESULTS
    limit = min(max(limit, 1), MAX_MAX_RESULTS)
    network = str(network or "auto").strip().lower()
    if network not in WEB_SEARCH_NETWORKS:
        network = "auto"
    recency = bool(recency)

    cache_key = (clean_query, recency, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    diagnostics = []
    results: list[dict[str, str]] = []
    source_used = ""

    provider = str(search_provider or "none").strip().lower()
    if provider in SEARCH_API_PROVIDERS and provider != "none" and search_api_key:
        try:
            results = _search_via_api(provider, search_api_key, clean_query, limit, recency, network)
            if results:
                source_used = f"api:{provider}"
        except Exception as exc:
            diagnostics.append({
                "source": f"api:{provider}",
                "network": network,
                "errorType": type(exc).__name__,
                "message": str(exc)[:420],
            })
            results = []

    for source, url in ([] if results else _search_sources(clean_query, recency)):
        try:
            body = _fetch_text(url, network=network)
        except OSError as exc:
            diagnostics.append({"source": source, "network": network, "errorType": type(exc).__name__, "message": str(exc)[:420]})
            continue
        parsed = _parse_results(source, body, limit)
        if not parsed:
            continue
        # Anti-slop gate: an engine that "answers" with content sharing zero
        # material with the query served an anti-bot/consent page, not results.
        # Treating that as success is what sent the model into keyword-retry
        # spirals; count it as an ENGINE FAILURE and move on.
        results = _filter_relevant(parsed, clean_query)
        if not results:
            diagnostics.append({
                "source": source,
                "network": network,
                "errorType": "IrrelevantResults",
                "message": f"解析到 {len(parsed)} 条结果但内容与查询无关（疑似被风控或返回验证页），已按通道失败处理",
            })
            continue
        source_used = source
        break

    if results:
        message = (
            f"获得 {len(results)} 条相关结果（来源 {source_used}）。引用时给出来源标题和 URL。"
        )
    else:
        message = (
            "所有搜索通道当前均不可用或只返回无关内容（多为免费通道被风控）。"
            "请如实告知用户联网搜索暂时不可用，不要反复更换关键词重试；"
            "可建议用户稍后再试、在设置里查看搜索自检，或配置正规搜索 API。"
        )
    payload = {
        "query": clean_query,
        "recency": recency,
        "source": source_used or "none",
        "network": network,
        "searchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "message": message,
        "diagnostics": [] if results else diagnostics[-4:],
    }
    if results:
        _cache_put(cache_key, payload)
    return payload
