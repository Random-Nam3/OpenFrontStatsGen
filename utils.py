#!/usr/bin/env python3
"""
OpenFront Stats Generator - Shared Utilities
Contains helper functions for API requests, logging, datetime parsing, and manifest caching.
"""

import os
import sys
import json
import urllib.request
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

# Public API endpoints
API_BASE_URL = "https://api.openfront.io/public"
RESOURCES_BASE_URL = "https://raw.githubusercontent.com/openfrontio/OpenFrontIO/main/resources"
CACHE_DIR = "map_cache"

def log_err(msg: str):
    """Logs warning/error messages with a timestamp prefix to stderr."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    newlines = ""
    while msg.startswith("\n"):
        newlines += "\n"
        msg = msg[1:]
    print(f"{newlines}[{now_str}] {msg}", file=sys.stderr)

def get_map_slug(map_name: str) -> str:
    """Standardizes map name into a lowercase alphanumeric slug."""
    return "".join(c for c in map_name if c.isalnum()).lower()

def parse_iso_datetime(dt_str: str) -> datetime:
    """Parses ISO 8601 datetime strings robustly across different Python versions."""
    if not dt_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    normalized = dt_str
    if normalized.endswith('Z'):
        normalized = normalized[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        try:
            if '.' in normalized:
                base, frac = normalized.split('.')
                tz = '+' + frac.split('+')[1] if '+' in frac else ''
                normalized = base + tz
            return datetime.strptime(normalized.split('+')[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

def make_request(url: str) -> dict:
    """Helper to perform HTTP GET requests to the API with custom user agent and robust error handling."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OpenFrontStatsGen/1.0 (Python data analysis script)",
            "Accept": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        if e.code == 429:
            log_err("Error: Rate limit exceeded (HTTP 429).")
            log_err("OpenFront API has strict rate limits. Please wait before running the script again.")
            log_err("Join the Discord (https://discord.gg/K9zernJB5z) to request higher rate limits.")
        else:
            log_err(f"API Error: HTTP status code {e.code} - {e.reason}")
        sys.exit(1)
    except URLError as e:
        log_err(f"Network Error: Failed to reach the API server: {e.reason}")
        sys.exit(1)
    except Exception as e:
        log_err(f"Unexpected Error: {e}")
        sys.exit(1)

def fetch_map_manifest(map_name: str) -> dict:
    """Fetches (or loads from local cache) the manifest.json for a map from OpenFront raw CDN."""
    slug = get_map_slug(map_name)
    cache_file = os.path.join(CACHE_DIR, f"{slug}_manifest.json")
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_err(f"Warning: Could not read cached manifest from {cache_file}: {e}")
            
    url = f"{RESOURCES_BASE_URL}/maps/{slug}/manifest.json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OpenFrontStatsGen/1.0"}
    )
    try:
        if VERBOSE:
            print(f"Fetching manifest for map slug '{slug}'...", file=sys.stderr)
        with urllib.request.urlopen(req, timeout=5) as response:
            raw_data = response.read().decode('utf-8')
            manifest = json.loads(raw_data)
            
        # Save to cache
        os.makedirs(CACHE_DIR, exist_ok=True)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(raw_data)
        except Exception as cache_err:
            log_err(f"Warning: Could not write cache file {cache_file}: {cache_err}")
            
        return manifest
    except Exception as e:
        log_err(f"Warning: Could not fetch manifest for '{slug}': {e}.")
    return {}
