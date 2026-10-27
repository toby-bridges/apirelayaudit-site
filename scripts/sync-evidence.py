#!/usr/bin/env python3
"""Import a reviewed public evidence registry from one immutable tool commit."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request


SOURCE_REPOSITORY = "toby-bridges/api-relay-audit"
SOURCE_PATH = "evidence/registry.json"
SNAPSHOT_PATH = "web/data/evidence.json"
MAX_BYTES = 2 * 1024 * 1024
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
DOMAIN_RE = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.I),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?:/Users/|/home/|[A-Z]:\\Users\\)", re.I),
)
SENSITIVE_QUERY_KEYS = {
    "key", "api_key", "apikey", "token", "access_token", "authorization",
    "signature", "x-amz-signature", "x-goog-signature",
}
STRING_FIELDS = {
    "recordType", "relayDomain", "claimedProvider", "apiFormat", "modelTested",
    "toolVersion", "toolCommit", "auditProfile", "toolReportedOverallRating",
    "evidenceLevel", "stepSummary", "operatorContacted", "falsePositiveSuspected",
    "submittedAt", "testedAt", "submitter", "reportHash", "reportArtifactUrl",
    "evidenceStatus", "reviewStatus", "disputeStatus", "staleAfter", "source",
}
RECORD_FIELDS = STRING_FIELDS | {"schemaVersion", "issueNumber", "redFlags", "reportImages"}
REQUIRED_FIELDS = {
    "schemaVersion", "recordType", "relayDomain", "toolCommit", "reportHash",
    "reportArtifactUrl", "auditProfile", "toolReportedOverallRating", "source",
}


class EvidenceError(ValueError):
    """A safe-to-display registry validation failure without source values."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EvidenceError("Evidence source redirects are not allowed")


def validate_commit(commit):
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise EvidenceError("An explicit lowercase 40-character reviewed commit is required")
    return commit


def source_url(commit):
    validate_commit(commit)
    return f"https://raw.githubusercontent.com/{SOURCE_REPOSITORY}/{commit}/{SOURCE_PATH}"


def fetch_evidence(commit):
    request = Request(source_url(commit), headers={"User-Agent": "apirelayaudit-site-evidence-sync"})
    try:
        with build_opener(NoRedirects()).open(request, timeout=20) as response:
            if response.status != 200:
                raise EvidenceError("Evidence source did not return HTTP 200")
            raw = response.read(MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise EvidenceError("Could not read the fixed public evidence source") from None
    if len(raw) > MAX_BYTES:
        raise EvidenceError("Evidence source exceeds the size limit")
    return raw


def _check_public_text(value):
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise EvidenceError("Evidence contains a credential-shaped value or private local path")


def _check_public_url(value):
    _check_public_text(value)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise EvidenceError("Evidence links must be public HTTPS URLs without credentials")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise EvidenceError("Evidence links must not use private local hosts")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is None and not DOMAIN_RE.fullmatch(host):
            raise EvidenceError("Evidence links must use a public hostname")
        if address is not None and not address.is_global:
            raise EvidenceError("Evidence links must not use private addresses")
        if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
            raise EvidenceError("Evidence links must not include credential query parameters")
    except (ValueError, TypeError):
        raise EvidenceError("Evidence contains an invalid public URL") from None


def validate_registry(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise EvidenceError("Evidence source exceeds the size limit or is not bytes")
    try:
        records = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise EvidenceError("Evidence source is not a UTF-8 JSON registry") from None
    if not isinstance(records, list):
        raise EvidenceError("Evidence registry must be a JSON array")
    for record in records:
        if not isinstance(record, dict) or set(record) - RECORD_FIELDS or REQUIRED_FIELDS - set(record):
            raise EvidenceError("Evidence record has missing or unsupported fields")
        if type(record["schemaVersion"]) is not int or record["schemaVersion"] != 1:
            raise EvidenceError("Unsupported evidence schema version")
        if record["recordType"] != "community-submitted-audit-evidence" or record["source"] != "github-issue":
            raise EvidenceError("Unsupported evidence record type or source")
        for field in STRING_FIELDS & set(record):
            value = record[field]
            if not isinstance(value, str) or len(value) > 8192:
                raise EvidenceError("Evidence text field has an invalid type or length")
            _check_public_text(value)
        if not DOMAIN_RE.fullmatch(record["relayDomain"]):
            raise EvidenceError("Evidence relay domain has invalid public hostname syntax")
        _check_public_url("https://" + record["relayDomain"])
        if not re.fullmatch(r"[0-9a-f]{7,40}", record["toolCommit"]):
            raise EvidenceError("Evidence tool commit has invalid syntax")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", record["reportHash"]):
            raise EvidenceError("Evidence report hash has invalid syntax")
        if record["auditProfile"] not in {"general", "web3", "full"}:
            raise EvidenceError("Evidence audit profile is unsupported")
        if record["toolReportedOverallRating"] not in {"LOW", "MEDIUM", "HIGH"}:
            raise EvidenceError("Evidence rating is unsupported")
        issue = record.get("issueNumber")
        if issue is not None and (type(issue) is not int or issue < 1):
            raise EvidenceError("Evidence issue number is invalid")
        _check_public_url(record["reportArtifactUrl"])
        for field, limit in [("redFlags", 10), ("reportImages", 4)]:
            values = record.get(field, [])
            if not isinstance(values, list) or len(values) > limit:
                raise EvidenceError("Evidence list field has an invalid shape")
            for value in values:
                if not isinstance(value, str) or len(value) > 8192:
                    raise EvidenceError("Evidence list item has an invalid type or length")
                _check_public_text(value)
                if field == "reportImages":
                    _check_public_url(value)
    return records


def _stage_bytes(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp


def sync_evidence(root, commit, fetch=fetch_evidence):
    """Fetch and validate before replacing the public snapshot and provenance."""
    validate_commit(commit)
    root = Path(root)
    config_path = root / "site-source.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("tool_repository") != SOURCE_REPOSITORY:
        raise EvidenceError("Site tool repository does not match the fixed public source")
    raw = fetch(commit)
    records = validate_registry(raw)
    snapshot = (json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode()
    snapshot_path = root / SNAPSHOT_PATH
    config["evidence"] = {
        "path": SOURCE_PATH,
        "commit": commit,
        "state": "reviewed_public_snapshot",
        "source_url": source_url(commit),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot": SNAPSHOT_PATH,
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "record_count": len(records),
    }
    metadata = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
    old_snapshot = snapshot_path.read_bytes() if snapshot_path.exists() else None
    snapshot_temp = _stage_bytes(snapshot_path, snapshot)
    metadata_temp = None
    installed_snapshot = False
    try:
        metadata_temp = _stage_bytes(config_path, metadata)
        os.replace(snapshot_temp, snapshot_path)
        installed_snapshot = True
        os.replace(metadata_temp, config_path)
    except BaseException:
        if installed_snapshot:
            if old_snapshot is None:
                snapshot_path.unlink(missing_ok=True)
            else:
                rollback = _stage_bytes(snapshot_path, old_snapshot)
                os.replace(rollback, snapshot_path)
        raise
    finally:
        snapshot_temp.unlink(missing_ok=True)
        if metadata_temp is not None:
            metadata_temp.unlink(missing_ok=True)
    return {"commit": commit, "record_count": len(records), "snapshot_sha256": hashlib.sha256(snapshot).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="reviewed lowercase 40-character tool repository commit")
    args = parser.parse_args(argv)
    try:
        result = sync_evidence(Path(__file__).resolve().parent.parent, args.commit)
    except (EvidenceError, OSError, json.JSONDecodeError):
        parser.exit(1, "Evidence sync failed; no unvalidated source values were printed.\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
