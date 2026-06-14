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
from utils import (
    VERBOSE, log_err, parse_iso_datetime, fetch_map_manifest, 
    make_request, API_BASE_URL, extract_winner_client_id, 
    resolve_spawn_coordinates, load_game_ids_from_csv, fetch_game_details,
    GAME_CACHE_DIR
)

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
    try:
        games = make_request(url, exit_on_error=False)
    except Exception as e:
        log_err(f"Warning: Failed to fetch recent games from API: {e}")
        return []
    
    if games and isinstance(games, list):
        return sorted(
            games, 
            key=lambda g: parse_iso_datetime(g.get("start", "")), 
            reverse=True
        )
    return []



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



def find_spawn_location(start_dt: datetime = None, end_dt: datetime = None):
    """Finds the spawn location of the winner for all recent games and exports new ones to CSV."""


    # 1. Load existing logged game IDs to prevent redundant requests
    existing_ids = load_game_ids_from_csv(CSV_FILENAME)
    
    # 2. Get recent games from the specified timeframe
    recent_games = find_recent_games(start_dt, end_dt)
    
    # 2b. Add game_cache backlog
    backlog_games = []
    if os.path.isdir(GAME_CACHE_DIR):
        for filename in os.listdir(GAME_CACHE_DIR):
            if filename.endswith(".json"):
                gid = filename[:-5]
                if gid not in existing_ids:
                    backlog_games.append({"game": gid})
                    
    # Merge recent games and backlog games (avoiding duplicates)
    recent_game_ids = {g.get("game") for g in recent_games if g.get("game")}
    for bg in backlog_games:
        if bg["game"] not in recent_game_ids:
            recent_games.append(bg)
            
    if not recent_games:
        if VERBOSE:
            print("No games to process.", file=sys.stderr)
        return
        
    if VERBOSE:
        start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "30 mins ago"
        end_label = end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else "now"
        print(f"Found {len(recent_games)} games to process (including backlog and recent from {start_label} to {end_label}).", file=sys.stderr)
    
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
            game_info = fetch_game_details(game_id)
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
            # Sort by turn number ascending to find the final/latest spawn choice
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
