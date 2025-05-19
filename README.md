# Lighthouse Bulk Audit Script

This script automates running Google Lighthouse audits across a large set of URLs in parallel. It can scrape sitemaps for URLs or accept a list of URLs from a CSV file, then run both **desktop** and **mobile** Lighthouse analyses, and finally compile the results into a CSV summary.

The latest version includes:

- Optional YAML/JSON configuration files (`--config-file`)
- Ability to write results to a database via `--db-uri`
- Command line entry point via `pyproject.toml`
- Configurable log file path (`--log-file`)
- Basic unit tests using `pytest`

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Script Overview](#script-overview)
4. [Configuration Flags & Variables](#configuration-flags--variables)
5. [Usage Examples](#usage-examples)
6. [Outputs](#outputs)
7. [Known Limitations / Caveats](#known-limitations--caveats)
8. [Troubleshooting](#troubleshooting)
9. [License](#license)

----

## Prerequisites

- **Python 3.7+** installed.
- **Lighthouse** (CLI) installed globally via npm (Node.js).

    ```bash
    npm install -g lighthouse
    ```

    or

    ```bash
    yarn global add lighthouse
    ```

- Additional Python libraries (install via `pip install -r requirements.txt` if you create a requirements.txt from the script's imports):
    - pandas
    - bs4 (beautifulsoup4)
    - requests
    - tqdm
    - PyYAML
    - SQLAlchemy
    - logging (part of the Python standard library, so no extra install needed)

----

## Installation

1. **Clone or copy** this repository into a folder of your choice.
2. **Install** the Python dependencies listed above:

    ```bash
    pip install -r requirements.txt
    ```

3. **Verify** that you have Lighthouse installed and in your system path:

    ```bash
    lighthouse --version
    ```

    If the command runs, you're set. Otherwise, install it or specify a custom path in `lighthouse_path` (see below).

----

## Script Overview

1. **Find & Collect URLs**

    - If `csv_input_file` is provided, the script will read URLs from that file (column A).
    - Otherwise, it will attempt to locate a valid base URL (e.g., `https://example.com`) and parse its sitemaps at:

        ```bash
        /sitemap.xml
        /sitemap_index.xml
        ```

    - Collects a maximum of `max_urls`.
2. **Run Lighthouse**

    - For each URL, it runs Lighthouse in **desktop** and **mobile** modes.
    - The script includes a concurrency limit (`max_workers`) to parallelize runs.
3. **Save Outputs**

    - Every Lighthouse run generates a JSON report file in the `output_path`.
    - A CSV summary (`lighthouse_summary.csv`) aggregates key metrics (performance/accessibility/best-practices/SEO) plus extra fields like TBT, LCP, etc.
4. **Cleanup**

    - Optionally, you can decide if you want to keep or remove those JSON files.
    - The script logs every step and writes out a final summary CSV of all runs.

----

## Configuration Flags & Variables

These top-level variables are **user-configurable** in the script:

| Variable          | Default              | Description |
| ----------------- | -------------------- | ----------- |
| **input_url**     | 'stopbullying.gov'   | The base domain to fetch. The script tries standard protocols (https://, http://, https://www., etc.) until one returns a valid response (status 200). Only used if no CSV file is specified. |
| **output_path**   | 'lighthouse_reports' | Directory where Lighthouse reports (.json) are saved. The script creates the directory if it doesn't exist. |
| **max_urls**      | 99999                | The maximum number of URLs to audit from all discovered sitemaps or the CSV file. Setting a high number (e.g., 99999) effectively means "no limit." |
| **max_workers**   | 10                   | Maximum concurrency. More workers = more parallel Lighthouse runs. This can speed up the process but may increase CPU usage and bandwidth needs. |
| **headers**       | {'User-Agent': ...}  | Custom request headers used for all requests.get() calls, primarily to fetch sitemaps. |
| **lighthouse_path** | '' (empty)         | The path to the Lighthouse CLI executable. If empty, the script tries known default locations (e.g., %APPDATA%\npm\lighthouse.cmd on Windows, or ~/.npm-global/bin/lighthouse). If not found, raises error. |
| **csv_input_file**| '' (empty)           | If set, the script will **not** parse sitemaps and instead load URLs from this CSV file. The first column (column A) in that CSV is expected to contain the URLs. |

### Script Flags & Behavior

There is no "true" command-line flag parsing mechanism in the script as-is. Instead, you edit these variables in the script to fit your environment. However, here's how each variable changes behavior:

1. **input_url**

    - This is the domain or site to test if you're **not** using a CSV file.
    - Example: `input_url = 'example.com'`
2. **csv_input_file**

    - If non-empty (e.g., `csv_input_file = 'my_urls.csv'`), the script ignores input_url and sitemaps.
    - The script will read column A of `my_urls.csv` for the list of URLs to test.
3. **max_urls**

    - Limits how many URLs you test in total. If you have a massive sitemap or a large CSV, reduce this to keep testing short.
4. **max_workers**

    - Controls concurrency: how many Lighthouse runs happen simultaneously.
    - On lower-powered machines, consider setting `max_workers` to 1--3. On more powerful desktops or servers, 10+ might be fine.
5. **output_path**

    - Where .json reports are stored. Also used to store final CSV summary in the script's root directory (`lighthouse_summary.csv`) so you can keep them separate.
6. **lighthouse_path**

    - If you want to direct the script to a **specific** Lighthouse installation, set the absolute path here. e.g., "/usr/local/bin/lighthouse" on Linux or C:/Users/Name/AppData/Roaming/npm/lighthouse.cmd on Windows.
7. **Mobile vs. Desktop Mode**

    - The script automatically runs both modes. For each URL, it calls `--emulated-form-factor=mobile` or `--preset=desktop`. That yields two JSON outputs per URL.

----

## Usage Examples

### **1. Default usage**

In the script:

```python
input_url = 'stopbullying.gov'
csv_input_file = ''
max_urls = 99999
max_workers = 10
lighthouse_path = ''
output_path = 'lighthouse_reports'
```

Then just run:

```bash
python -m lighthouse_bulk_scan.cli
```

- The script will:
    - Attempt `https://stopbullying.gov`, `http://stopbullying.gov`, etc.
    - Fetch `stopbullying.gov/sitemap.xml` and `stopbullying.gov/sitemap_index.xml`.
    - Collect up to 99,999 URLs from the sitemaps.
    - Run Lighthouse on each URL (desktop & mobile).
    - Write JSON files to `lighthouse_reports/` plus a final `lighthouse_summary.csv` in the same directory as the script.

### **2. Use a custom CSV**

Suppose you have `my_urls.csv` containing specific links (one per line in column A).

```python
input_url = ''
csv_input_file = 'my_urls.csv'
max_urls = 100
max_workers = 5
lighthouse_path = ''  # Let the script auto-detect
output_path = 'my_lh_reports'
```

Then run:

```bash
python -m lighthouse_bulk_scan.cli
```

- The script **ignores** any sitemaps and uses `my_urls.csv`.
- It audits only the first 100 URLs due to `max_urls=100`.
- Uses `concurrency=5`.
- Writes to `my_lh_reports/`.

### **3. Specify Lighthouse Path**

If the script can't auto-detect your Lighthouse location, you can set:

```python
lighthouse_path = '/usr/local/bin/lighthouse'  # Example for Linux/Mac
```

and run:

```bash
python -m lighthouse_bulk_scan.cli
```

----

## Outputs

1. **lighthouse_reports/** (or whatever you set `output_path` to)

    - Contains JSON reports named like `example.com_about_us_mobile.json` or `example.com_about_us_desktop.json`.
    - Each file includes the raw Lighthouse result for that page.
2. **urls_tested.csv**

    - A list of all final URLs that were tested (in case you need to track which URLs actually got processed).
3. **lighthouse_summary.csv**

    - A table of performance metrics for all pages, such as performance score, accessibility score, LCP, TBT, and more.
    - Each URL will appear with both a "desktop" and "mobile" row.

----

## Known Limitations / Caveats

- Lighthouse must be installed separately via `npm install -g lighthouse`.
- The optional database table (`lighthouse_results`) must exist beforehand.
- Large sites can take a long time to audit.
## Testing
Run `pytest` to execute unit tests.

