# report_parser.py
import json
import logging
from typing import Dict, Any

def extract_detailed_data(report_path: str, mode: str) -> Dict[str, Any]:
    """
    Read the Lighthouse JSON report and extract a handful of useful metrics.
    """
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        categories = data.get('categories', {})
        audits = data.get('audits', {})

        return {
            'mode': mode,
            'url': data.get('finalDisplayedUrl', ''),
            'requested_url': data.get('requestedUrl', ''),
            'lighthouse_version': data.get('lighthouseVersion', ''),
            'fetch_time': data.get('fetchTime', ''),
            'performance_score': categories.get('performance', {}).get('score'),
            'accessibility_score': categories.get('accessibility', {}).get('score'),
            'best_practices_score': categories.get('best-practices', {}).get('score'),
            'seo_score': categories.get('seo', {}).get('score'),
            'first_contentful_paint': audits.get('first-contentful-paint', {}).get('displayValue', ''),
            'largest_contentful_paint': audits.get('largest-contentful-paint', {}).get('displayValue', ''),
            'interactive': audits.get('interactive', {}).get('displayValue', ''),
            'speed_index': audits.get('speed-index', {}).get('displayValue', ''),
            'total_blocking_time': audits.get('total-blocking-time', {}).get('displayValue', ''),
            'cumulative_layout_shift': audits.get('cumulative-layout-shift', {}).get('displayValue', ''),
            'timing_total': data.get('timing', {}).get('total', 0)
        }
    except Exception as e:
        logging.error(f"Error reading Lighthouse report {report_path}: {e}")
        return {}
