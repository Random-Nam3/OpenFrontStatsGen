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
import csv


VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

# Public API endpoints
API_BASE_URL = os.environ.get("OPENFRONT_API_URL", "https://api.openfront.io/public")
RESOURCES_BASE_URL = "https://raw.githubusercontent.com/openfrontio/OpenFrontIO/main/resources"
CACHE_DIR = "map_cache"
GAME_CACHE_DIR = "game_cache"

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

def make_request(url: str, exit_on_error: bool = True) -> dict:
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
        if exit_on_error:
            sys.exit(1)
        raise
    except URLError as e:
        log_err(f"Network Error: Failed to reach the API server: {e.reason}")
        if exit_on_error:
            sys.exit(1)
        raise
    except Exception as e:
        log_err(f"Unexpected Error: {e}")
        if exit_on_error:
            sys.exit(1)
        raise

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

def extract_winner_client_id(game_info: dict) -> tuple:
    """
    Extracts the winner's client ID and username from detailed game info.
    Handles various formats including ['player', client_id] list format.
    """
    info = game_info.get("info", {})
    players = info.get("players", [])
    winner_val = info.get("winner") or game_info.get("winner") or game_info.get("winners")
    
    winner_client_id = None
    winner_name = "Unknown"
    
    if winner_val:
        # Check list format, e.g., ['player', 'czt89Z5u']
        if isinstance(winner_val, list):
            for item in winner_val:
                if isinstance(item, str) and len(item) == 8:
                    winner_client_id = item
                    break
        elif isinstance(winner_val, dict):
            winner_client_id = winner_val.get("clientID") or winner_val.get("id")
        elif isinstance(winner_val, str):
            winner_client_id = winner_val
            
    # If we have a winner client ID, resolve the username
    if winner_client_id:
        for p in players:
            if isinstance(p, dict) and p.get("clientID") == winner_client_id:
                winner_name = p.get("username", "Unknown")
                break
    else:
        # Fallback heuristic: search players for place = 1 or win flag
        for p in players:
            if not isinstance(p, dict):
                continue
            is_win = any(p.get(k) is True for k in ["hasWon", "won", "winning", "isWinner"])
            is_first = any(str(p.get(k)) == "1" for k in ["place", "rank", "position"])
            if is_win or is_first:
                winner_client_id = p.get("clientID")
                winner_name = p.get("username", "Unknown")
                break
                
    return winner_client_id, winner_name

def resolve_spawn_coordinates(map_name: str, tile_index: int, config: dict = None) -> tuple:
    """
    Fetches (or loads from local cache) the map manifest, determines the grid size based on game 
    config (compact/normal/tiny) or a heuristic, calculates (x, y) coordinates, and scales them 
    to the base map resolution.
    """
    manifest = fetch_map_manifest(map_name)
    if not manifest:
        return None, None

    # Get base map dimensions
    base_dim = manifest.get("map", {})
    base_w = base_dim.get("width", 2048)
    base_h = base_dim.get("height", 1024)
    
    # Determine the resolution of the grid for this specific match
    resolution_key = "map"
    if config:
        map_size = config.get("gameMapSize")
        is_compact = config.get("publicGameModifiers", {}).get("isCompact", False)
        
        if map_size == "Compact" or is_compact:
            resolution_key = "map4x"
        elif map_size == "Tiny":
            resolution_key = "map16x"
    else:
        # Heuristic fallback for when config is not available (e.g. parsing old CSV entries)
        map4x = manifest.get("map4x", {})
        w_4x = map4x.get("width")
        h_4x = map4x.get("height")
        if w_4x and h_4x and tile_index < (w_4x * h_4x):
            resolution_key = "map4x"
            
    res_dim = manifest.get(resolution_key, {})
    res_w = res_dim.get("width")
    res_h = res_dim.get("height")
    
    if not res_w or not res_h:
        res_w = base_w
        res_h = base_h
        
    # Calculate coordinates on the match grid
    x_grid = tile_index % res_w
    y_grid = tile_index // res_w
    
    # Scale coordinates to match the base map resolution
    scale_x = base_w / res_w
    scale_y = base_h / res_h
    
    x_base = int(x_grid * scale_x)
    y_base = int(y_grid * scale_y)
    
    return x_base, y_base

def load_game_ids_from_csv(csv_path: str) -> set:
    """Reads the first column (gameID) of a CSV file and returns a set of game IDs."""
    return set(load_game_ids_list_from_csv(csv_path))

def load_game_ids_list_from_csv(csv_path: str) -> list:
    """Reads the first column (gameID) of a CSV file and returns a list of game IDs in order."""
    game_ids = []
    if os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0:
        try:
            with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    if row and len(row) > 0:
                        game_ids.append(row[0].strip())
        except Exception as e:
            log_err(f"Warning: Could not read CSV {csv_path}: {e}")
    return game_ids

def serialize_dict_to_str(d: dict) -> str:
    """Serializes a dictionary of statistics (e.g. {'city': 5}) into a key:value string (e.g. 'city:5,fact:2')."""
    return ",".join(f"{k}:{v}" for k, v in sorted(d.items()))

def parse_and_accumulate_stats(stats_str: str, target_dict: dict):
    """Parses a serialized statistics string and adds the values to the target dictionary."""
    if not stats_str:
        return
    for item in stats_str.split(","):
        if ":" in item:
            parts = item.split(":", 1)
            k = parts[0].strip()
            v_str = parts[1].strip()
            try:
                target_dict[k] = target_dict.get(k, 0) + int(v_str)
            except ValueError:
                pass


def fetch_game_details(game_id: str) -> dict:
    """Fetches (or loads from local cache) the details for a game ID from the API."""
    os.makedirs(GAME_CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(GAME_CACHE_DIR, f"{game_id}.json")
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_err(f"Warning: Could not read cached game details from {cache_file}: {e}")
            
    url = f"{API_BASE_URL}/game/{game_id}"
    if VERBOSE:
        print(f"Fetching details for game '{game_id}' from API...", file=sys.stderr)
        
    game_info = make_request(url, exit_on_error=False)
    
    # Save to cache if request succeeded
    if game_info:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(game_info, f, indent=2)
        except Exception as cache_err:
            log_err(f"Warning: Could not write cache file {cache_file}: {cache_err}")
            
    return game_info


def load_existing_game_ids(directory: str) -> set:
    """Reads all CSV files in the directory and returns a set of gameIDs already processed."""
    existing_ids = set()
    if os.path.isdir(directory):
        try:
            for filename in os.listdir(directory):
                if filename.endswith(".csv"):
                    csv_path = os.path.join(directory, filename)
                    existing_ids.update(load_game_ids_from_csv(csv_path))
        except Exception as e:
            log_err(f"Warning: Could not read files in {directory} for deduplication: {e}")
    return existing_ids


def cleanup_game_cache(games_csv_path: str, stats_dir: str):
    """Clean up cached game detail files if they have been successfully processed in both pipeline steps."""
    if os.path.isdir(GAME_CACHE_DIR):
        try:
            # Load the latest sets to reflect changes from this run
            games_csv_ids = load_game_ids_from_csv(games_csv_path)
            stats_csv_ids = load_existing_game_ids(stats_dir)
            
            cleaned_count = 0
            for filename in os.listdir(GAME_CACHE_DIR):
                if filename.endswith(".json"):
                    game_id = filename[:-5]
                    file_path = os.path.join(GAME_CACHE_DIR, filename)
                    should_clean = False
                    if game_id in games_csv_ids and game_id in stats_csv_ids:
                        should_clean = True
                    else:
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                game_info = json.load(f)
                            winner_client_id, _ = extract_winner_client_id(game_info)
                            if not winner_client_id:
                                should_clean = True
                        except Exception:
                            should_clean = True

                    if should_clean:
                        try:
                            os.remove(file_path)
                            cleaned_count += 1
                        except OSError as e:
                            log_err(f"Warning: Failed to delete cache file {file_path}: {e}")
            
            if VERBOSE and cleaned_count > 0:
                print(f"Cleaned up {cleaned_count} cached game file(s) from {GAME_CACHE_DIR}.", file=sys.stderr)
                
            # If the cache directory is empty, remove it
            if not os.listdir(GAME_CACHE_DIR):
                try:
                    os.rmdir(GAME_CACHE_DIR)
                    if VERBOSE:
                        print(f"Removed empty cache directory {GAME_CACHE_DIR}.", file=sys.stderr)
                except OSError:
                    pass
        except Exception as e:
            log_err(f"Warning: Failed during cache cleanup: {e}")



