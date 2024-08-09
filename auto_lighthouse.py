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
input_url = 'hhs.gov'
output_path = 'lighthouse_reports'
max_urls = 1
max_workers = 10 # 1-3 on a laptop, 3-10 on a desktop, 10-20 on a desktop with gigabit connection. (More = slower possible aggregate result, also a janky way to simulate a throttled device / connection)
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
lighthouse_path = os.path.join('C:/Users/palantir/AppData/Roaming/npm', 'lighthouse.cmd')

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def check_lighthouse_path():
    if not os.path.isfile(lighthouse_path):
        logging.critical(f"Lighthouse executable not found at {lighthouse_path}. Please ensure Lighthouse is installed and the path is correct.")
        raise FileNotFoundError(f"Lighthouse executable not found at {lighthouse_path}")

def get_valid_url(base_url):
    logging.info(f"Trying to get a valid URL for base URL: {base_url}")
    variants = [f'https://{base_url}', f'http://{base_url}', f'https://www.{base_url}', f'http://www.{base_url}']
    for url in variants:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                logging.info(f"Valid URL found: {url}")
                return url
        except requests.exceptions.RequestException:
            continue
    logging.warning(f"No valid URL found for base URL: {base_url}")
    return None

def clean_url(url):
    logging.info(f"Cleaning URL: {url}")
    parsed_url = urlparse(url)
    if not parsed_url.scheme:
        parsed_url = parsed_url._replace(scheme='http')
    if not parsed_url.netloc and parsed_url.path:
        parsed_url = parsed_url._replace(netloc=parsed_url.path, path='')
    return urlunparse(parsed_url)

def parse_sitemap(url):
    logging.info(f"Parsing sitemap: {url}")
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        sitemap_tags = soup.find_all('sitemap')
        if sitemap_tags:
            urls = []
            for sitemap in sitemap_tags:
                sitemap_url = sitemap.find('loc').text
                urls.extend(parse_sitemap(sitemap_url))
            return urls
        return [loc.text for loc in soup.find_all('loc') if is_html_page(loc.text)]
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error parsing sitemap {url}: {e}")
        return []
    except Exception as e:
        logging.error(f"Error parsing sitemap {url}: {e}")
        raise

def is_html_page(url):
    return any(url.lower().endswith(ext) for ext in ['.html', '.htm', '/'])

def run_lighthouse(url, output_path, mode):
    logging.info(f"Running Lighthouse for URL: {url} in {mode} mode")
    file_name = f"{output_path}/{url.replace('https://', '').replace('http://', '').replace('/', '_')}_{mode}.json"
    command = [
        lighthouse_path, url, '--output=json', f'--output-path={file_name}', 
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
        logging.info(f"Lighthouse completed for URL: {url} in {mode} mode")
        return file_name
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logging.error(f"Lighthouse command error for URL: {url} in {mode} mode: {e}")
        raise

# Function to extract detailed data
def extract_detailed_data(file_path, mode):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check if categories exist in the JSON
        categories = data.get('categories', {})
        if not categories:
            logging.warning(f"No categories found in JSON file: {file_path}")
        
        # Extract scores with default value if missing
        performance_score = categories.get('performance', {}).get('score', None)
        accessibility_score = categories.get('accessibility', {}).get('score', None)
        best_practices_score = categories.get('best-practices', {}).get('score', None)
        seo_score = categories.get('seo', {}).get('score', None)

        audits = data.get('audits', {})
        if not audits:
            logging.warning(f"No audits found in JSON file: {file_path}")
        
        # Flatten audit details, excluding any keys with 'description' or '_id'
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
            'performance_score': performance_score,
            'accessibility_score': accessibility_score,
            'best_practices_score': best_practices_score,
            'seo_score': seo_score,
            'first_contentful_paint': audits.get('first-contentful-paint', {}).get('displayValue', ''),
            'speed_index': audits.get('speed-index', {}).get('displayValue', ''),
            'largest_contentful_paint': audits.get('largest-contentful-paint', {}).get('displayValue', ''),
            'interactive': audits.get('interactive', {}).get('displayValue', ''),
            'total_blocking_time': audits.get('total-blocking-time', {}).get('displayValue', ''),
            'cumulative_layout_shift': audits.get('cumulative-layout-shift', {}).get('displayValue', ''),
            'top_20_slowest_scripts': "; ".join(get_top_slowest_scripts(audits)),
            'network_requests': "",
            'timing_total': data.get('timing', {}).get('total', 0),
            **audit_details  # Include all audit details, excluding descriptions and _id
        }
    except Exception as e:
        logging.error(f"Error extracting detailed data from {file_path}: {e}")
        return {}


def get_top_slowest_scripts(audits):
    logging.info("Getting top slowest scripts")
    try:
        script_timings = [(item['url'], item.get('duration', 0)) 
                          for item in audits.get('network-requests', {}).get('details', {}).get('items', []) 
                          if item.get('resourceType') == 'Script']
        sorted_scripts = sorted(script_timings, key=lambda x: x[1], reverse=True)[:20]
        return [script[0] for script in sorted_scripts]
    except Exception as e:
        logging.error(f"Error extracting slowest scripts: {e}")
        raise

def extract_network_requests(file_path):
    logging.info(f"Extracting network requests from file: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        requests = [entry['params']['request']['url'] for entry in data if entry['method'] == 'Network.requestWillBeSent']
        return "; ".join(requests)
    except Exception as e:
        logging.error(f"Error extracting network requests from {file_path}: {e}")
        raise

def filter_string_columns(df):
    string_columns = [col for col in df.columns if df[col].dtype == "object"]
    return df[string_columns]

logging.info(f"Starting script for input URL: {input_url}")
check_lighthouse_path()
base_url = get_valid_url(input_url)
if not base_url:
    logging.critical("No valid base URL found. Exiting.")
    raise Exception("No valid base URL found. Exiting.")

sitemap_urls = [f'{base_url.rstrip("/")}/sitemap.xml', f'{base_url.rstrip("/")}/sitemap_index.xml']
urls = []
for sitemap_url in sitemap_urls:
    try:
        urls.extend(parse_sitemap(clean_url(sitemap_url)))
    except Exception as e:
        logging.error(f"Skipping sitemap due to error: {e}")

urls = list(set(url for url in urls if is_html_page(url)))
logging.info(f"Total unique HTML URLs collected: {len(urls)}")
if not urls:
    logging.critical("No URLs found in any sitemap. Exiting.")
    raise Exception("No URLs found in any sitemap.")

urls = urls[:max_urls]

os.makedirs(output_path, exist_ok=True)
results = []

def process_url(url, mode):
    try:
        report = run_lighthouse(url, output_path, mode)
        data = extract_detailed_data(report, mode)
        data['network_requests'] = extract_network_requests(report.replace('.json', '-0.devtoolslog.json'))
        return data
    except Exception as e:
        logging.error(f"Error processing URL {url} in {mode} mode: {e}")
        return {}

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
df = filter_string_columns(df)
df.to_csv('lighthouse_summary.csv', index=False)
logging.info("Summary saved as lighthouse_summary.csv")

# for file in os.listdir(output_path):
#     if file.endswith('.json'):
#         os.remove(os.path.join(output_path, file))
# logging.info("All JSON files have been deleted.")
