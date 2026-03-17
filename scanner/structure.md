# Structure of the application

This file reflects the current implementation status in `scanner/`.

## Implemented modules (already in code)

0. Root/orchestration module (`scanner/main.py`)
    - CLI entrypoint with options for subnets, ports, logging, worker limits, artifacts dir, LLM cache toggle.
    - Sequentially orchestrates modules:
      1) `NetScanner`
      2) `WebEnumerator`
      3) `KeywordExtractor`
      4) `CredSearcher`
      5) `CredTester`
    - Periodic status summary and final scan summary logging.

1. Settings and runtime config (`scanner/settings.py`)
    - Central settings via env + runtime overrides.
    - Supports remote LLM mode and local LLM mode.
    - Artifacts dir, DB path, log file, worker limits, cache settings.

2. Persistence/DB layer (`scanner/db/`)
    - SQLite (peewee) with pooled connections.
    - Thread-safe serialized DB write queue.
    - Models:
      - `Service`: discovered web service + candidate credentials + module completion flags.
      - `Endpoint`: discovered path + login flag + keywords + tested/working credentials.

3. Network scan module (`scanner/netscan/main.py`)
    - Scans target subnet(s)/IP(s) with nmap.
    - Detects reachable HTTP services and checks HTTPS behavior.
    - Creates `Service` records and emits pubsub events.

4. Web enumeration module (`scanner/webenum/main.py`)
    - Multi-worker directory/path enumeration from wordlist.
    - Basic crawling by parsing links.
    - Renders pages via browser fetch helper for JS-heavy pages.
    - Endpoint deduplication and soft-404 handling.
    - Login page detection using password input heuristic.

5. Keyword extraction module (`scanner/ai/keyword_extractor.py`)
    - Selects relevant endpoints per service.
    - Converts page HTML to markdown.
    - Uses LLM to extract search keywords/links.
    - Stores extracted keywords in endpoint records.

6. Credential web-search module (`scanner/ai/cred_searcher.py`)
    - Uses LLM agent tools for web search and page fetch.
    - Collects potential default credentials and stores on `Service`.
    - Retries with bounded attempts and can stop early when creds already verified.

7. Credential testing module (`scanner/ai/cred_tester.py`)
    - Concurrent credential testing workers with bounded browser pool.
    - Selenium/LLM-tool-driven form interaction (`insert_text_into_field`, `click_button`).
    - Baseline failed-login comparison logic and success heuristics.
    - Records tested credentials, working credentials, and screenshots.

8. Shared browser/runtime helpers (`scanner/shared/`, `scanner/ai/tools/`)
    - Browser pool management for reusable headless sessions.
    - URL fetching, web search, and credential testing tool wrappers.
    - LLM wrapper with response caching and rate-limit backoff.

9. Integration testing harness (`scanner/tests/`)
    - End-to-end tests against vulnerable containerized apps.
    - Verifies discovery, login detection, and credential verification outcomes.
    - Stores per-run artifacts and summary tables.

## Potential/future work (not implemented or partial)

1. Webapp fingerprinting/name+version detection
    - No dedicated fingerprinting module yet.
    - Add deterministic fingerprints (headers, assets, routes, signatures) plus LLM-assisted labeling.

2. Database credential lookup from curated sources
    - Current flow relies on LLM web search + small static defaults.
    - Add local curated credential corpus and matching/ranking logic.

3. VHost enumeration and smarter crawl strategy
    - Path enumeration/crawling exists, but no explicit vhost brute forcing.
    - Add adaptive crawling prioritization and depth policies.

4. Lockout/rate-limit aware credential strategy
    - Basic early-stop logic exists.
    - Add per-service attempt budgets, cooldowns, and account lockout detection.

5. Reporting/notification module
    - Results are written to DB/logs and viewable in dashboard.
    - Missing alert channels (email/Slack/webhook) and report export.

6. CVE enrichment
    - No CVE lookup currently.
    - Once app identification is reliable, add CPE/CVE correlation.

7. GitHub/source mining for defaults
    - Not integrated in scanner pipeline.
    - Could be a separate offline job to enrich credential knowledge base.

8. Operator controls and resumability
    - No complete pause/resume/checkpointing workflow yet.
    - Add module-level resume and manual result injection between stages.

9. Config schema and policy controls
    - Settings currently env/CLI driven.
    - Add structured YAML/TOML config profiles and per-module policies.

## Notes

- Main pipeline is already functional end-to-end and tested with lab applications.
- Several items above are quality, safety, and accuracy improvements rather than missing core functionality.
