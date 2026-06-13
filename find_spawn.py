#!/usr/bin/env python3
"""
OpenFront Stats Generator - Spawn Finder
This script retrieves all Public Free For All games from the last 30 minutes,
identifies the winners, parses the match turns, extracts starting locations (spawn tiles),
scales them to base map resolution, and logs them to games.csv.
"""

import sys
import os
import csv
import urllib.parse
from datetime import datetime, timedelta, timezone
from utils import VERBOSE, log_err, parse_iso_datetime, fetch_map_manifest, make_request, API_BASE_URL

# Output CSV file path
CSV_FILENAME = "games.csv"

def find_recent_games(start_dt: datetime = None, end_dt: datetime = None) -> list:
    """Queries the games endpoint for Public Free For All games in a specific timeframe."""
    now = datetime.now(timezone.utc)
    if not end_dt:
        end_dt = now
    if not start_dt:
        start_dt = end_dt - timedelta(minutes=30)
        
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    params = {
        "start": start_str,
        "end": end_str,
        "type": "Public",
        "mode": "Free For All",
        "limit": 100
    }
    url = f"{API_BASE_URL}/games?{urllib.parse.urlencode(params)}"
    games = make_request(url)
    
    if games and isinstance(games, list):
        return sorted(
            games, 
            key=lambda g: parse_iso_datetime(g.get("start", "")), 
            reverse=True
        )
    return []

def extract_winner_client_id(game_info: dict) -> tuple:
    """
    Extracts the winner's client ID and username.
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
            # If the second element looks like a client ID (alphanumeric, length ~8)
            for item in winner_val:
                if isinstance(item, str) and item != "player" and len(item) == 8:
                    winner_client_id = item
                    break
            if not winner_client_id and len(winner_val) > 0:
                # Fallback: check all elements
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

def load_existing_game_ids(csv_path: str) -> set:
    """Reads the CSV file and returns a set of all gameIDs already logged."""
    existing_ids = set()
    if os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0:
        try:
            with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    if row and len(row) > 0:
                        existing_ids.add(row[0].strip())
        except Exception as e:
            log_err(f"Warning: Could not read CSV for deduplication: {e}")
    return existing_ids

def append_to_csv(csv_path: str, game_id: str, game_map: str, start_loc: str, x: int = None, y: int = None):
    """Appends match info to the CSV file. Assumes deduplication check is done before calling."""
    file_exists = os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0
    try:
        with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["gameID", "map", "start_location", "x", "y"])
            writer.writerow([game_id, game_map, start_loc, str(x) if x is not None else "", str(y) if y is not None else ""])
            if VERBOSE:
                print(f"Successfully added game '{game_id}' to CSV: {csv_path}", file=sys.stderr)
    except Exception as e:
        log_err(f"Error: Failed to write to CSV: {e}")

def resolve_spawn_coordinates(map_name: str, tile_index: int, config: dict) -> tuple:
    """
    Fetches (or loads from local cache) the map manifest, determines the grid size based on game 
    config (compact/normal/tiny), calculates (x, y) coordinates, and scales them to the base map resolution.
    """
    manifest = fetch_map_manifest(map_name)
    if not manifest:
        return None, None

    # Get base map dimensions
    base_dim = manifest.get("map", {})
    base_w = base_dim.get("width", 2048)
    base_h = base_dim.get("height", 1024)
    
    # Determine the resolution of the grid for this specific match
    map_size = config.get("gameMapSize")
    is_compact = config.get("publicGameModifiers", {}).get("isCompact", False)
    
    resolution_key = "map"
    if map_size == "Compact" or is_compact:
        resolution_key = "map4x"
    elif map_size == "Tiny":
        resolution_key = "map16x"
        
    res_dim = manifest.get(resolution_key, {})
    res_w = res_dim.get("width")
    res_h = res_dim.get("height")
    
    if not res_w:
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

def find_spawn_location(start_dt: datetime = None, end_dt: datetime = None):
    """Finds the spawn location of the winner for all recent games and exports new ones to CSV."""


    # 1. Load existing logged game IDs to prevent redundant requests
    existing_ids = load_existing_game_ids(CSV_FILENAME)
    
    # 2. Get recent games from the specified timeframe
    recent_games = find_recent_games(start_dt, end_dt)
    if not recent_games:
        if VERBOSE:
            print("No recent games found.", file=sys.stderr)
        return
        
    if VERBOSE:
        start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "30 mins ago"
        end_label = end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else "now"
        print(f"Found {len(recent_games)} recent games from {start_label} to {end_label}.", file=sys.stderr)
    
    processed_count = 0
    skipped_count = 0
    processed_by_map = {}
    
    for game_meta in recent_games:
        game_id = game_meta.get("game")
        if not game_id:
            continue
            
        # Check if already processed
        if game_id in existing_ids:
            skipped_count += 1
            continue
            
        if VERBOSE:
            print(f"\nProcessing game {game_id}...", file=sys.stderr)
        
        # 3. Query game details WITH turns (essential for spawn parsing)
        try:
            url = f"{API_BASE_URL}/game/{game_id}"
            game_info = make_request(url)
        except Exception as e:
            log_err(f"Warning: Failed to fetch details for game {game_id}: {e}")
            continue
            
        # 4. Resolve winner client ID and username
        winner_client_id, winner_name = extract_winner_client_id(game_info)
        if not winner_client_id:
            log_err(f"Warning: Could not determine winner for game {game_id}.")
            continue
            
        # 5. Search turns for the winner's spawn intents
        turns = game_info.get("turns", [])
        spawn_intents = []
        
        for turn in turns:
            turn_num = turn.get("turnNumber", 0)
            intents = turn.get("intents", [])
            for intent in intents:
                if not isinstance(intent, dict):
                    continue
                if intent.get("clientID") == winner_client_id and intent.get("type") == "spawn":
                    spawn_intents.append((turn_num, intent))
                    
        # 6. Extract map name and config
        info = game_info.get("info", {})
        config = info.get("config", {})
        game_map = config.get("gameMap", "Unknown Map")
        
        # 7. Extract start location string and resolve coordinates
        start_location_str = "Unknown"
        resolved_x, resolved_y = None, None
        
        if VERBOSE:
            print(f"Winner:         {winner_name} ({winner_client_id})")
            print(f"Map:            {game_map}")
        
        if spawn_intents:
            # Sort by turn number descending to find the final/latest spawn choice
            spawn_intents.sort(key=lambda x: x[0])
            final_turn, final_spawn_intent = spawn_intents[-1]
            
            # Extract location info robustly
            tile = final_spawn_intent.get("tile") or final_spawn_intent.get("tileIndex")
            
            # Check if coordinates are present instead of a single tile
            x = final_spawn_intent.get("x")
            y = final_spawn_intent.get("y")
            
            if tile is not None:
                start_location_str = f"Tile {tile}"
                if VERBOSE:
                    print(f"Start Location: {start_location_str} (Turn {final_turn})")
                # Resolve the tile index into scaled coordinates on the base map
                resolved_x, resolved_y = resolve_spawn_coordinates(game_map, tile, config)
                if resolved_x is not None and VERBOSE:
                    print(f"Scaled Coords:  X={resolved_x}, Y={resolved_y} (scaled to base map)")
            elif x is not None and y is not None:
                start_location_str = f"X={x},Y={y}"
                if VERBOSE:
                    print(f"Start Location: {start_location_str} (Turn {final_turn})")
                resolved_x, resolved_y = x, y
            else:
                # Print the entire intent if standard keys aren't matched
                start_location_str = str(final_spawn_intent)
                if VERBOSE:
                    print(f"Start Location: {start_location_str} (Turn {final_turn})")
        else:
            if VERBOSE:
                print("Start Location: No spawn intent found in turn logs for the winner.")
            
        # 8. Append to CSV
        append_to_csv(CSV_FILENAME, game_id, game_map, start_location_str, resolved_x, resolved_y)
        existing_ids.add(game_id)
        processed_count += 1
        processed_by_map[game_map] = processed_by_map.get(game_map, 0) + 1
        
    if VERBOSE:
        print(f"\nFinished. Processed {processed_count} new games. Skipped {skipped_count} games already logged.")
        if processed_count > 0:
            print("\nNew games processed by map:")
            for map_name, count in sorted(processed_by_map.items()):
                print(f"  - {map_name}: {count} game(s)")
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] Added {processed_count} new game(s).")

if __name__ == "__main__":
    start_arg = None
    end_arg = None
    
    # Simple CLI parsing for custom time range
    for i, arg in enumerate(sys.argv):
        if arg == "--start" and i + 1 < len(sys.argv):
            start_arg = parse_iso_datetime(sys.argv[i + 1])
        elif arg == "--end" and i + 1 < len(sys.argv):
            end_arg = parse_iso_datetime(sys.argv[i + 1])
            
    find_spawn_location(start_arg, end_arg)
