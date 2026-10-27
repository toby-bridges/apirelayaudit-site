"""Evidence import proves its fixed source and fails without publishing bad data."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("sync_evidence", ROOT / "scripts/sync-evidence.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
COMMIT = "a" * 40


def record():
    return {
        "schemaVersion": 1,
        "recordType": "community-submitted-audit-evidence",
        "relayDomain": "relay.example.com",
        "toolCommit": "b" * 40,
        "reportHash": "sha256:" + "c" * 64,
        "reportArtifactUrl": "https://github.com/example/project/files/1/report.md",
        "auditProfile": "general",
        "toolReportedOverallRating": "LOW",
        "source": "github-issue",
        "evidenceStatus": "accepted_unverified",
        "reviewStatus": "unverified",
        "redFlags": [],
        "reportImages": [],
    }


@pytest.fixture
def site(tmp_path):
    (tmp_path / "web/data").mkdir(parents=True)
    (tmp_path / "web/data/evidence.json").write_text("[]\n")
    config = {"tool_repository": "toby-bridges/api-relay-audit", "release": {"version": "2.5.0"}, "evidence": {"state": "old"}}
    (tmp_path / "site-source.json").write_text(json.dumps(config))
    return tmp_path


def test_import_preserves_unverified_record_and_records_exact_public_source(site):
    raw = json.dumps([record()]).encode()
    seen = []
    def fetch(commit):
        seen.append(commit)
        return raw
    result = sync.sync_evidence(site, COMMIT, fetch=fetch)
    assert seen == [COMMIT]
    assert result["record_count"] == 1
    snapshot = json.loads((site / "web/data/evidence.json").read_text())
    assert snapshot == [record()]
    assert snapshot[0]["reviewStatus"] == "unverified"
    evidence = json.loads((site / "site-source.json").read_text())["evidence"]
    assert evidence["commit"] == COMMIT
    assert evidence["source_url"] == f"https://raw.githubusercontent.com/toby-bridges/api-relay-audit/{COMMIT}/evidence/registry.json"
    assert evidence["snapshot_sha256"] == sync.hashlib.sha256((site / "web/data/evidence.json").read_bytes()).hexdigest()
    assert evidence["source_sha256"] == sync.hashlib.sha256(raw).hexdigest()


def test_empty_public_registry_remains_empty(site):
    result = sync.sync_evidence(site, COMMIT, fetch=lambda _: b"[]\n")
    assert result["record_count"] == 0
    assert (site / "web/data/evidence.json").read_bytes() == b"[]\n"


@pytest.mark.parametrize("commit", ["main", "master", "v2.5.0", "a" * 7, "A" * 40, "a" * 39, "a" * 41, "../" + "a" * 40])
def test_mutable_or_invalid_ref_is_rejected_before_fetch(site, commit):
    def fetch(_):
        pytest.fail("Invalid commit must not make a network request")
    with pytest.raises(sync.EvidenceError):
        sync.sync_evidence(site, commit, fetch=fetch)


@pytest.mark.parametrize("raw", [b"<html>not found</html>", b"{}", b"null", b"[null]", b"[{\"schemaVersion\":1}]", b"[\xff]", b" " * (sync.MAX_BYTES + 1)])
def test_bad_source_leaves_existing_snapshot_and_provenance_untouched(site, raw):
    before = {path: path.read_bytes() for path in [site / "site-source.json", site / "web/data/evidence.json"]}
    with pytest.raises(sync.EvidenceError):
        sync.sync_evidence(site, COMMIT, fetch=lambda _: raw)
    assert all(path.read_bytes() == value for path, value in before.items())


@pytest.mark.parametrize("change", [
    {"rawResponse": "must not be published"},
    {"schemaVersion": True},
    {"toolCommit": "master"},
    {"reportHash": "bad"},
    {"auditProfile": "other"},
    {"toolReportedOverallRating": "SAFE"},
    {"reportArtifactUrl": "https://name:password@example.com/report"},
    {"reportArtifactUrl": "https://example.com/report?api_key=fake-value"},
    {"reportArtifactUrl": "http://example.com/report"},
    {"reportArtifactUrl": "https://127.0.0.1/report"},
    {"reportArtifactUrl": "https://reports.internal/report"},
    {"reportArtifactUrl": "https://private-report/report"},
    {"relayDomain": "127.0.0.1"},
    {"relayDomain": "relay.internal"},
    {"reportImages": ["https://example.com/image?token=fake-value"]},
    {"stepSummary": "/Users/example/private-report.md"},
    {"stepSummary": "Bearer syntheticplaceholder123456789"},
    {"stepSummary": "sk-" + "x" * 32},
    {"redFlags": ["ghp_" + "x" * 36]},
])
def test_unsupported_or_sensitive_record_is_not_written(site, change):
    item = record() | change
    raw = json.dumps([item]).encode()
    before = (site / "web/data/evidence.json").read_bytes()
    with pytest.raises(sync.EvidenceError) as caught:
        sync.sync_evidence(site, COMMIT, fetch=lambda _: raw)
    assert (site / "web/data/evidence.json").read_bytes() == before
    assert "syntheticplaceholder" not in str(caught.value)
    assert "xxxxxxxxxxxxxxxx" not in str(caught.value)


def test_redirect_to_another_source_is_rejected():
    with pytest.raises(sync.EvidenceError):
        sync.NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://example.com/")


def test_fetch_reads_only_bounded_immutable_public_source(monkeypatch):
    seen = []
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, size):
            seen.append(size)
            return b"[]\n"
    class Opener:
        def open(self, request, timeout):
            seen.append((request.full_url, dict(request.header_items()), timeout))
            return Response()
    monkeypatch.setattr(sync, "build_opener", lambda *_: Opener())
    assert sync.fetch_evidence(COMMIT) == b"[]\n"
    url, headers, timeout = seen[0]
    assert url == f"https://raw.githubusercontent.com/toby-bridges/api-relay-audit/{COMMIT}/evidence/registry.json"
    assert set(key.lower() for key in headers) == {"user-agent"}
    assert timeout == 20
    assert seen[1] == sync.MAX_BYTES + 1


def test_failed_metadata_replace_restores_previous_snapshot(site, monkeypatch):
    original_replace = sync.os.replace
    def replace(source, destination):
        if Path(destination) == site / "site-source.json":
            raise OSError("synthetic metadata write failure")
        return original_replace(source, destination)
    monkeypatch.setattr(sync.os, "replace", replace)
    old_metadata = (site / "site-source.json").read_bytes()
    with pytest.raises(OSError):
        sync.sync_evidence(site, COMMIT, fetch=lambda _: json.dumps([record()]).encode())
    assert (site / "web/data/evidence.json").read_bytes() == b"[]\n"
    assert (site / "site-source.json").read_bytes() == old_metadata
    assert not list(site.rglob(".*.json.*"))
