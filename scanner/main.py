# Main entry point for the network scanner.
# Orchestrates all scanner modules to discover services and test credentials.

import json
import logging
import time
import threading
from pathlib import Path
import click
from tabulate import tabulate

from scanner.netscan import NetScanner
from scanner.webenum import WebEnumerator
from scanner.ai import CredSearcher, CredTester, KeywordExtractor
from scanner.settings import override_settings, configure_logging, get_settings
from scanner.db import load_or_create_db, Endpoint, Service
from scanner.ai.llm_cache import LLMCache

logger = logging.getLogger("scanner.main")

@click.command()
@click.argument("subnets")
@click.option("--ports", "-p", default=None, help="Comma-separated list of ports to scan; forwarded to nmap")
@click.option("--log-level", "-L", default="INFO", help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
@click.option("--log-file", default="scanner.log", help="Path to the log file. Default: <artifacts_dir>/scanner.log")
@click.option("--max-webdrivers", default=None, type=int, help="Maximum number of concurrent WebDriver instances for credential testing. Default: min(CPU cores, RAM in GB / 2)")
@click.option("--max-webenum-workers", default=4, help="Maximum number of concurrent web enumeration workers")
@click.option("--artifacts-dir", default="./scan_artifacts", help="Base directory for scan artifacts (DB, screenshots, logs)")
@click.option("--disable_llm_cache", is_flag=True, help="Do not cache LLM responses")
def main_cmd(subnets, ports, log_level, log_file, max_webdrivers, max_webenum_workers, artifacts_dir, disable_llm_cache):
    """CLI wrapper that delegates to the run() function."""
    run(subnets, ports, log_level, log_file, max_webdrivers, max_webenum_workers, artifacts_dir, disable_llm_cache)

def run(subnets, ports, log_level, log_file, max_webdrivers, max_webenum_workers, artifacts_dir, disable_llm_cache):
    """
    Initialize settings, database, and start all scanner modules.
    """
    override_settings(
        subnets=subnets,
        ports=ports,
        log_level=log_level,
        log_file=Path(log_file),
        max_webdrivers=max_webdrivers,
        max_webenum_workers=max_webenum_workers,
        artifacts_dir=Path(artifacts_dir),
        disable_llm_cache=disable_llm_cache
    )
    get_settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    configure_logging()
    load_or_create_db()

    start_time = time.time()
    logger.debug("Starting scanner")

    subnets = [sub for sub in subnets.split(",") if sub.strip()]

    modules = [
        NetScanner(subnets, ports),
        WebEnumerator(),
        KeywordExtractor(),
        CredSearcher(),
        CredTester(),
    ]

    # Status monitoring thread prints progress every 3 minutes
    stop_event = threading.Event()
    status_thread = threading.Thread(
        target=status_monitor,
        args=(stop_event,),
        daemon=True
    )
    status_thread.start()

    try:
        for module in modules:
            module.start()

        logger.info("All modules started.")

        for module in modules:
            module.join()

        logger.info("All modules completed.")
    finally:
        stop_event.set()
        status_thread.join(timeout=1)

    write_token_usage_artifact()
    print_scan_summary(start_time)


def write_token_usage_artifact():
    """Persist cumulative LLM token usage to a JSON file in artifacts_dir for external tooling to read."""
    token_usage_path = get_settings().artifacts_dir / "token_usage.json"
    token_usage_path.write_text(json.dumps({
        "input_tokens": LLMCache().total_input_tokens,
        "output_tokens": LLMCache().total_output_tokens,
        "estimated": LLMCache().estimated_tokens_used,
    }))


def status_monitor(stop_event):
    """Background thread that prints scan progress every 180 seconds."""
    while not stop_event.is_set():
        if stop_event.wait(timeout=180):
            break
        print_status_summary()


def print_scan_summary(start_time):
    """Print final scan results including discovered credentials and statistics."""
    summary = "\n" + "=" * 30 + " Scan Summary " + "=" * 30 + "\n"

    endpoints_with_default_creds = Endpoint.select().where(Endpoint.working_credentials != '')
    if endpoints_with_default_creds.count() > 0:
        summary += "Endpoints with default credentials found:\n"
        for endpoint in endpoints_with_default_creds:
            summary += f"- {endpoint.url()} | Credentials: {endpoint.working_credentials}\n"
    else:
        summary += "No endpoints with default credentials found.\n"

    services = Service.select()
    summary += f"\nTotal services scanned: {services.count()}\n"

    service_data = []
    for service in Service.select():
        service_data.append([
            service.url(),
            len(service.endpoints),
            service.credentials if service.credentials else 'Unknown or N/A'
        ])

    summary += tabulate(
        service_data,
        headers=['Service URL', 'Endpoints', 'Potential Default Credentials'],
        tablefmt='grid'
    ) + "\n"

    cache_hit_rate = (LLMCache().cached_requests / LLMCache().total_requests * 100) if LLMCache().total_requests > 0 else 0
    summary += f"Total number of LLM requests: {LLMCache().total_requests}; cached: {LLMCache().cached_requests} ({cache_hit_rate:.2f}%)\n"
    summary += f"Total scan duration: {time.time() - start_time:.2f} seconds\n"
    logger.info(summary)


def print_status_summary():
    """Print real-time scan status including services, endpoints, and credential testing progress."""
    services = Service.select()
    endpoints = Endpoint.select()
    login_endpoints = Endpoint.select().where(Endpoint.is_login == True)
    endpoints_with_creds = Endpoint.select().where(Endpoint.working_credentials != '')

    # Count endpoints by analysis status
    endpoints_with_keywords = Endpoint.select().where(Endpoint._keywords != None)
    endpoints_pending_analysis = Endpoint.select().where(Endpoint._keywords == None)

    # Services enumeration status
    services_in_progress = Service.select().where(Service.webenum_done == False)
    services_completed = Service.select().where(Service.webenum_done == True)

    status = "\n" + "=" * 30 + " Current Status " + "=" * 30 + "\n"
    status += f"Services discovered: {services.count()}\n"
    status += f"  - Enumeration in progress: {services_in_progress.count()}\n"
    status += f"  - Enumeration completed: {services_completed.count()}\n"
    status += f"\nEndpoints discovered: {endpoints.count()}\n"
    status += f"  - Login pages identified: {login_endpoints.count()}\n"
    status += f"  - Analyzed for keywords: {endpoints_with_keywords.count()}\n"
    status += f"  - Pending analysis: {endpoints_pending_analysis.count()}\n"
    status += f"\nCredentials testing:\n"
    status += f"  - Endpoints with working credentials: {endpoints_with_creds.count()}\n"

    # Calculate total credentials tested
    total_tested = sum(len(ep.tested_credentials) for ep in login_endpoints)
    status += f"  - Total credential pairs tested: {total_tested}\n"

    # LLM cache statistics
    cache_hit_rate = (LLMCache().cached_requests / LLMCache().total_requests * 100) if LLMCache().total_requests > 0 else 0
    status += f"\nLLM requests: {LLMCache().total_requests} (cached: {LLMCache().cached_requests}, {cache_hit_rate:.2f}%)\n"

    # Display services with their first 10 endpoints
    status += "\n" + "=" * 30 + " Services & Endpoints " + "=" * 30 + "\n"
    for service in services:
        status += f"\n{service.url()}\n"
        status += f"  Credentials found: {service.credentials if service.credentials else 'None'}\n"
        status += f"  Total endpoints: {len(service.endpoints)}\n"

        if len(service.endpoints) > 0:
            status += "  Endpoints (showing first 10):\n"
            for i, endpoint in enumerate(service.endpoints[:10]):
                login_marker = " [LOGIN]" if endpoint.is_login else ""
                creds_marker = f" [CREDS: {endpoint.working_credentials}]" if endpoint.working_credentials else ""
                status += f"    {i+1}. {endpoint.path}{login_marker}{creds_marker}\n"

            if len(service.endpoints) > 10:
                status += f"    ... and {len(service.endpoints) - 10} more\n"

    status += "\n" + "=" * 76 + "\n"

    logger.info(status)


if __name__ == '__main__':
    main_cmd()  # pylint: disable=no-value-for-parameter
