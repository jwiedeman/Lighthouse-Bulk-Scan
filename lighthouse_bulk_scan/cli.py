import os
import csv
import json
import logging
import argparse
import pandas as pd
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

from .sitemap import fetch_sitemaps_from_robots, parse_sitemap
from .runner import get_lighthouse_path, run_lighthouse
from .report import extract_detailed_data

def parse_display_value(val):
    """Extract numeric portion from strings like '1.2 s' or '240 ms'."""
    if not val:
        return None
    # Remove all non-digit and non-decimal characters
    val_str = re.sub(r'[^0-9.]', '', val)
    try:
        return float(val_str) if val_str else None
    except ValueError:
        return None

def get_domain_from_url(url):
    """Attempt to parse domain from a given URL."""
    parsed = urlparse(url)
    return parsed.netloc or "unknown-domain"

def main():
    """
    Lighthouse bulk audit script with:
      - Single URL, CSV, or sitemap input
      - Default Chrome flags (headless, no-sandbox, etc.) for cross-platform
      - Per-URL timeout for each Lighthouse run
      - Multiple runs per URL (controlled by --runs-per-url)
      - Storing each run’s JSON in a subfolder run_1/, run_2/, etc.
      - Aggregated CSV summary across all runs & modes
      - Graceful KeyboardInterrupt handling
    """

    parser = argparse.ArgumentParser(
        description="Run Lighthouse audits across multiple URLs and runs, storing results in subfolders, summarizing in a CSV."
    )

    # Input modes
    parser.add_argument("--base-url", default="",
                        help="Domain/base URL (e.g. 'example.com') for sitemaps. Ignored if CSV or --url-target used.")
    parser.add_argument("--url-target", default="",
                        help="Single URL to audit, bypassing sitemaps/CSV.")
    parser.add_argument("--csv-input-file", default="",
                        help="Path to a CSV file with URLs in the first column (sitemaps ignored if set).")
    parser.add_argument("--config-file", default="", help="Optional YAML/JSON config file with defaults.")

    # Limits & outputs
    parser.add_argument("--max-urls", type=int, default=99999,
                        help="Max URLs to process from CSV/sitemaps. Default=99999.")
    parser.add_argument("--output-dir", default="lighthouse_reports",
                        help="Top-level directory for storing Lighthouse JSON outputs.")
    parser.add_argument("--csv-output", default="lighthouse_summary.csv",
                        help="(Legacy) final CSV name if needed; we now store domain-timestamp CSV inside /reports.")
    parser.add_argument("--db-uri", default="", help="SQLAlchemy DB URI for saving results (optional).")

    # Lighthouse & logging
    parser.add_argument("--lighthouse-path", default="",
                        help="Path to Lighthouse if not on the system PATH.")
    parser.add_argument("--disable-mobile", action="store_true",
                        help="Disable mobile mode (only run desktop).")
    parser.add_argument("--debug", action="store_true",
                        help="Set Python logger to DEBUG level for more logs.")
    parser.add_argument("--log-file", default="", help="Optional path to log file.")
    parser.add_argument("--verbose-lh", action="store_true",
                        help="Pass --verbose to Lighthouse for extra Lighthouse logs.")

    # Timeout & multiple runs
    parser.add_argument("--per-url-timeout", type=int, default=120,
                        help="Max seconds allowed for each Lighthouse run (desktop/mobile). Default=120.")
    parser.add_argument("--runs-per-url", type=int, default=1,
                        help="Number of times to test each URL (desktop & mobile unless disabled). Default=1.")

    args, unknown_lh_flags = parser.parse_known_args()

    # Load optional config file and override defaults
    if args.config_file:
        try:
            with open(args.config_file, "r", encoding="utf-8") as cf:
                if args.config_file.endswith((".yaml", ".yml")) and yaml:
                    cfg = yaml.safe_load(cf)
                else:
                    cfg = json.load(cf)
            if isinstance(cfg, dict):
                for k, v in cfg.items():
                    if hasattr(args, k) and getattr(args, k) == parser.get_default(k):
                        setattr(args, k, v)
        except Exception as e:
            print(f"Failed to load config file {args.config_file}: {e}")

    # 1) Logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    handlers: list[Any] = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

    # If user wants LH verbose logs
    if args.verbose_lh and "--verbose" not in unknown_lh_flags:
        unknown_lh_flags.append("--verbose")

    logging.debug(f"Parsed CLI args: {args}")
    logging.debug(f"Unknown LH flags: {unknown_lh_flags}")

    # Ensure the top-level output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # 2) Gather URLs (single, CSV, or sitemaps)
    if args.url_target:
        # Single URL mode
        urls_to_process = [args.url_target.strip()]
        logging.debug(f"Single-URL mode: {urls_to_process}")
    elif args.csv_input_file:
        # CSV mode
        if not os.path.isfile(args.csv_input_file):
            logging.error(f"CSV file not found: {args.csv_input_file}")
            return
        urls_to_process = []
        logging.debug(f"Reading CSV: {args.csv_input_file}")
        with open(args.csv_input_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row and row[0].strip():
                    urls_to_process.append(row[0].strip())
        urls_to_process = urls_to_process[:args.max_urls]
        logging.debug(f"Loaded {len(urls_to_process)} URLs (capped at {args.max_urls}).")

    else:
        # Sitemap mode
        base_domain = args.base_url.strip()
        if not base_domain:
            logging.error("No --base-url, --url-target, or --csv-input-file given. Exiting.")
            return
        logging.debug(f"Fetching sitemaps for domain: {base_domain}")
        sitemaps = fetch_sitemaps_from_robots(f"http://{base_domain}")
        if not sitemaps:
            sitemaps = [
                f"http://{base_domain.rstrip('/')}/sitemap.xml",
                f"http://{base_domain.rstrip('/')}/sitemap_index.xml"
            ]
            logging.warning("No sitemaps discovered in robots.txt, using fallback patterns.")
        all_urls = set()
        for sm in sitemaps:
            all_urls.update(parse_sitemap(sm))
        urls_to_process = list(all_urls)[:args.max_urls]
        logging.debug(f"Discovered {len(all_urls)} unique URLs; "
                      f"capped at {args.max_urls} => {len(urls_to_process)} remain.")

    logging.info(f"Total URLs to process: {len(urls_to_process)}")

    # 3) Lighthouse path detection
    lighthouse_exe = get_lighthouse_path(args.lighthouse_path)
    logging.debug(f"Lighthouse executable: {lighthouse_exe}")

    # Determine domain label (for naming output CSV).
    if args.base_url:
        domain_label = args.base_url
    elif args.url_target:
        domain_label = get_domain_from_url(args.url_target)
    elif args.csv_input_file and urls_to_process:
        domain_label = get_domain_from_url(urls_to_process[0])
    else:
        domain_label = "bulk-scan"
    domain_label = domain_label.replace(":", "_").replace("/", "_").strip()

    # Prepare /reports folder and final CSV path
    report_dir = os.path.join(args.output_dir, "reports")
    os.makedirs(report_dir, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"{domain_label}-{timestamp_str}.csv"
    csv_output_path = os.path.join(report_dir, csv_filename)

    # ----------------------------------------------------------------------
    # 4) Detect prior run_X folders, so we don't overwrite old results
    # If you do multiple runs (e.g., run the script again), it auto-finds
    # the highest run_N folder and continues from run_(N+1) onward.
    # ----------------------------------------------------------------------
    existing_runs = [
        d for d in os.listdir(args.output_dir)
        if d.startswith("run_") and os.path.isdir(os.path.join(args.output_dir, d))
    ]
    max_run_found = 0
    for run_folder in existing_runs:
        try:
            num = int(run_folder.split("_")[1])
            if num > max_run_found:
                max_run_found = num
        except ValueError:
            continue

    # We start from (max_run_found+1) up to (max_run_found + runs_per_url)
    start_run = max_run_found + 1
    end_run = max_run_found + args.runs_per_url

    results = []

    try:
        for url in urls_to_process:
            for run_iter in range(start_run, end_run + 1):
                # Create subfolder for this run, e.g. "lighthouse_reports/run_2"
                run_subfolder = os.path.join(args.output_dir, f"run_{run_iter}")
                os.makedirs(run_subfolder, exist_ok=True)

                logging.info(f"RUN {run_iter} - Desktop: {url}")
                desktop_json = run_lighthouse(
                    url=url,
                    mode="desktop",
                    output_dir=run_subfolder,
                    lighthouse_exe=lighthouse_exe,
                    extra_flags=unknown_lh_flags,
                    timeout_secs=args.per_url_timeout
                )
                if desktop_json:
                    desk_data = extract_detailed_data(desktop_json, "desktop")
                    desk_data["run_iteration"] = run_iter
                    results.append(desk_data)
                else:
                    logging.debug(f"No desktop JSON for run={run_iter}: {url}")

                if not args.disable_mobile:
                    logging.info(f"RUN {run_iter} - Mobile: {url}")
                    mobile_json = run_lighthouse(
                        url=url,
                        mode="mobile",
                        output_dir=run_subfolder,
                        lighthouse_exe=lighthouse_exe,
                        extra_flags=unknown_lh_flags,
                        timeout_secs=args.per_url_timeout
                    )
                    if mobile_json:
                        mob_data = extract_detailed_data(mobile_json, "mobile")
                        mob_data["run_iteration"] = run_iter
                        results.append(mob_data)
                    else:
                        logging.debug(f"No mobile JSON for run={run_iter}: {url}")

    except KeyboardInterrupt:
        logging.warning("KeyboardInterrupt: Stopping early. Partial results will still be saved.")

    # 5) Save aggregated CSV with top 2 rows (avg desktop, avg mobile), then all runs
    if results:
        df = pd.DataFrame(results)

        # Convert numeric-like columns
        numeric_cols = [
            "performance_score",
            "accessibility_score",
            "best_practices_score",
            "seo_score",
            "timing_total",
            "first_contentful_paint",
            "largest_contentful_paint",
            "interactive",
            "speed_index",
            "total_blocking_time",
            "cumulative_layout_shift",
        ]
        for col in numeric_cols:
            if col in df.columns:
                # Parse the "displayValue" columns that might have strings like "1.2 s"
                if col in [
                    "first_contentful_paint", "largest_contentful_paint",
                    "interactive", "speed_index", "total_blocking_time",
                    "cumulative_layout_shift"
                ]:
                    df[col] = df[col].apply(parse_display_value)
                # Convert to numeric
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Separate Desktop & Mobile subsets
        desktop_df = df[df['mode'] == 'desktop']
        mobile_df = df[df['mode'] == 'mobile']

        # Compute the average for each group, even if there's only 1 row
        desktop_avg = desktop_df[numeric_cols].mean(numeric_only=True) if not desktop_df.empty else pd.Series()
        mobile_avg = mobile_df[numeric_cols].mean(numeric_only=True) if not mobile_df.empty else pd.Series()

        # Prepare row dicts
        desktop_row = {'mode': 'desktop-AVERAGE'}
        mobile_row  = {'mode': 'mobile-AVERAGE'}

        for col in df.columns:
            if col in ['mode']:
                continue
            if col in desktop_avg:
                desktop_row[col] = desktop_avg[col]
            else:
                desktop_row[col] = '---'

            if col in mobile_avg:
                mobile_row[col] = mobile_avg[col]
            else:
                mobile_row[col] = '---'

        avg_df = pd.DataFrame([desktop_row, mobile_row])
        final_df = pd.concat([avg_df, df], ignore_index=True)

        final_df.to_csv(csv_output_path, index=False)
        logging.info(f"Saved {len(df)} results (all runs) to {csv_output_path}")
        if args.db_uri:
            try:
                from sqlalchemy import create_engine
                engine = create_engine(args.db_uri)
                final_df.to_sql('lighthouse_results', engine, if_exists='append', index=False)
                logging.info("Results written to database")
            except Exception as e:
                logging.error(f"Failed to write to database: {e}")
    else:
        logging.warning("No successful Lighthouse runs, no CSV written.")

    logging.info("All audits complete.")

if __name__ == "__main__":
    main()
