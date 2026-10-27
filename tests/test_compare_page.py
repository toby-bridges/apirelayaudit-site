"""Regression checks for the Chinese tool-comparison page (web/zh/compare-relay-tools.html).

The page quotes two third-party sites. Every external link on it was fetched on
2026-10-26 and returned HTTP 200; that check is a one-off recorded in the commit
message, so this test freezes the allowed link set instead of touching the network.
"""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = REPO_ROOT / "web"
PAGE = WEB_ROOT / "zh" / "compare-relay-tools.html"
PAGE_URL = "https://apirelayaudit.com/zh/compare-relay-tools.html"

# Fetched 2026-10-26, all HTTP 200. Adding a link here means re-verifying it.
ALLOWED_EXTERNAL_LINKS = {
    "https://www.hvoyai.com/",
    "https://www.hvoyai.com/partner/terms/",
    "https://github.com/zzsting88/relayAPI",
    "https://veridrop.org/",
    "https://veridrop.org/leaderboard",
    "https://veridrop.org/business",
    "https://veridrop.org/about/affiliate",
    "https://veridrop.org/faq",
    "https://veridrop.org/compare/veridrop-vs-hvoy",
    "https://veridrop.org/compare/relay-detectors",
    "https://github.com/canarybyte/veridrop",
    "https://github.com/toby-bridges/api-relay-audit",
    "https://github.com/toby-bridges/api-relay-audit/issues",
    "https://github.com/toby-bridges/api-relay-audit/blob/master/docs/community-evidence.md",
}

# Verbatim quotes from the two sites as captured on 2026-10-26, plus our own
# commitments. If a quote disappears from the page, the citation changed.
REQUIRED_PHRASES = [
    "2026-10-26",
    "主要检查接口连通性、响应特征、延迟和模型一致性信号",
    "禾维 AI 是广告与信息展示平台",
    "可能属于广告或商业展示",
    "免费、无需注册、API key 不落盘",
    "均明确标识为付费展示",
    "付费不改检测分与红黑榜",
    "用 hvoy 比价、找候选站，用 Veridrop 做买前真伪核验",
    "目前没有付费展示位",
    "价目公开、不改任何检测结果、不接受付费下架、付费展示一律标注",
    "只发给你指定的中转站 URL",
    "不为任何中转站颁发安全认证",
    "目前没有已发布条目",
    "本站未复核",
]

# Things that must never appear on this page: unverified attributions,
# volatile competitor counts, internal documents, stale hosts, and claims the
# README forbids.
FORBIDDEN_PHRASES = [
    "aff=",
    "36 / 40",
    "SEO_AI_GEO_PLAN",
    "toby-bridges.github.io",
    "Key 留在本地",
    "key stays local",
    "付费不改分",
    "推荐以下中转站",
    "安全认证通过",
    # MCP distribution is PR #110 and not in master yet; drop this once it ships.
    "MCP",
]


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.canonicals = []
        self.lang = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang")
        if tag == "a" and "href" in attrs:
            self.hrefs.append(attrs["href"])
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))


def _parse(path):
    parser = _Links()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def test_page_is_chinese_with_exact_canonical():
    parser = _parse(PAGE)
    assert parser.lang == "zh-CN"
    assert parser.canonicals == [PAGE_URL]


def test_external_links_are_frozen_to_verified_set():
    external = {
        href for href in _parse(PAGE).hrefs if urlparse(href).scheme in ("http", "https")
    }
    assert external, "page should cite its sources"
    assert external <= ALLOWED_EXTERNAL_LINKS, external - ALLOWED_EXTERNAL_LINKS
    assert all(href.startswith("https://") for href in external)


def test_quotes_and_commitments_are_present():
    text = PAGE.read_text(encoding="utf-8")
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in text]
    assert not missing, missing


def test_forbidden_claims_are_absent():
    text = PAGE.read_text(encoding="utf-8")
    present = [phrase for phrase in FORBIDDEN_PHRASES if phrase in text]
    assert not present, present


def test_page_is_reachable_from_chinese_home_english_guide_and_sitemap():
    assert "compare-relay-tools.html" in _parse(WEB_ROOT / "zh" / "index.html").hrefs
    guide = WEB_ROOT / "guides" / "compare-api-relay-audit-hvoy-cctest.html"
    assert "../zh/compare-relay-tools.html" in _parse(guide).hrefs
    root = ET.parse(WEB_ROOT / "sitemap.xml").getroot()
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    assert PAGE_URL in [item.text for item in root.findall("sm:url/sm:loc", namespace)]
