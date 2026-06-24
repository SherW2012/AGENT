from __future__ import annotations

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
CJK_QUERY_FILLER_RE = re.compile(
    r"(最新动态|最新消息|最新进展|实时动态|发展速度|发展进度|进展情况|"
    r"是不是|是否|有没有|怎么样|如何|哪个|哪家|哪些|比较|相比|"
    r"从|上看|来看|而言|更快|更慢|更好|更强|的|了|吗|呢|吧)"
)
CURRENT_QUERY_TERMS = (
    "latest",
    "current",
    "recent",
    "today",
    "news",
    "progress",
    "update",
    "updates",
    "release",
)
CURRENT_QUERY_CJK_TERMS = (
    "最新",
    "动态",
    "新闻",
    "今日",
    "近期",
    "前沿",
    "进展",
    "进度",
    "发展",
    "发布",
    "获批",
    "上市",
)

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
    with _open_url(request, timeout=14, network=network) as response:
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


def _looks_like_current_query(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in CURRENT_QUERY_TERMS) or any(term in query for term in CURRENT_QUERY_CJK_TERMS)


def _query_variants(query: str) -> list[str]:
    clean = query.strip()
    return [clean] if clean else []


def _search_sources(query: str) -> list[tuple[str, str, str]]:
    sources: list[tuple[str, str, str]] = []
    current = _looks_like_current_query(query)
    for variant in _query_variants(query):
        encoded = urlencode({"q": variant})
        plus_query = quote_plus(variant)
        if current:
            sources.extend(
                [
                    (
                        "google-news-rss",
                        "https://news.google.com/rss/search?"
                        + urlencode({"q": variant, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}),
                        variant,
                    ),
                    ("bing-news-rss", f"https://www.bing.com/news/search?q={plus_query}&format=rss", variant),
                ]
            )
        sources.extend(
            [
                ("duckduckgo-html", "https://duckduckgo.com/html/?" + encoded, variant),
                ("duckduckgo-rss", "https://duckduckgo.com/rss/?" + encoded, variant),
                ("bing-html", f"https://www.bing.com/search?q={plus_query}&setlang=zh-CN", variant),
            ]
        )
    return sources


def _query_focus_terms(query: str) -> list[str]:
    lowered = query.lower()
    latin = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", lowered)
    cjk_text = re.sub(r"[^\u4e00-\u9fff]+", " ", query)
    cjk_text = CJK_QUERY_FILLER_RE.sub(" ", cjk_text)
    cjk = []
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", cjk_text):
        if len(chunk) <= 12:
            cjk.append(chunk)
            continue
        cjk.extend(re.findall(r"[\u4e00-\u9fff]{2,8}", chunk))
    return list(dict.fromkeys([*latin, *cjk]))[:8]


def _filter_relevant_results(query: str, results: list[dict[str, str]]) -> list[dict[str, str]]:
    focus_terms = _query_focus_terms(query)
    if not focus_terms:
        return results
    filtered = []
    for result in results:
        haystack = " ".join(str(result.get(key) or "") for key in ("title", "snippet", "url")).lower()
        if any(term.lower() in haystack for term in focus_terms):
            filtered.append(result)
    return filtered or results


def web_search(_root: Path, query: str, max_results: int = DEFAULT_MAX_RESULTS, network: str = "auto") -> dict[str, Any]:
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

    diagnostics = []
    results: list[dict[str, str]] = []
    source_used = ""
    for source, url, variant in _search_sources(clean_query):
        try:
            body = _fetch_text(url, network=network)
        except OSError as exc:
            diagnostics.append({"source": source, "network": network, "errorType": type(exc).__name__, "message": str(exc)[:420]})
            continue
        if source in {"duckduckgo-rss", "google-news-rss", "bing-news-rss"}:
            results = parse_duckduckgo_rss(body, limit)
        elif source == "bing-html":
            results = parse_bing_html(body, limit)
        else:
            results = parse_duckduckgo_html(body, limit)
        results = _filter_relevant_results(variant, results)
        if results:
            source_used = source
            break

    return {
        "query": clean_query,
        "queryVariant": variant if results else "",
        "source": source_used or "none",
        "network": network,
        "searchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "diagnostics": [] if results else diagnostics[-3:],
    }
