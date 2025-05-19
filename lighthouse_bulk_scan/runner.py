"""Helpers for running the Lighthouse CLI."""

import os
import subprocess
import logging
import tempfile
import time
from typing import Optional

def get_lighthouse_path(custom_path: str = "") -> str:
    """
    Return the absolute path to the Lighthouse CLI executable in a
    platform-agnostic manner.
    """
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    likely_paths = [
        os.path.join(os.getenv('APPDATA', ''), 'npm', 'lighthouse.cmd'),
        os.path.join(os.getenv('LOCALAPPDATA', ''), 'npm', 'lighthouse.cmd'),
        os.path.join(os.getenv('HOME', ''), '.npm-global', 'bin', 'lighthouse'),
        "lighthouse"
    ]

    for path in likely_paths:
        if path and os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Could not locate Lighthouse. Please install globally or specify --lighthouse-path."
    )

def run_lighthouse(
    url: str,
    mode: str,
    output_dir: str,
    lighthouse_exe: str,
    extra_flags: list[str],
    timeout_secs: int = 120
) -> Optional[str]:
    """
    Run Lighthouse on Windows/Mac/Linux without ephemeral random profiles.
    1) Use a persistent user-data-dir so we don't rely on ephemeral folders that get locked.
    2) Sleep briefly after the run to avoid Windows holding file locks.
    3) Return path to JSON or None if LH fails/times out.
    """

    # Hardcode a persistent user-data-dir:
    #   On Windows, e.g. C:\lighthouse_profile
    #   On Mac/Linux, e.g. /tmp/lighthouse_profile
    # (You can also let the user choose a path via CLI if you like.)
    custom_profile_dir = r"C:\lighthouse_profile" if os.name == "nt" else "/tmp/lighthouse_profile"

    # If user didn't supply --chrome-flags, we'll use our set
    if not any("--chrome-flags" in f for f in extra_flags):
        default_flags = [
            "--headless",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            f'--user-data-dir="{custom_profile_dir}"'
        ]
        extra_flags.append(f'--chrome-flags="{" ".join(default_flags)}"')

    # Build a sanitized output filename
    safe_url = (
        url.replace("https://", "")
           .replace("http://", "")
           .replace("/", "_")
           .replace("?", "_")
           .replace("&", "_")
           .replace(":", "_")
    )
    out_file = os.path.join(output_dir, f"{safe_url}_{mode}.json")

    # Base LH command
    cmd = [
        lighthouse_exe,
        url,
        "--output=json",
        f"--output-path={out_file}",
        "--only-categories=performance,accessibility,best-practices,seo",
        "--save-assets",
        "--disable-storage-reset"  # don't forcibly remove user-data
    ]

    # Add mobile or desktop flags
    if mode == "mobile":
        cmd.extend([
            "--emulated-form-factor=mobile",
            "--screenEmulation.width=375",
            "--screenEmulation.height=667",
            "--screenEmulation.deviceScaleFactor=2",
            "--screenEmulation.mobile"
        ])
    else:
        cmd.append("--preset=desktop")

    # Append any unknown LH flags (e.g., --verbose)
    cmd.extend(extra_flags)

    logging.debug(f"Full Lighthouse command: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=timeout_secs
        )
        logging.debug(f"--- LH STDOUT ---\n{proc.stdout}")
        logging.debug(f"--- LH STDERR ---\n{proc.stderr}")

        # *** Post-run sleep *** to let Windows release file locks
        time.sleep(2)

        return out_file

    except subprocess.TimeoutExpired as e:
        logging.error(f"Lighthouse timed out after {timeout_secs}s ({mode}): {url}")
        logging.error(f"--- STDOUT (partial) ---\n{e.stdout}")
        logging.error(f"--- STDERR (partial) ---\n{e.stderr}")
        return None

    except subprocess.CalledProcessError as e:
        logging.error(f"Lighthouse error (exit code != 0) for {url} ({mode}): {e}")
        logging.error(f"--- STDOUT ---\n{e.stdout}")
        logging.error(f"--- STDERR ---\n{e.stderr}")
        return None
