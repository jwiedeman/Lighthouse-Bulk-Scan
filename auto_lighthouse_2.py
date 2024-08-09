import os
import json
import subprocess
import pandas as pd
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import logging

# User-configurable variables
input_url = 'stopbullying.gov'
output_path = 'lighthouse_reports'
max_urls = 99999 # how many urls to grab from sitemap, 99999 for all urls
max_workers = 10
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
lighthouse_path = ''  # Leave empty for auto-detection, or add your lighthouse PATH
csv_input_file = ''  # Optional CSV file containing URLs to test instead of using sitemaps, COL A list of urls expected

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_lighthouse_path():
    """Returns the path to the Lighthouse executable, checking default locations if not manually specified."""
    if lighthouse_path:
        return lighthouse_path
    default_paths = [
        os.path.join(os.getenv('APPDATA', ''), 'npm', 'lighthouse.cmd'),
        os.path.join(os.getenv('LOCALAPPDATA', ''), 'npm', 'lighthouse.cmd'),
        os.path.join(os.getenv('HOME', ''), '.npm-global', 'bin', 'lighthouse')
    ]
    for path in default_paths:
        if os.path.isfile(path):
            return path
    logging.critical("Lighthouse executable not found. Please ensure Lighthouse is installed.")
    raise FileNotFoundError("Lighthouse executable not found.")

def get_valid_url(base_url):
    """Attempts to find a valid URL from common variants."""
    variants = [f'https://{base_url}', f'http://{base_url}', f'https://www.{base_url}', f'http://www.{base_url}']
    for url in variants:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return url
        except requests.exceptions.RequestException:
            continue
    logging.warning(f"No valid URL found for base URL: {base_url}")
    return None

def clean_url(url):
    """Cleans up URL to ensure it has a proper scheme and netloc."""
    parsed_url = urlparse(url)
    if not parsed_url.scheme:
        parsed_url = parsed_url._replace(scheme='http')
    if not parsed_url.netloc and parsed_url.path:
        parsed_url = parsed_url._replace(netloc=parsed_url.path, path='')
    return urlunparse(parsed_url)

def parse_sitemap(url):
    """Parses sitemap XML to extract URLs, recursively if needed."""
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        sitemap_tags = soup.find_all('sitemap')
        if sitemap_tags:
            return [url for sitemap in sitemap_tags for url in parse_sitemap(sitemap.find('loc').text)]
        return [tag.find('loc').text for tag in soup.find_all('url') if is_html_page(tag.find('loc').text)]
    except Exception as e:
        logging.error(f"Error parsing sitemap {url}: {e}")
        return []

def is_html_page(url):
    """Determines if a URL likely points to an HTML page by checking its extension."""
    non_html_extensions = (
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.zip', '.rar', '.exe', '.dmg', '.mp3', '.mp4', '.avi', '.mov',
        '.flv', '.wmv', '.mkv', '.ogg', '.ogv', '.webm', '.mpg', '.mpeg'
    )
    return not any(url.lower().endswith(ext) for ext in non_html_extensions)

def run_lighthouse(url, mode):
    """Runs Lighthouse audit for a given URL and mode."""
    file_name = f"{output_path}/{url.replace('https://', '').replace('http://', '').replace('/', '_')}_{mode}.json"
    command = [
        get_lighthouse_path(), url, '--output=json', f'--output-path={file_name}', 
        '--only-categories=performance,accessibility,best-practices,seo', '--save-assets'
    ]
    if mode == 'mobile':
        command.extend(['--emulated-form-factor=mobile', '--screenEmulation.width=375', 
                        '--screenEmulation.height=667', '--screenEmulation.deviceScaleFactor=2', 
                        '--screenEmulation.mobile'])
    else:
        command.append('--preset=desktop')
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return file_name
    except subprocess.CalledProcessError as e:
        logging.error(f"Lighthouse command error for URL: {url} in {mode} mode: {e}")
        return None

def extract_detailed_data(file_path, mode):
    """Extracts detailed data from Lighthouse JSON report."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        categories = data.get('categories', {})
        audits = data.get('audits', {})
        audit_details = {f"{audit_id}_{detail_key}": detail_value 
                         for audit_id, audit in audits.items() 
                         for detail_key, detail_value in audit.items() 
                         if 'description' not in detail_key and '_id' not in detail_key}
        return {
            'url': data.get('finalDisplayedUrl', ''),
            'mode': mode,
            'lighthouse_version': data.get('lighthouseVersion', ''),
            'fetch_time': data.get('fetchTime', ''),
            'user_agent': data.get('userAgent', ''),
            'requested_url': data.get('requestedUrl', ''),
            'main_document_url': data.get('mainDocumentUrl', ''),
            'final_displayed_url': data.get('finalDisplayedUrl', ''),
            'performance_score': categories.get('performance', {}).get('score', None),
            'accessibility_score': categories.get('accessibility', {}).get('score', None),
            'best_practices_score': categories.get('best-practices', {}).get('score', None),
            'seo_score': categories.get('seo', {}).get('score', None),
            'first_contentful_paint': audits.get('first-contentful-paint', {}).get('displayValue', ''),
            'speed_index': audits.get('speed-index', {}).get('displayValue', ''),
            'largest_contentful_paint': audits.get('largest-contentful-paint', {}).get('displayValue', ''),
            'interactive': audits.get('interactive', {}).get('displayValue', ''),
            'total_blocking_time': audits.get('total-blocking-time', {}).get('displayValue', ''),
            'cumulative_layout_shift': audits.get('cumulative-layout-shift', {}).get('displayValue', ''),
            'top_20_slowest_scripts': "; ".join(get_top_slowest_scripts(audits)),
            'network_requests': extract_network_requests(file_path.replace('.json', '-0.devtoolslog.json')),
            'timing_total': data.get('timing', {}).get('total', 0),
            **audit_details
        }
    except Exception as e:
        logging.error(f"Error extracting detailed data from {file_path}: {e}")
        return {}

def get_top_slowest_scripts(audits):
    """Extracts the top 20 slowest scripts from the audits."""
    try:
        script_timings = [(item['url'], item.get('duration', 0)) 
                          for item in audits.get('network-requests', {}).get('details', {}).get('items', []) 
                          if item.get('resourceType') == 'Script']
        sorted_scripts = sorted(script_timings, key=lambda x: x[1], reverse=True)[:20]
        return [script[0] for script in sorted_scripts]
    except Exception as e:
        logging.error(f"Error extracting slowest scripts: {e}")
        return []

def extract_network_requests(file_path):
    """Extracts network requests from the Lighthouse devtools log."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        requests = [entry['params']['request']['url'] for entry in data if entry['method'] == 'Network.requestWillBeSent']
        return "; ".join(requests)
    except Exception as e:
        logging.error(f"Error extracting network requests from {file_path}: {e}")
        return ""

def load_urls_from_csv(csv_file):
    """Loads URLs from a specified CSV file."""
    try:
        df = pd.read_csv(csv_file)
        urls = df.iloc[:, 0].dropna().tolist()
        return urls
    except Exception as e:
        logging.error(f"Error loading URLs from CSV file {csv_file}: {e}")
        return []

def main():
    logging.info(f"Starting script for input URL: {input_url}")
    os.makedirs(output_path, exist_ok=True)

    if csv_input_file:
        urls = load_urls_from_csv(csv_input_file)
        logging.info(f"Loaded {len(urls)} URLs from {csv_input_file}")
    else:
        base_url = get_valid_url(input_url)
        if not base_url:
            logging.critical("No valid base URL found. Exiting.")
            return
        sitemap_urls = [f'{base_url.rstrip("/")}/sitemap.xml', f'{base_url.rstrip("/")}/sitemap_index.xml']
        urls = []
        for sitemap_url in sitemap_urls:
            urls.extend(parse_sitemap(clean_url(sitemap_url)))

    urls = list(set(urls))[:max_urls]
    logging.info(f"Total unique HTML URLs collected: {len(urls)}")

    if not urls:
        logging.critical("No URLs found. Exiting.")
        return

    with open('urls_tested.csv', 'w') as f:
        f.write('\n'.join(urls))
    logging.info("Tested URLs saved as urls_tested.csv")

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_url, url, mode) for url in urls for mode in ('desktop', 'mobile')]
        with tqdm(total=len(futures), dynamic_ncols=True) as pbar:
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)
                    pbar.set_postfix_str(f"Processing: {result['url']} ({result['mode']})")
                pbar.update(1)

    df = pd.DataFrame(results)
    df.to_csv('lighthouse_summary.csv', index=False)
    logging.info("Summary saved as lighthouse_summary.csv")

def process_url(url, mode):
    """Process each URL by running Lighthouse and extracting data."""
    try:
        report = run_lighthouse(url, mode)
        if report:
            return extract_detailed_data(report, mode)
    except Exception as e:
        logging.error(f"Error processing URL {url} in {mode} mode: {e}")
    return {}

if __name__ == '__main__':
    main()
