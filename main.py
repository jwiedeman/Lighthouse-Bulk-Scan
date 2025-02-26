import os
import csv
import logging
import argparse
import pandas as pd

from sitemap_parser import fetch_sitemaps_from_robots, parse_sitemap
from lighthouse_runner import get_lighthouse_path, run_lighthouse
from report_parser import extract_detailed_data

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

    # Limits & outputs
    parser.add_argument("--max-urls", type=int, default=99999,
                        help="Max URLs to process from CSV/sitemaps. Default=99999.")
    parser.add_argument("--output-dir", default="lighthouse_reports",
                        help="Top-level directory for storing Lighthouse JSON outputs.")
    parser.add_argument("--csv-output", default="lighthouse_summary.csv",
                        help="File path for the final CSV results.")

    # Lighthouse & logging
    parser.add_argument("--lighthouse-path", default="",
                        help="Path to Lighthouse if not on the system PATH.")
    parser.add_argument("--disable-mobile", action="store_true",
                        help="Disable mobile mode (only run desktop).")
    parser.add_argument("--debug", action="store_true",
                        help="Set Python logger to DEBUG level for more logs.")
    parser.add_argument("--verbose-lh", action="store_true",
                        help="Pass --verbose to Lighthouse for extra Lighthouse logs.")

    # Timeout & multiple runs
    parser.add_argument("--per-url-timeout", type=int, default=120,
                        help="Max seconds allowed for each Lighthouse run (desktop/mobile). Default=120.")
    parser.add_argument("--runs-per-url", type=int, default=1,
                        help="Number of times to test each URL (desktop & mobile unless disabled). Default=1.")

    args, unknown_lh_flags = parser.parse_known_args()

    # 1) Logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
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

    # 4) Main loop: multiple runs, each stored in a subfolder
    results = []
    runs_per_url = args.runs_per_url

    try:
        for url in urls_to_process:
            for run_iter in range(1, runs_per_url + 1):
                # Create subfolder for this run, e.g. "lighthouse_reports/run_1"
                run_subfolder = os.path.join(args.output_dir, f"run_{run_iter}")
                os.makedirs(run_subfolder, exist_ok=True)

                logging.info(f"RUN {run_iter}/{runs_per_url} - Desktop: {url}")
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
                    # Mark which run iteration this result came from
                    desk_data["run_iteration"] = run_iter
                    results.append(desk_data)
                else:
                    logging.debug(f"No desktop JSON for run={run_iter}: {url}")

                if not args.disable_mobile:
                    logging.info(f"RUN {run_iter}/{runs_per_url} - Mobile: {url}")
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

    # 5) Save aggregated CSV
    if results:
        df = pd.DataFrame(results)
        df.to_csv(args.csv_output, index=False)
        logging.info(f"Saved {len(results)} results (all runs) to {args.csv_output}")
    else:
        logging.warning("No successful Lighthouse runs, no CSV written.")

    logging.info("All audits complete.")

if __name__ == "__main__":
    main()
