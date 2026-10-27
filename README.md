# apirelayaudit-site

## Purpose

This repository contains the static source files for the website hosted at https://apirelayaudit.com/ . The core audit CLI tool is maintained independently at https://github.com/toby-bridges/api-relay-audit . The website and the tool repository operate on separate release schedules.

## Repository Boundary

All static HTML, CSS, script, and image assets reside in the `web/` directory. Published URL structures must be preserved during edits, including `/zh/`, `/guides/*.html`, `/zh/compare-relay-tools.html`, and `/zh/guides/audit-claude-api-relay-safely.html`. Do not alter published slugs.

The site is static. It does not run server-side audits or transmit entered API credentials to a site backend. Generated audit command snippets instruct readers to execute checks locally against reader-selected relays. Core tool code, detection algorithms, report schemas, synthetic fixtures, and community evidence reviews belong in the tool repository; link directly to upstream resources rather than maintaining redundant copies here.

Do not commit internal editorial outlines, acquisition tests, owner analytics, raw audit reports, personal details, or credentials to this public repository.

## Local Preview and Checks

Preview the site locally by serving only the `web/` directory:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web
```

To run repository validation tests:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
```

Automated CI runs these test suites before Pages deployment. Pull requests do not trigger production deployments. The default branch is `main`.

## Content and Evidence Updates

Tool provenance is tracked in `site-source.json`, which records the referenced tool release, tool commit hash, download checksum, and reviewed evidence snapshot metadata. The Chinese onboarding guide is pinned to tool release v2.5.0 (commit `75bdac000051871c9f088a3be58e6f17a8854ffb`).

Synchronize approved public evidence snapshots from the tool repository using:

```bash
python3 scripts/sync-evidence.py --commit <reviewed-40-character-tool-commit>
```

This script copies the reviewed public registry snapshot from upstream `evidence/registry.json` and updates snapshot provenance records. Automated synchronization against untracked branch heads is disallowed. An empty registry indicates an absence of published evidence, not confirmation that a relay is safe.

## Deployment and Provenance

The production Pages workflow publishes only the `web/` directory. Custom domain mappings and HTTPS enforcement are configured separately from repository files.

Imported sources and file hashes are recorded in `SOURCE.json`. The original `AGPL-3.0-only` license is preserved in `LICENSE`.
