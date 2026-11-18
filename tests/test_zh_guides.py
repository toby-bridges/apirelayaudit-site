"""Regression checks for the core Chinese guides that twin the English guides.

Each Chinese guide shares its slug with the English source under web/guides/,
links back and forth through hreflang, pins the declared release commit, and
uses the environment-variable key flow instead of a key on the command line.
"""

from html.parser import HTMLParser
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
BASE = "https://apirelayaudit.com/"
COMMIT = json.loads((ROOT / "site-source.json").read_text(encoding="utf-8"))["release"]["commit"]

TWIN_SLUGS = [
    "guides/what-is-ai-api-relay-proxy.html",
    "guides/detect-prompt-injection-llm-api-proxies.html",
    "guides/web3-wallet-prompt-injection-ai-agents.html",
]

# Wording the public Chinese pages must not use: competitor slogans, the
# retired key-flow claim, stale hosts, stale step counts and certification talk.
FORBIDDEN_PHRASES = [
    "付费不改分",
    "Key 留在本地",
    "key stays local",
    "toby-bridges.github.io",
    "13 步",
    "安全认证通过",
    "推荐以下中转站",
    "master/audit.py",
]


class _Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.lang = None
        self.links = []
        self.alternates = set()
        self.ids = set()
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang")
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "link" and attrs.get("rel") == "alternate":
            self.alternates.add((attrs.get("hreflang"), attrs.get("href")))


def _text(path):
    return path.read_text(encoding="utf-8")


def test_core_chinese_guides_pair_with_their_english_sources():
    for slug in TWIN_SLUGS:
        english = WEB / slug
        chinese = WEB / "zh" / slug
        assert english.exists() and chinese.exists(), slug
        expected = {("en", BASE + slug), ("zh-CN", BASE + "zh/" + slug)}
        assert _Page(_text(english)).alternates == expected, slug
        assert _Page(_text(chinese)).alternates == expected, slug
        assert f"../zh/{slug}" in _Page(_text(english)).links, slug
        assert f"../../{slug}" in _Page(_text(chinese)).links, slug
        assert _Page(_text(chinese)).lang == "zh-CN", slug


def test_core_chinese_guides_pin_the_release_and_use_the_env_key_flow():
    for slug in TWIN_SLUGS:
        guide = _text(WEB / "zh" / slug)
        assert COMMIT in guide, slug
        assert "v2.5.0" in guide, slug
        assert "--key &lt;" not in guide, slug
    for slug in TWIN_SLUGS[0:1] + TWIN_SLUGS[2:3]:
        assert "--key-env API_RELAY_AUDIT_KEY" in _text(WEB / "zh" / slug), slug
    web3 = _text(WEB / "zh" / TWIN_SLUGS[2])
    assert "--profile web3" in web3
    injection = _text(WEB / "zh" / TWIN_SLUGS[1])
    for label in ["exact\nwhitespace\nsubstituted", 'run_name="synthetic_guide_demo"', "pip install reqeusts==2.31.0"]:
        assert label in injection


def test_public_chinese_pages_avoid_forbidden_wording():
    for path in sorted((WEB / "zh").rglob("*.html")):
        text = _text(path)
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, (path, phrase)


def test_chinese_homepage_links_every_chinese_guide_and_has_a_faq():
    home = _Page(_text(WEB / "zh" / "index.html"))
    for path in sorted((WEB / "zh" / "guides").glob("*.html")):
        assert f"guides/{path.name}" in home.links, path.name
    assert "faq" in home.ids
    assert "compare-relay-tools.html" in home.links
