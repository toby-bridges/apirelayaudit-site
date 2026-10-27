"""Public website behavior and fixed-release contracts after repository split."""

import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
BASE = "https://apirelayaudit.com/"
CONFIG = json.loads((ROOT / "site-source.json").read_text(encoding="utf-8"))
VERSION = CONFIG["release"]["version"]
COMMIT = CONFIG["release"]["commit"]


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.lang = None
        self.title = []
        self.h1_count = 0
        self.canonicals = []
        self.alternates = set()
        self.links = []
        self.in_title = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang")
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.h1_count += 1
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href"))
        if tag == "link" and attrs.get("rel") == "alternate":
            self.alternates.add((attrs.get("hreflang"), attrs.get("href")))

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False


def _text(path):
    return path.read_text(encoding="utf-8")


def _sync_module():
    spec = importlib.util.spec_from_file_location("site_evidence", ROOT / "scripts/sync-evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_page_keeps_public_domain_language_title_and_heading():
    pages = sorted(WEB.rglob("*.html"))
    assert pages
    for path in pages:
        relative = path.relative_to(WEB).as_posix()
        suffix = relative.removesuffix("index.html") if path.name == "index.html" else relative
        page = Page(_text(path))
        assert page.canonicals == [BASE + suffix], path
        assert page.lang == ("zh-CN" if relative.startswith("zh/") else "en"), path
        assert "".join(page.title).strip(), path
        assert page.h1_count == 1, path


def test_sitemap_has_no_duplicate_or_foreign_domain_entries():
    root = ET.parse(WEB / "sitemap.xml").getroot()
    urls = [item.text for item in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert len(urls) == len(set(urls))
    assert all(url.startswith(BASE) for url in urls)


def test_first_chinese_task_has_a_homepage_entry_and_language_pair():
    slug = "guides/audit-claude-api-relay-safely.html"
    assert slug in Page(_text(WEB / "zh/index.html")).links
    expected = {("en", BASE + slug), ("zh-CN", BASE + "zh/" + slug)}
    for path in [WEB / slug, WEB / "zh" / slug]:
        assert Page(_text(path)).alternates == expected
    guide = _text(WEB / "zh" / slug)
    assert COMMIT in guide
    assert "--key-env API_RELAY_AUDIT_KEY" in guide
    assert "--connectivity" in guide
    assert "--skip-infra --skip-context" in guide
    assert "--key &lt;" not in guide


def test_release_downloads_are_fixed_to_the_declared_release():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
    assert re.fullmatch(r"[0-9a-f]{40}", COMMIT)
    assert re.fullmatch(r"[0-9a-f]{64}", CONFIG["release"]["audit_sha256"])
    allowed = {f"v{VERSION}", COMMIT, "${AUDIT_SCRIPT_REF}", "\\${AUDIT_SCRIPT_REF}", "$env:AUDIT_SCRIPT_REF"}
    seen = []
    pattern = re.compile(r"https://raw\.githubusercontent\.com/toby-bridges/api-relay-audit/([^/]+)/audit\.py")
    for path in WEB.rglob("*.html"):
        text = _text(path)
        for ref in pattern.findall(text):
            assert ref in allowed, (path, ref)
            seen.append(ref)
        assert "master/audit.py" not in text
    assert seen
    assert f"const scriptRef='v{VERSION}';" in _text(WEB / "index.html")


def test_homepage_keeps_published_dsh_install_and_channel_contract():
    text = _text(WEB / "index.html")
    assert "DeepSeek Harness plugin" in text
    assert f'dsh plugin --profile web add "github:toby-bridges/api-relay-audit#v{VERSION}"' in text
    assert "/relay-audit --connectivity" in text
    assert "API_RELAY_AUDIT_KEY" in text
    assert "Upstream Channel Classifier" in text
    assert "cmp_channel:\"Upstream Channel Classifier\"" in text
    assert "cmp_channel:\"上游通道分类\"" in text
    for forbidden in ["after ClawHub publication", "Claude Code Skill", "~/.claude/commands", "my key is sk-xxx", "Channel Fingerprint", '<td class="soon">Soon</td>']:
        assert forbidden not in text


def test_website_copy_preserves_query_families_and_signal_limits():
    for path in [WEB / "index.html", WEB / "zh/index.html"]:
        text = _text(path)
        for family in ["API relay audit", "Prompt injection audit", "Model substitution signals", "Web3 relay audit"]:
            assert family.lower() in text.lower(), (path, family)
        for forbidden in ["13-step", "13 steps", "13 步", "Steps 1-10"]:
            assert forbidden not in text
    home = _text(WEB / "index.html")
    assert "14-step" in home or "14 steps" in home or "14 步" in home
    assert all(profile in home for profile in ["general", "web3", "full"])
    assert "Step 11" in home and "profile-gated" in home
    assert "--profile web3" in home or "profile web3" in home
    assert "standalone" in home.lower()
    assert "provider proof" in home.lower() or "provider-level proof" in home.lower()


def test_evidence_snapshot_matches_explicit_public_provenance():
    evidence = CONFIG["evidence"]
    assert CONFIG["tool_repository"] == "toby-bridges/api-relay-audit"
    assert evidence["path"] == "evidence/registry.json"
    assert evidence["snapshot"] == "web/data/evidence.json"
    raw = (ROOT / evidence["snapshot"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == evidence["snapshot_sha256"]
    records = _sync_module().validate_registry(raw)
    if evidence["state"] == "pending_core_migration":
        assert evidence["commit"] is None and records == []
    else:
        assert evidence["state"] == "reviewed_public_snapshot"
        assert re.fullmatch(r"[0-9a-f]{40}", evidence["commit"])
        assert evidence["source_url"] == _sync_module().source_url(evidence["commit"])
        assert re.fullmatch(r"[0-9a-f]{64}", evidence["source_sha256"])
        assert evidence["record_count"] == len(records)


def test_publication_tree_excludes_internal_material_and_symlinks():
    for path in WEB.rglob("*"):
        assert not path.is_symlink(), path
        if not path.is_file():
            continue
        relative = path.relative_to(WEB).as_posix()
        assert not any(piece in relative for piece in ["content-board", "content-authoring", "content-baseline", "growth/", ".env", "owner-collection"])
        if path.suffix in {".html", ".css", ".json", ".txt", ".xml"}:
            text = _text(path)
            assert "/Users/" not in text and "/private/tmp/" not in text
            for pattern in _sync_module().SECRET_PATTERNS:
                assert not pattern.search(text), path


def test_workflow_deploys_only_verified_web_directory_from_main():
    workflow = _text(ROOT / ".github/workflows/pages.yml")
    assert "needs: test" in workflow
    assert "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'" in workflow
    assert "path: web" in workflow
    assert "path: .\n" not in workflow
    assert "pull_request_target:" not in workflow
    assert "schedule:" not in workflow
    assert "sync-evidence" not in workflow
