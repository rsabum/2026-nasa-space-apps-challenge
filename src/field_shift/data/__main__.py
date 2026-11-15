"""Command line: `python -m field_shift.data fetch [--dataset NAME | --all] [--force]`
and `python -m field_shift.data status`."""

from __future__ import annotations

import argparse
import logging
import sys

import requests

from field_shift.config import Config, load_config
from field_shift.data import DATASETS, cache, http, reference

log = logging.getLogger("field_shift")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)-7s %(message)s")
    # Library debug logs can include full request URLs; keep them quiet.
    for noisy in ("urllib3", "rasterio", "earthaccess", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def mock_server_up(config: Config) -> bool:
    try:
        requests.get(config.mock_base_url + "/health", timeout=3)  # no retries: fail fast
        return True
    except Exception:
        return False


def run_fetch(config: Config, names: list[str], force: bool) -> list[cache.FetchResult]:
    if config.is_mock and not mock_server_up(config):
        print(f"The mock services are not running at {config.mock_base_url}.\n"
              "Start them in another terminal with:  python -m field_shift.mock serve", file=sys.stderr)
        raise SystemExit(2)
    if config.is_mock:
        log.info("endpoints.mode = mock: fetching SYNTHETIC data from %s", config.mock_base_url)
    results = []
    for name in names:
        log.info("--- %s", name)
        try:
            result = DATASETS[name].module.fetch(config, force=force)
        except Exception as exc:  # keep going: one broken source must not stop the rest
            log.exception("%s failed", name)
            result = cache.FetchResult(name, "failed", http.redact(str(exc))[:300])
        log.info("%s", result)
        results.append(result)
    print("\nSummary")
    for result in results:
        print(f"  {result}")
    return results


def run_status(config: Config) -> None:
    manifest = cache.read_manifest(config)
    print(f"Endpoint mode: {config.mode.upper()}"
          + (" (synthetic data from local mock services)" if config.is_mock else ""))
    header = f"{'dataset':<9}{'cached':<8}{'source':<21}{'range':<24}{'rows':>7}  {'last fetched (UTC)':<26}credentials"
    print(header)
    print("-" * len(header))
    for name, info in DATASETS.items():
        entry = manifest.get(name, {})
        cached = info.primary_output(config).exists()
        source = ("MOCK/SYNTHETIC" if entry.get("source") == "mock" else "REAL") if entry else "-"
        if name == "terrain" and entry.get("source_used"):
            source += f" {entry['source_used']}"
        span = f"{entry.get('date_min', '')}..{entry.get('date_max', '')}" if entry.get("date_min") else "-"
        rows = str(entry.get("rows", "-"))
        fetched = entry.get("fetched_at", "-")
        creds = "-" if info.credential is None else ("ok" if info.has_credential(config) else f"MISSING {info.credential}")
        print(f"{name:<9}{'yes' if cached else 'no':<8}{source:<21}{span:<24}{rows:>7}  {fetched:<26}{creds}")
    print("\nHand-filled reference tables (data/reference/):")
    for name, blanks in reference.blank_counts(config).items():
        state = blanks if isinstance(blanks, str) else ("complete" if blanks == 0 else f"{blanks} blank cells")
        print(f"  {name + '.csv':<22}{state}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m field_shift.data", description=__doc__)
    parser.add_argument("--config", help="path to config.yaml (default: repo config.yaml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_p = sub.add_parser("fetch", help="download and cache datasets")
    which = fetch_p.add_mutually_exclusive_group(required=True)
    which.add_argument("--dataset", choices=list(DATASETS))
    which.add_argument("--all", action="store_true")
    fetch_p.add_argument("--force", action="store_true", help="re-download even if cached")
    sub.add_parser("status", help="show what is cached")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    config = load_config(args.config)
    if args.command == "status":
        run_status(config)
        return 0
    names = list(DATASETS) if args.all else [args.dataset]
    results = run_fetch(config, names, args.force)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
