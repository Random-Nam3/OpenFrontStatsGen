#!/usr/bin/env python3
"""
OpenFront Stats Generator - Winner Build Stats Extractor
This script processes game IDs from games.csv, fetches detailed match data
(including turns), and extracts the winner's initial build order and total unit statistics.
"""

import sys
import os
import csv
from datetime import datetime
from utils import (
    log_err, make_request, API_BASE_URL, VERBOSE, get_map_slug,
    extract_winner_client_id, load_game_ids_from_csv, load_game_ids_list_from_csv,
    serialize_dict_to_str, fetch_game_details, load_existing_game_ids,
    GAME_CACHE_DIR
)

# Default file and directory paths
INPUT_CSV = "games.csv"
OUTPUT_DIR = "winner_build_stats_by_map"


def load_game_ids_to_process(csv_path: str) -> list:
    """Reads the input games.csv and returns a list of game IDs in order."""
    if not os.path.isfile(csv_path):
        log_err(f"Error: Input games file not found at {csv_path}")
        sys.exit(1)
    return load_game_ids_list_from_csv(csv_path)

def extract_winner_build_order(game_info: dict, limit: int = 5) -> list:
    """Parses turns sequentially and extracts the first few buildings/units built by the winner."""
    winner_client_id, _ = extract_winner_client_id(game_info)
    if not winner_client_id:
        return []
        
    build_order = []
    turns = game_info.get("turns", [])
    
    # Sort turns sequentially by turn number
    sorted_turns = sorted(turns, key=lambda t: t.get("turnNumber", 0))
    
    for turn in sorted_turns:
        intents = turn.get("intents", [])
        for intent in intents:
            if not isinstance(intent, dict):
                continue
            if intent.get("clientID") == winner_client_id:
                itype = intent.get("type")
                if itype == "build_unit":
                    unit = intent.get("unit") or "Unknown Unit"
                    build_order.append(unit)
                elif itype == "upgrade_structure":
                    build_order.append("Upgrade")
                    
                if len(build_order) >= limit:
                    return build_order
                    
    return build_order

def extract_winner_unit_counts(game_info: dict) -> tuple:
    """
    Extracts the winner's unit stats at the end of the game,
    categorized by built, lost, destroyed, captured, and upgraded.
    """
    winner_client_id, _ = extract_winner_client_id(game_info)
    if not winner_client_id:
        return {}, {}, {}, {}, {}
        
    players = game_info.get("info", {}).get("players", [])
    winner_stats = None
    for p in players:
        if isinstance(p, dict) and p.get("clientID") == winner_client_id:
            winner_stats = p.get("stats", {})
            break
            
    if not winner_stats:
        return {}, {}, {}, {}, {}
        
    units = winner_stats.get("units", {})
    
    # Unit stats array indices mapping:
    # Index 0: built
    # Index 1: lost
    # Index 2: destroyed
    # Index 3: captured
    # Index 4: upgraded
    built = {}
    lost = {}
    destroyed = {}
    captured = {}
    upgraded = {}
    
    for unit_type, values in units.items():
        if not isinstance(values, list):
            continue
            
        def get_val(idx):
            if idx < len(values):
                try:
                    return int(values[idx])
                except (ValueError, TypeError):
                    return 0
            return 0
            
        b_val = get_val(0)
        l_val = get_val(1)
        d_val = get_val(2)
        c_val = get_val(3)
        u_val = get_val(4)
        
        if b_val > 0: built[unit_type] = b_val
        if l_val > 0: lost[unit_type] = l_val
        if d_val > 0: destroyed[unit_type] = d_val
        if c_val > 0: captured[unit_type] = c_val
        if u_val > 0: upgraded[unit_type] = u_val
        
    return built, lost, destroyed, captured, upgraded



def append_row_to_csv(csv_path: str, row: list):
    """Appends a row to the output CSV file, creating headers if the file is new/empty."""
    if os.path.dirname(csv_path):
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    file_exists = os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0
    try:
        with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "gameID", "map", "winner_name", "winner_build_order",
                    "total_built", "total_lost", "total_destroyed",
                    "total_captured", "total_upgraded"
                ])
            writer.writerow(row)
    except Exception as e:
        log_err(f"Error: Failed to write row to CSV {csv_path}: {e}")

def main():
    limit = 5
    input_path = INPUT_CSV
    output_dir = OUTPUT_DIR
    max_games = 100  # Default limit to avoid hitting rate limits or timeouts
    
    # CLI Argument Parsing
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i+1])
            except ValueError:
                pass
        elif arg == "--input" and i + 1 < len(args):
            input_path = args[i+1]
        elif arg == "--output" and i + 1 < len(args):
            output_dir = args[i+1]
        elif arg == "--max-games" and i + 1 < len(args):
            try:
                max_games = int(args[i+1])
            except ValueError:
                pass
            
    # 1. Load games to process
    all_game_ids = []
    if os.path.isfile(input_path):
        all_game_ids = load_game_ids_to_process(input_path)
    elif VERBOSE:
        print(f"Warning: Input games file not found at {input_path}. Processing game_cache backlog only.", file=sys.stderr)
        
    # 2. Load already processed games to prevent double queries
    processed_ids = load_existing_game_ids(output_dir)
    
    game_ids_to_run_all = [gid for gid in all_game_ids if gid not in processed_ids]
    
    # 2b. Scan game_cache for backlog matches
    backlog_ids = []
    if os.path.isdir(GAME_CACHE_DIR):
        for filename in os.listdir(GAME_CACHE_DIR):
            if filename.endswith(".json"):
                gid = filename[:-5]
                if gid not in processed_ids:
                    backlog_ids.append(gid)
                    
    # Combine and prioritize backlog game IDs (from game_cache) at the front of the queue
    game_ids_to_run_all = backlog_ids + [gid for gid in game_ids_to_run_all if gid not in backlog_ids]
    all_game_ids = list(set(all_game_ids).union(backlog_ids))
    unprocessed_count = len(game_ids_to_run_all)
    already_processed_count = len(all_game_ids) - unprocessed_count
    
    if VERBOSE:
        print(f"Total games loaded:  {len(all_game_ids)}")
        print(f"Already processed:   {already_processed_count}")
        print(f"Unprocessed:         {unprocessed_count}")
        
    game_ids_to_run = game_ids_to_run_all
    if max_games is not None and max_games > 0:
        game_ids_to_run = game_ids_to_run_all[:max_games]
        
    if not game_ids_to_run:
        if VERBOSE:
            print("All games already processed.")
        return
        
    if VERBOSE:
        print(f"Processing {len(game_ids_to_run)} new games in this batch...")
    
    processed_count = 0
    for game_id in game_ids_to_run:
        if VERBOSE:
            print(f"Fetching details for game {game_id}...", file=sys.stderr)
            
        try:
            game_info = fetch_game_details(game_id)
        except Exception as e:
            log_err(f"Warning: Failed to fetch details for game {game_id}: {e}")
            continue
            
        winner_client_id, winner_name = extract_winner_client_id(game_info)
        if not winner_client_id:
            log_err(f"Warning: Could not resolve winner for game {game_id}.")
            continue
            
        # Extract map
        info = game_info.get("info", {})
        config = info.get("config", {})
        game_map = config.get("gameMap", "Unknown Map")
        
        # Resolve map slug and define output path
        slug = get_map_slug(game_map)
        map_csv_path = os.path.join(output_dir, f"{slug}.csv")
        
        # Extract build order and stats
        build_order = extract_winner_build_order(game_info, limit=limit)
        built, lost, destroyed, captured, upgraded = extract_winner_unit_counts(game_info)
        
        # Prepare CSV row fields
        build_order_str = ",".join(build_order)
        built_str = serialize_dict_to_str(built)
        lost_str = serialize_dict_to_str(lost)
        destroyed_str = serialize_dict_to_str(destroyed)
        captured_str = serialize_dict_to_str(captured)
        upgraded_str = serialize_dict_to_str(upgraded)
        
        row = [
            game_id, game_map, winner_name, build_order_str,
            built_str, lost_str, destroyed_str, captured_str, upgraded_str
        ]
        
        append_row_to_csv(map_csv_path, row)
        processed_count += 1
        
        if VERBOSE:
            print(f"Processed game {game_id} on map {game_map} (Winner: {winner_name}, Build Order: {build_order_str})", file=sys.stderr)
            
    if VERBOSE:
        print(f"Finished. Successfully extracted stats for {processed_count} games.")
    else:
        if processed_count > 0:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now_str}] Processed {processed_count} new game(s) (Total: {len(all_game_ids)}, Already Processed: {already_processed_count + processed_count}, Remaining: {unprocessed_count - processed_count}).")


if __name__ == "__main__":
    main()
