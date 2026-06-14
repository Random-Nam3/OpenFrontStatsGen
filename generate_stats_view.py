#!/usr/bin/env python3
"""
OpenFront Stats Generator - Unified Statistics Dashboard Generator
This script parses winner spawn data from games.csv and detailed winner statistics
from the winner_build_stats_by_map/ folder to generate a beautiful, interactive
HTML dashboard showing spawn heatmaps, opening build orders, and unit breakdowns.
"""

import json
import os
import csv
import sys
from datetime import datetime
from utils import VERBOSE, log_err, get_map_slug, fetch_map_manifest, resolve_spawn_coordinates, parse_and_accumulate_stats, cleanup_game_cache

def parse_games_csv(csv_path: str) -> dict:
    """Reads the CSV file and maps tile numbers to 2D coordinates using fetched map dimensions."""
    if not os.path.isfile(csv_path):
        log_err(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)
        
    map_data = {}
    
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            game_id = (row.get("gameID") or "").strip()
            map_name = (row.get("map") or "").strip()
            start_loc = (row.get("start_location") or "").strip()
            if not game_id or not map_name:
                continue
                
            slug = get_map_slug(map_name)
            
            # 1. Try to read x and y columns directly (if present and populated)
            x_coord, y_coord = None, None
            x_str = row.get("x")
            y_str = row.get("y")
            if x_str and y_str:
                try:
                    x_coord = int(x_str.strip())
                    y_coord = int(y_str.strip())
                except ValueError:
                    pass
            
            # 2. Extract from map_data cache or fetch manifest
            if slug not in map_data:
                manifest = fetch_map_manifest(map_name)
                base_dim = manifest.get("map", {})
                width = int(base_dim.get("width", 2048))
                height = int(base_dim.get("height", 1024))
                map_data[slug] = {
                    "name": map_name,
                    "width": width,
                    "height": height,
                    "points": []
                }
            
            # 3. Resolve coordinate
            if x_coord is not None and y_coord is not None:
                map_data[slug]["points"].append({"x": x_coord, "y": y_coord})
            else:
                # Fallback for old entries without x, y columns
                coords = None
                if "X=" in start_loc and "Y=" in start_loc:
                    try:
                        parts = start_loc.split(",")
                        x_val = int(parts[0].split("=")[1])
                        y_val = int(parts[1].split("=")[1])
                        coords = (x_val, y_val)
                    except Exception:
                        pass
                
                tile_index = None
                if not coords:
                    if "Tile " in start_loc:
                        try:
                            tile_index = int(start_loc.replace("Tile ", "").split("(")[0].strip())
                        except ValueError:
                            pass
                    elif start_loc.isdigit():
                        tile_index = int(start_loc)
                
                if coords:
                    map_data[slug]["points"].append({"x": coords[0], "y": coords[1]})
                elif tile_index is not None:
                    rx, ry = resolve_spawn_coordinates(map_name, tile_index)
                    if rx is not None and ry is not None:
                        map_data[slug]["points"].append({"x": rx, "y": ry})
                        
    return map_data

def parse_winner_stats(directory: str) -> dict:
    """Reads all CSV files in the directory and aggregates stats on a per-map basis."""
    stats_data = {}
    if not os.path.isdir(directory):
        return stats_data
        
    for filename in os.listdir(directory):
        if not filename.endswith(".csv"):
            continue
        slug = filename[:-4]  # strip .csv
        csv_path = os.path.join(directory, filename)
        
        games_count = 0
        build_orders = {}
        build_steps = [{} for _ in range(5)]
        
        sum_built = {}
        sum_lost = {}
        sum_destroyed = {}
        sum_captured = {}
        sum_upgraded = {}
        
        try:
            with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    games_count += 1
                    
                    # 1. Build order sequences
                    bo_str = (row.get("winner_build_order") or "").strip()
                    if bo_str:
                        build_orders[bo_str] = build_orders.get(bo_str, 0) + 1
                        
                        parts = bo_str.split(",")
                        for step_idx in range(min(5, len(parts))):
                            unit = parts[step_idx].strip()
                            if unit:
                                build_steps[step_idx][unit] = build_steps[step_idx].get(unit, 0) + 1
                            
                    # 2. Accumulate totals using shared utility
                    parse_and_accumulate_stats(row.get("total_built"), sum_built)
                    parse_and_accumulate_stats(row.get("total_lost"), sum_lost)
                    parse_and_accumulate_stats(row.get("total_destroyed"), sum_destroyed)
                    parse_and_accumulate_stats(row.get("total_captured"), sum_captured)
                    parse_and_accumulate_stats(row.get("total_upgraded"), sum_upgraded)
                    
        except Exception as e:
            log_err(f"Warning: Failed to parse winner stats from {csv_path}: {e}")
            continue
            
        if games_count == 0:
            continue
            
        # Calculate averages rounded to 1 decimal place
        def get_averages(sum_dict):
            return {k: round(v / games_count, 1) for k, v in sum_dict.items()}
            
        # Sort build orders by frequency
        sorted_bos = sorted(build_orders.items(), key=lambda x: x[1], reverse=True)
        top_bos = [{"sequence": seq.split(","), "count": count, "percentage": round((count / games_count) * 100, 1)} 
                   for seq, count in sorted_bos[:5]]
                   
        # Calculate percentages for the first 5 steps
        build_steps_percentages = []
        for step_dict in build_steps:
            total_at_step = sum(step_dict.values())
            if total_at_step > 0:
                sorted_step = sorted(
                    [{ "unit": k, "percentage": round((v / total_at_step) * 100, 1) } for k, v in step_dict.items()],
                    key=lambda x: x["percentage"],
                    reverse=True
                )
                build_steps_percentages.append(sorted_step)
            else:
                build_steps_percentages.append([])
        
        stats_data[slug] = {
            "games_count": games_count,
            "top_build_orders": top_bos,
            "build_steps": build_steps_percentages,
            "avg_built": get_averages(sum_built),
            "avg_lost": get_averages(sum_lost),
            "avg_destroyed": get_averages(sum_destroyed),
            "avg_captured": get_averages(sum_captured),
            "avg_upgraded": get_averages(sum_upgraded)
        }
        
    return stats_data

def generate_html_dashboard(map_data: dict, output_path: str):
    """Generates the interactive unified dashboard HTML page."""
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenFront Match Winner Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0d12;
            --card-bg: #131722;
            --card-border: #242c3d;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-color: #3b82f6;
            --accent-hover: #2563eb;
            --success-color: #10b981;
            --danger-color: #ef4444;
            --warning-color: #f59e0b;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            margin: 0;
            padding: 0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        header {
            margin-top: 40px;
            text-align: center;
            width: 100%;
            max-width: 1200px;
        }

        h1 {
            font-size: 2.8rem;
            font-weight: 800;
            margin: 0 0 10px 0;
            background: linear-gradient(135deg, #60a5fa, #3b82f6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        p.subtitle {
            font-size: 1.1rem;
            color: var(--text-secondary);
            margin: 0;
        }

        /* Tabs Navigation */
        .tabs {
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-top: 25px;
            width: 100%;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 15px;
        }

        .tab-button {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--card-border);
            color: var(--text-secondary);
            padding: 10px 24px;
            border-radius: 30px;
            cursor: pointer;
            font-family: 'Outfit', sans-serif;
            font-weight: 600;
            font-size: 0.95rem;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .tab-button:hover {
            color: var(--text-primary);
            border-color: rgba(59, 130, 246, 0.5);
            background: rgba(255, 255, 255, 0.06);
        }

        .tab-button.active {
            background: var(--accent-color);
            color: white;
            border-color: var(--accent-color);
            box-shadow: 0 0 16px rgba(59, 130, 246, 0.35);
        }

        .container {
            max-width: 95vw;
            width: 1200px;
            margin: 30px 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 30px;
            box-sizing: border-box;
        }

        /* Map selection grid */
        .map-grid {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 12px;
            width: 100%;
        }

        .map-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 10px 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
            min-width: 170px;
        }

        .map-card:hover {
            transform: translateY(-2px);
            border-color: rgba(59, 130, 246, 0.5);
            background: rgba(19, 23, 34, 0.85);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }

        .map-card.active {
            border-color: var(--accent-color);
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.08), rgba(37, 99, 235, 0.15));
            box-shadow: 0 0 16px 2px rgba(37, 99, 235, 0.2);
        }

        .map-card-icon {
            width: 34px;
            height: 34px;
            border-radius: 8px;
            background-size: cover;
            background-position: center;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .map-card-info {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
        }

        .map-card-name {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .map-card-count {
            font-size: 0.7rem;
            color: var(--text-secondary);
            margin-top: 2px;
            background: rgba(255, 255, 255, 0.04);
            padding: 1px 6px;
            border-radius: 12px;
        }

        .map-card.active .map-card-count {
            color: #60a5fa;
            background: rgba(59, 130, 246, 0.15);
        }

        /* View Contents */
        .tab-content {
            display: none;
            width: 100%;
            animation: fadeIn 0.4s ease-out;
        }

        .tab-content.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Heatmap View */
        .visualization-card {
            position: relative;
            background-color: var(--card-bg);
            border-radius: 16px;
            border: 1px solid var(--card-border);
            padding: 16px;
            box-shadow: 0 15px 25px -5px rgba(0, 0, 0, 0.4);
            width: 100%;
            box-sizing: border-box;
            display: flex;
            justify-content: center;
        }

        .map-wrapper {
            position: relative;
            width: 100%;
            max-width: 1100px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #1e293b;
        }

        .map-bg {
            display: block;
            width: 100%;
            height: auto;
            object-fit: contain;
            opacity: 0.7;
        }

        canvas {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
        }

                /* Build Order Analytics View */
        .builds-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 24px;
            width: 100%;
        }

        .panel-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 20px rgba(0,0,0,0.3);
        }

        .panel-title {
            font-size: 1.3rem;
            font-weight: 700;
            margin: 0 0 20px 0;
            border-bottom: 2px solid rgba(255,255,255,0.05);
            padding-bottom: 10px;
            color: var(--text-primary);
        }

        .build-sequence-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .build-seq-item {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .build-seq-header {
            display: flex;
            justify-content: space-between;
            font-size: 0.95rem;
            font-weight: 600;
        }

        .build-seq-percentage {
            color: var(--accent-color);
        }

        .build-seq-flow {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
        }

        .build-step {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: capitalize;
            color: var(--text-primary);
        }

        .build-arrow {
            color: var(--text-secondary);
            font-size: 0.75rem;
        }

        /* Pie Charts Grid */
        .pie-charts-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            justify-content: flex-start;
            margin-top: 15px;
        }

        .pie-chart-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 180px;
            flex: 1 1 180px;
            box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.2);
            transition: border-color 0.25s ease, background 0.25s ease;
        }

        .pie-chart-card:hover {
            border-color: rgba(59, 130, 246, 0.2);
            background: rgba(255, 255, 255, 0.04);
        }

        /* Featured 1st Step Card Styles */
        .pie-chart-card.featured {
            flex: 1 1 100%;
            display: flex;
            flex-direction: row;
            justify-content: space-evenly;
            align-items: center;
            gap: 30px;
            padding: 30px;
            border-color: rgba(59, 130, 246, 0.15);
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.02) 0%, rgba(59, 130, 246, 0.02) 100%);
        }

        .pie-chart-card.featured .pie-circle {
            width: 150px;
            height: 150px;
            margin-bottom: 0;
        }

        .pie-chart-card.featured .pie-legend {
            border-top: none;
            padding-top: 0;
            max-width: 300px;
        }

        .pie-chart-card.featured .pie-chart-info {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
        }

        @media (max-width: 768px) {
            .pie-chart-card.featured {
                flex-direction: column;
                align-items: center;
                gap: 20px;
                padding: 20px;
            }
            .pie-chart-card.featured .pie-circle {
                width: 120px;
                height: 120px;
            }
            .pie-chart-card.featured .pie-legend {
                max-width: 100%;
                border-top: 1px solid rgba(255, 255, 255, 0.05);
                padding-top: 12px;
            }
        }

        .pie-chart-title {
            font-size: 0.9rem;
            font-weight: 700;
            color: var(--text-secondary);
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .pie-circle {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            margin-bottom: 16px;
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.4);
            transition: transform 0.3s ease;
        }

        .pie-chart-card:hover .pie-circle {
            transform: scale(1.05);
        }

        .pie-legend {
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 8px;
            font-size: 0.8rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 12px;
        }

        .pie-legend-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }

        .pie-legend-label {
            display: flex;
            align-items: center;
            gap: 8px;
            text-transform: capitalize;
            color: var(--text-primary);
            font-weight: 500;
        }

        .pie-legend-color {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .pie-legend-pct {
            color: var(--text-secondary);
            font-weight: 600;
        }

        /* Unit Stats View */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
            width: 100%;
        }

        .unit-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.25);
            display: flex;
            flex-direction: column;
            gap: 15px;
            transition: transform 0.25s ease;
        }
        
        .unit-card:hover {
            transform: translateY(-2px);
            border-color: rgba(255,255,255,0.08);
        }

        .unit-card-title {
            font-size: 1.15rem;
            font-weight: 700;
            text-transform: capitalize;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding-bottom: 8px;
            color: var(--text-primary);
        }

        .unit-metric-row {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .unit-metric-label {
            display: flex;
            justify-content: space-between;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .unit-metric-val {
            color: var(--text-primary);
            font-weight: 700;
        }

        .metric-bar-outer {
            background: rgba(255, 255, 255, 0.03);
            border-radius: 10px;
            height: 8px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.02);
        }

        .metric-bar-fill {
            height: 100%;
            border-radius: 10px;
            width: 0%;
            transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .fill-built { background: linear-gradient(90deg, #2563eb, #3b82f6); }
        .fill-lost { background: linear-gradient(90deg, #dc2626, #ef4444); }
        .fill-destroyed { background: linear-gradient(90deg, #d97706, #f59e0b); }
        .fill-captured { background: linear-gradient(90deg, #059669, #10b981); }

        /* General Stats Blocks */
        .general-stats {
            display: flex;
            justify-content: center;
            gap: 20px;
            width: 100%;
            margin-top: 10px;
        }

        .stat-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            padding: 15px 25px;
            border-radius: 12px;
            text-align: center;
            min-width: 140px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.15);
        }

        .stat-val {
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--accent-color);
        }

        .stat-lbl {
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-top: 5px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        footer {
            margin-top: 50px;
            margin-bottom: 30px;
            font-size: 0.9rem;
            color: #334155;
        }
    </style>
</head>
<body>
    <header>
        <h1>OpenFront Match Winner Dashboard</h1>
        <p class="subtitle">Superimposed spawn locations and detailed build order statistics of winners</p>
        
        <!-- Map selector grid directly below the title -->
        <div class="map-grid" id="mapGrid" style="margin-top: 30px;">
            <!-- Populated dynamically -->
        </div>

        <!-- Tabs Navigation below the map selector -->
        <div class="tabs" style="margin-top: 30px;">
            <button class="tab-button active" onclick="switchTab('heatmap')" id="btn-heatmap">
                Spawn Heatmap
            </button>
            <button class="tab-button" onclick="switchTab('builds')" id="btn-builds">
                Winner Opening Builds
            </button>
            <button class="tab-button" onclick="switchTab('unit-stats')" id="btn-unit-stats">
                Winner Unit Stats
            </button>
        </div>
    </header>

    <div class="container">

        <!-- Heatmap View Content -->
        <div class="tab-content active" id="content-heatmap">
            <!-- Heatmap / Cluster Controls -->
            <div class="controls-bar" style="display: flex; gap: 20px; align-items: center; margin-bottom: 15px; padding: 12px 20px; background: var(--card-bg); border-radius: 12px; border: 1px solid var(--card-border); max-width: 1100px; margin-left: auto; margin-right: auto;">
                <div style="font-weight: 700; font-size: 0.9rem; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.05em;">Visual Options</div>
                <label class="control-label" style="display: flex; align-items: center; gap: 8px; font-size: 0.9rem; color: var(--text-secondary); cursor: pointer; user-select: none;">
                    <input type="checkbox" id="chkFilterNoise" onchange="drawHeatmap(mapData[activeSlug])" style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--accent-color);"> Filter Outliers (DBSCAN)
                </label>
                <label class="control-label" style="display: flex; align-items: center; gap: 8px; font-size: 0.9rem; color: var(--text-secondary); cursor: pointer; user-select: none;">
                    <input type="checkbox" id="chkShowClusters" onchange="drawHeatmap(mapData[activeSlug])" checked style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--accent-color);"> Highlight Hotspots
                </label>
            </div>

            <div class="visualization-card">
                <div class="map-wrapper" id="mapWrapper">
                    <img id="mapBackground" class="map-bg" src="" alt="Map Geography">
                    <canvas id="heatmapCanvas"></canvas>
                </div>
            </div>
        </div>

        <!-- Opening Builds View Content -->
        <div class="tab-content" id="content-builds">
            <div class="builds-grid">
                <!-- Most Common Build Sequences -->
                <div class="panel-card">
                    <h3 class="panel-title">Top 5 Opening Build Sequences</h3>
                    <div class="build-sequence-list" id="seqList">
                        <!-- Populated dynamically -->
                    </div>
                </div>
                
                <!-- Frequencies at Each Build Step -->
                <div class="panel-card">
                    <h3 class="panel-title">Frequencies at Each Build Step (First 5 Units)</h3>
                    <div class="pie-charts-grid" id="pieChartsContainer">
                        <!-- Populated dynamically -->
                    </div>
                </div>
            </div>
        </div>

        <!-- Unit Stats View Content -->
        <div class="tab-content" id="content-unit-stats">
            <div class="stats-grid" id="unitStatsGrid">
                <!-- Populated dynamically -->
            </div>
        </div>

        <!-- General stats panel at bottom -->
        <div class="general-stats">
            <div class="stat-card">
                <div class="stat-val" id="totalGamesVal">0</div>
                <div class="stat-lbl" id="totalGamesLbl">Sampled Spawns</div>
            </div>
            <div class="stat-card">
                <div class="stat-val" id="gridDimVal">0 x 0</div>
                <div class="stat-lbl">Grid Dimensions</div>
            </div>
        </div>
    </div>

    <footer>
        Generated by OpenFrontStatsGen
    </footer>

    <script>
        // Embed parsed map data
        const mapData = /* DATA */;

        let activeSlug = null;
        let activeTab = 'heatmap';



        // Set up tabs switching
        function switchTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-button').forEach(el => el.classList.remove('active'));
            
            document.getElementById(`content-${tabName}`).classList.add('active');
            document.getElementById(`btn-${tabName}`).classList.add('active');
            
            activeTab = tabName;
            
            // Update map counts for the new active tab
            updateMapCardCounts();
            
            // Re-render when switching tabs to trigger animations/draws
            if (activeSlug) {
                renderActiveView();
            }
        }

        function populateMapSelect() {
            const grid = document.getElementById('mapGrid');
            grid.innerHTML = '';
            
            const slugs = Object.keys(mapData);
            if (slugs.length === 0) return;
            
            activeSlug = slugs[0];
            
            slugs.forEach(slug => {
                const card = document.createElement('div');
                card.className = `map-card ${slug === activeSlug ? 'active' : ''}`;
                card.id = `card-${slug}`;
                card.onclick = () => selectMap(slug);
                
                // Icon thumbnail
                const icon = document.createElement('div');
                icon.className = 'map-card-icon';
                icon.style.backgroundImage = `url(https://raw.githubusercontent.com/openfrontio/OpenFrontIO/main/resources/maps/${slug}/thumbnail.webp)`;
                
                // Info block
                const info = document.createElement('div');
                info.className = 'map-card-info';
                
                const name = document.createElement('div');
                name.className = 'map-card-name';
                name.textContent = mapData[slug].name;
                
                const count = document.createElement('div');
                count.className = 'map-card-count';
                
                // Count samples based on activeTab
                let samples = 0;
                let unit = 'game';
                if (activeTab === 'heatmap') {
                    samples = mapData[slug].points ? mapData[slug].points.length : 0;
                    unit = 'spawn';
                } else {
                    samples = mapData[slug].stats ? mapData[slug].stats.games_count : 0;
                    unit = 'game';
                }
                count.textContent = `${samples} ${unit}${samples === 1 ? '' : 's'}`;
                
                info.appendChild(name);
                info.appendChild(count);
                
                card.appendChild(icon);
                card.appendChild(info);
                
                grid.appendChild(card);
            });
        }

        function updateMapCardCounts() {
            Object.keys(mapData).forEach(slug => {
                const card = document.getElementById(`card-${slug}`);
                if (!card) return;
                const countEl = card.querySelector('.map-card-count');
                if (!countEl) return;
                
                let samples = 0;
                let unit = 'game';
                if (activeTab === 'heatmap') {
                    samples = mapData[slug].points ? mapData[slug].points.length : 0;
                    unit = 'spawn';
                } else {
                    samples = mapData[slug].stats ? mapData[slug].stats.games_count : 0;
                    unit = 'game';
                }
                countEl.textContent = `${samples} ${unit}${samples === 1 ? '' : 's'}`;
            });
        }

        function selectMap(slug) {
            if (activeSlug) {
                const prevCard = document.getElementById(`card-${activeSlug}`);
                if (prevCard) prevCard.classList.remove('active');
            }
            
            activeSlug = slug;
            const card = document.getElementById(`card-${slug}`);
            if (card) card.classList.add('active');
            
            renderActiveView();
        }

        function renderActiveView() {
            const data = mapData[activeSlug];
            if (!data) return;

            // Update general stats
            let gamesCount = 0;
            let labelText = '';
            if (activeTab === 'heatmap') {
                gamesCount = data.points ? data.points.length : 0;
                labelText = 'Sampled Spawns';
            } else {
                gamesCount = data.stats ? data.stats.games_count : 0;
                labelText = 'Sampled Stats Games';
            }
            
            document.getElementById('totalGamesVal').textContent = gamesCount;
            const lblEl = document.getElementById('totalGamesLbl');
            if (lblEl) lblEl.textContent = labelText;
            
            document.getElementById('gridDimVal').textContent = `${data.width} × ${data.height}`;

            if (activeTab === 'heatmap') {
                loadMapHeatmap(data);
            } else if (activeTab === 'builds') {
                loadBuildOrdersView(data);
            } else if (activeTab === 'unit-stats') {
                loadUnitStatsView(data);
            }
        }

        // ==================== HEATMAP RENDER ====================
        function loadMapHeatmap(data) {
            const bgImg = document.getElementById('mapBackground');
            bgImg.crossOrigin = 'anonymous';
            bgImg.src = `https://raw.githubusercontent.com/openfrontio/OpenFrontIO/main/resources/maps/${activeSlug}/thumbnail.webp`;

            bgImg.onload = () => {
                drawHeatmap(data);
            };
            
            if (bgImg.complete) {
                drawHeatmap(data);
            }
        }

        function computeConvexHull(points) {
            if (points.length <= 1) return points.slice();

            // Sort points lexicographically by x, then y
            const sorted = points.slice().sort((a, b) => a.x !== b.x ? a.x - b.x : a.y - b.y);

            const crossProduct = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);

            // Build lower hull
            const lower = [];
            for (let i = 0; i < sorted.length; i++) {
                while (lower.length >= 2 && crossProduct(lower[lower.length - 2], lower[lower.length - 1], sorted[i]) <= 0) {
                    lower.pop();
                }
                lower.push(sorted[i]);
            }

            // Build upper hull
            const upper = [];
            for (let i = sorted.length - 1; i >= 0; i--) {
                while (upper.length >= 2 && crossProduct(upper[upper.length - 2], upper[upper.length - 1], sorted[i]) <= 0) {
                    upper.pop();
                }
                upper.push(sorted[i]);
            }

            // Remove the last point of each list because it's repeated at the beginning of the other list
            lower.pop();
            upper.pop();

            return lower.concat(upper);
        }

        function runDBSCAN(points, eps, minPts) {
            const status = new Array(points.length).fill(null); // 'noise' or cluster index
            
            function getNeighbors(idx) {
                const neighbors = [];
                const p1 = points[idx];
                for (let i = 0; i < points.length; i++) {
                    const p2 = points[i];
                    if (Math.hypot(p1.x - p2.x, p1.y - p2.y) <= eps) {
                        neighbors.push(i);
                    }
                }
                return neighbors;
            }

            let clusterIdx = 0;
            for (let i = 0; i < points.length; i++) {
                if (status[i] !== null) continue;

                const neighbors = getNeighbors(i);
                if (neighbors.length < minPts) {
                    status[i] = 'noise';
                    continue;
                }

                status[i] = clusterIdx;
                const queue = neighbors.filter(n => n !== i);

                for (let j = 0; j < queue.length; j++) {
                    const curr = queue[j];
                    if (status[curr] === 'noise') status[curr] = clusterIdx;
                    if (status[curr] !== null) continue;

                    status[curr] = clusterIdx;
                    const currNeighbors = getNeighbors(curr);
                    if (currNeighbors.length >= minPts) {
                        for (let k = 0; k < currNeighbors.length; k++) {
                            const n = currNeighbors[k];
                            if (!queue.includes(n)) queue.push(n);
                        }
                    }
                }
                clusterIdx++;
            }

            const clusters = Array.from({ length: clusterIdx }, () => []);
            const outliers = [];
            
            points.forEach((pt, i) => {
                if (status[i] === 'noise') {
                    outliers.push(pt);
                } else {
                    clusters[status[i]].push(pt);
                }
            });

            return { clusters, outliers };
        }

        function drawHeatmap(data) {
            const canvas = document.getElementById('heatmapCanvas');
            canvas.width = data.width;
            canvas.height = data.height;
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, data.width, data.height);

            const tempCanvas = document.createElement('canvas');
            tempCanvas.width = data.width;
            tempCanvas.height = data.height;
            const tempCtx = tempCanvas.getContext('2d');

            const radius = Math.max(30, Math.round(data.width * 0.025));
            
            // Get checkbox states
            const filterNoise = document.getElementById('chkFilterNoise')?.checked || false;
            const showClusters = document.getElementById('chkShowClusters')?.checked || false;

            // Run DBSCAN if either option is selected
            let renderPoints = data.points || [];
            let clustersInfo = null;

            if (filterNoise || showClusters) {
                const N = Math.max(1, renderPoints.length);
                // Determine search radius (eps) dynamically based on map width and sample count
                // Scales inversely with the sample count using N^-0.2 to prevent merging in dense areas
                const eps = Math.max(30, Math.round(data.width * 0.09 * Math.pow(N, -0.2)));
                // minPts dynamically scales (e.g. 2.5% of total points, min 4)
                const minPts = Math.max(4, Math.round(N * 0.025));
                
                clustersInfo = runDBSCAN(renderPoints, eps, minPts);
                
                if (filterNoise && clustersInfo) {
                    // Flatten clean clusters into renderPoints, leaving out outliers
                    renderPoints = clustersInfo.clusters.flat();
                }
            }

            // Draw heatmap onto the temp canvas
            tempCtx.globalCompositeOperation = 'lighter';
            const count = renderPoints.length;
            const intensity = Math.max(0.005, Math.min(0.5, 1.5 / Math.sqrt(Math.max(1, count))));

            renderPoints.forEach(pt => {
                const grad = tempCtx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, radius);
                grad.addColorStop(0, `rgba(255,255,255,${intensity})`);
                grad.addColorStop(1, 'rgba(255,255,255,0)');
                tempCtx.fillStyle = grad;
                tempCtx.beginPath();
                tempCtx.arc(pt.x, pt.y, radius, 0, Math.PI * 2);
                tempCtx.fill();
            });

            const imgData = tempCtx.getImageData(0, 0, data.width, data.height);
            const pixels = imgData.data;
            
            let maxAlpha = 0;
            for (let i = 3; i < pixels.length; i += 4) {
                if (pixels[i] > maxAlpha) {
                    maxAlpha = pixels[i];
                }
            }

            const palette = getGradientPalette();

            if (maxAlpha > 0) {
                for (let i = 0; i < pixels.length; i += 4) {
                    const alpha = pixels[i + 3];
                    if (alpha > 0) {
                        const normalizedAlpha = alpha / maxAlpha;
                        const colorIndex = Math.floor(normalizedAlpha * 255) * 4;
                        
                        pixels[i] = palette[colorIndex];
                        pixels[i + 1] = palette[colorIndex + 1];
                        pixels[i + 2] = palette[colorIndex + 2];
                        pixels[i + 3] = Math.floor(normalizedAlpha * 200); 
                    }
                }
            }
            ctx.putImageData(imgData, 0, 0);

            // Draw cluster hotspot overlays (centroids & standard deviation radius) on top of the heatmap
            if (showClusters && clustersInfo && clustersInfo.clusters.length > 0) {
                // Find the size of the largest cluster on the map for relative scaling
                const maxClusterSize = Math.max(...clustersInfo.clusters.map(c => c.length));

                clustersInfo.clusters.forEach((cluster, index) => {
                    if (cluster.length === 0) return;

                    // Fade hotspot opacity based on size relative to the largest cluster (min 0.2, max 1.0)
                    const relRatio = maxClusterSize > 0 ? cluster.length / maxClusterSize : 1;
                    const opacity = 0.2 + 0.8 * Math.sqrt(relRatio);
                    ctx.globalAlpha = opacity;

                    // Calculate centroid (mean X, Y)
                    let sumX = 0, sumY = 0;
                    cluster.forEach(pt => {
                        sumX += pt.x;
                        sumY += pt.y;
                    });
                    const cX = sumX / cluster.length;
                    const cY = sumY / cluster.length;

                    // Compute Convex Hull
                    const hull = computeConvexHull(cluster);

                    if (hull.length >= 3) {
                        // Draw the Convex Hull boundary polygon
                        ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
                        ctx.lineWidth = 3;
                        ctx.setLineDash([6, 6]);
                        ctx.beginPath();
                        ctx.moveTo(hull[0].x, hull[0].y);
                        for (let i = 1; i < hull.length; i++) {
                            ctx.lineTo(hull[i].x, hull[i].y);
                        }
                        ctx.closePath();
                        ctx.stroke();
                        ctx.setLineDash([]); // Reset line dash

                        // Calculate max distance from centroid to hull points for gradient scale
                        let maxDist = 50;
                        hull.forEach(pt => {
                            const dist = Math.hypot(pt.x - cX, pt.y - cY);
                            if (dist > maxDist) maxDist = dist;
                        });

                        // Draw inner soft glow backing restricted to polygon
                        const glowGrad = ctx.createRadialGradient(cX, cY, 0, cX, cY, maxDist);
                        glowGrad.addColorStop(0, 'rgba(255, 255, 255, 0.06)');
                        glowGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
                        ctx.fillStyle = glowGrad;
                        ctx.beginPath();
                        ctx.moveTo(hull[0].x, hull[0].y);
                        for (let i = 1; i < hull.length; i++) {
                            ctx.lineTo(hull[i].x, hull[i].y);
                        }
                        ctx.closePath();
                        ctx.fill();
                    } else {
                        // Fallback: draw standard circle if collinear or too few points
                        const cRadius = 50;
                        ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
                        ctx.lineWidth = 3;
                        ctx.setLineDash([6, 6]);
                        ctx.beginPath();
                        ctx.arc(cX, cY, cRadius, 0, Math.PI * 2);
                        ctx.stroke();
                        ctx.setLineDash([]);

                        const glowGrad = ctx.createRadialGradient(cX, cY, 0, cX, cY, cRadius);
                        glowGrad.addColorStop(0, 'rgba(255, 255, 255, 0.06)');
                        glowGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
                        ctx.fillStyle = glowGrad;
                        ctx.beginPath();
                        ctx.arc(cX, cY, cRadius, 0, Math.PI * 2);
                        ctx.fill();
                    }

                    // Draw a solid center target point
                    ctx.fillStyle = '#ffffff';
                    ctx.beginPath();
                    ctx.arc(cX, cY, 5, 0, Math.PI * 2);
                    ctx.fill();

                    // Draw text badge: e.g. "Hotspot #1 (N wins)"
                    ctx.globalAlpha = 1.0; // Temporarily reset to apply explicit rgba colors for shadow compatibility
                    ctx.font = 'bold 16px sans-serif';
                    ctx.fillStyle = `rgba(255, 255, 255, ${opacity})`;
                    ctx.shadowColor = `rgba(0, 0, 0, ${0.9 * opacity})`;
                    ctx.shadowBlur = 4;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'bottom';
                    
                    const totalPoints = data.points ? data.points.length : 1;
                    const pct = ((cluster.length / totalPoints) * 100).toFixed(1);
                    const label = `Hotspot #${index + 1} (${pct}%)`;
                    ctx.fillText(label, cX, cY - 12);
                    
                    // Reset shadow and alpha
                    ctx.shadowColor = 'transparent';
                    ctx.shadowBlur = 0;
                    ctx.globalAlpha = 1.0;
                });
            }
        }

        function getGradientPalette() {
            const canvas = document.createElement('canvas');
            canvas.width = 1;
            canvas.height = 256;
            const ctx = canvas.getContext('2d');

            const grad = ctx.createLinearGradient(0, 0, 0, 256);
            grad.addColorStop(0, 'rgba(59, 130, 246, 0)');
            grad.addColorStop(0.15, '#3b82f6');
            grad.addColorStop(0.4, '#10b981');
            grad.addColorStop(0.7, '#f59e0b');
            grad.addColorStop(1.0, '#ef4444');

            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 1, 256);
            return ctx.getImageData(0, 0, 1, 256).data;
        }

        // Color mapping for build order units (distinct, high-contrast palette)
        const UNIT_COLORS = {
            'city': '#2563eb',             // Deep Blue
            'factory': '#16a34a',          // Vibrant Green
            'fact': '#16a34a',
            'port': '#0ea5e9',             // Sky Blue
            'warship': '#8b5cf6',          // Violet/Purple
            'wshp': '#8b5cf6',
            'defense post': '#f59e0b',     // Amber/Yellow
            'defp': '#f59e0b',
            'missile silo': '#f97316',     // Orange
            'silo': '#f97316',
            'sam launcher': '#06b6d4',     // Cyan
            'saml': '#06b6d4',
            'atom bomb': '#ef4444',        // Vibrant Red
            'hydrogen bomb': '#991b1b',    // Burgundy Red
            'unknown': '#475569'           // Dark Slate Gray
        };

        function getUnitColor(unitName) {
            if (!unitName) return UNIT_COLORS['unknown'];
            const key = unitName.toLowerCase().trim().replace(/\s+/g, ' ');
            return UNIT_COLORS[key] || UNIT_COLORS['unknown'];
        }

        // ==================== BUILD ORDERS VIEW ====================
        function loadBuildOrdersView(data) {
            const seqList = document.getElementById('seqList');
            const pieContainer = document.getElementById('pieChartsContainer');
            
            seqList.innerHTML = '';
            pieContainer.innerHTML = '';
            
            const stats = data.stats;
            if (!stats || !stats.games_count) {
                seqList.innerHTML = '<div style="padding: 20px; color: var(--text-secondary);">No build statistics available. Run build stats collector.</div>';
                pieContainer.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); width: 100%; text-align: center;">No build statistics available.</div>';
                return;
            }
            
            // 1. Top Sequences
            stats.top_build_orders.forEach((bo, idx) => {
                const item = document.createElement('div');
                item.className = 'build-seq-item';
                
                const header = document.createElement('div');
                header.className = 'build-seq-header';
                
                const title = document.createElement('div');
                title.textContent = `Rank ${idx + 1} (${bo.count} game${bo.count === 1 ? '' : 's'})`;
                
                const percent = document.createElement('div');
                percent.className = 'build-seq-percentage';
                percent.textContent = `${bo.percentage}%`;
                
                header.appendChild(title);
                header.appendChild(percent);
                
                const flow = document.createElement('div');
                flow.className = 'build-seq-flow';
                
                bo.sequence.forEach((step, sIdx) => {
                    const stepDiv = document.createElement('div');
                    stepDiv.className = 'build-step';
                    stepDiv.textContent = step;
                    flow.appendChild(stepDiv);
                    
                    if (sIdx < bo.sequence.length - 1) {
                        const arrow = document.createElement('div');
                        arrow.className = 'build-arrow';
                        arrow.innerHTML = '&#9656;';
                        flow.appendChild(arrow);
                    }
                });
                
                item.appendChild(header);
                item.appendChild(flow);
                seqList.appendChild(item);
            });
            
            // 2. Build Steps Pie Charts
            const steps = stats.build_steps || [[], [], [], [], []];
            const stepNames = ["1st Unit", "2nd Unit", "3rd Unit", "4th Unit", "5th Unit"];
            
            function setPieGradient(stepData, element) {
                let accumulatedPct = 0;
                let gradientSegments = [];
                
                stepData.forEach(item => {
                    const color = getUnitColor(item.unit);
                    const start = accumulatedPct;
                    const end = accumulatedPct + item.percentage;
                    accumulatedPct = end;
                    gradientSegments.push(`${color} ${start.toFixed(1)}% ${end.toFixed(1)}%`);
                });
                
                if (accumulatedPct < 99.9) {
                    gradientSegments.push(`rgba(255, 255, 255, 0.05) ${accumulatedPct.toFixed(1)}% 100%`);
                }
                
                element.style.background = `conic-gradient(${gradientSegments.join(', ')})`;
            }
            
            function populateLegend(stepData, element) {
                if (stepData.length === 0) {
                    const emptyMsg = document.createElement('div');
                    emptyMsg.style.color = 'var(--text-secondary)';
                    emptyMsg.style.textAlign = 'center';
                    emptyMsg.textContent = 'No data';
                    element.appendChild(emptyMsg);
                } else {
                    stepData.forEach(item => {
                        const legendItem = document.createElement('div');
                        legendItem.className = 'pie-legend-item';
                        
                        const label = document.createElement('div');
                        label.className = 'pie-legend-label';
                        
                        const colorDot = document.createElement('div');
                        colorDot.className = 'pie-legend-color';
                        colorDot.style.backgroundColor = getUnitColor(item.unit);
                        
                        const text = document.createElement('span');
                        text.textContent = item.unit;
                        
                        label.appendChild(colorDot);
                        label.appendChild(text);
                        
                        const pct = document.createElement('div');
                        pct.className = 'pie-legend-pct';
                        pct.textContent = `${item.percentage}%`;
                        
                        legendItem.appendChild(label);
                        legendItem.appendChild(pct);
                        element.appendChild(legendItem);
                    });
                }
            }
            
            steps.forEach((stepData, stepIdx) => {
                const card = document.createElement('div');
                card.className = 'pie-chart-card';
                
                if (stepIdx === 0) {
                    card.classList.add('featured');
                    
                    const infoDiv = document.createElement('div');
                    infoDiv.className = 'pie-chart-info';
                    
                    const title = document.createElement('div');
                    title.className = 'pie-chart-title';
                    title.textContent = stepNames[stepIdx];
                    infoDiv.appendChild(title);
                    
                    const legend = document.createElement('div');
                    legend.className = 'pie-legend';
                    populateLegend(stepData, legend);
                    infoDiv.appendChild(legend);
                    
                    card.appendChild(infoDiv);
                    
                    const pieCircle = document.createElement('div');
                    pieCircle.className = 'pie-circle';
                    setPieGradient(stepData, pieCircle);
                    card.appendChild(pieCircle);
                } else {
                    const title = document.createElement('div');
                    title.className = 'pie-chart-title';
                    title.textContent = stepNames[stepIdx];
                    card.appendChild(title);
                    
                    const pieCircle = document.createElement('div');
                    pieCircle.className = 'pie-circle';
                    setPieGradient(stepData, pieCircle);
                    card.appendChild(pieCircle);
                    
                    const legend = document.createElement('div');
                    legend.className = 'pie-legend';
                    populateLegend(stepData, legend);
                    card.appendChild(legend);
                }
                
                pieContainer.appendChild(card);
            });
        }

        // ==================== UNIT STATISTICS VIEW ====================
        function loadUnitStatsView(data) {
            const grid = document.getElementById('unitStatsGrid');
            grid.innerHTML = '';
            
            const stats = data.stats;
            if (!stats || !stats.games_count) {
                grid.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); grid-column: 1 / -1; text-align: center;">No unit statistics available. Run build stats collector.</div>';
                return;
            }
            
            // Get list of all distinct unit types present in any of the categories
            const allUnits = new Set([
                ...Object.keys(stats.avg_built),
                ...Object.keys(stats.avg_lost),
                ...Object.keys(stats.avg_destroyed),
                ...Object.keys(stats.avg_captured),
                ...Object.keys(stats.avg_upgraded)
            ]);
            
            if (allUnits.size === 0) {
                grid.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); grid-column: 1 / -1; text-align: center;">No buildings or units recorded for the winner.</div>';
                return;
            }
            
            // Find peak values to scale charts relative to each other (optional, or scale each card to 100% locally)
            const findPeak = (unit, key) => stats[key] && stats[key][unit] ? stats[key][unit] : 0;
            
            Array.from(allUnits).sort().forEach(unit => {
                const card = document.createElement('div');
                card.className = 'unit-card';
                
                const title = document.createElement('div');
                title.className = 'unit-card-title';
                title.textContent = unit;
                card.appendChild(title);
                
                // We will add Built, Lost, Destroyed, Captured
                const metrics = [
                    { label: 'Built', key: 'avg_built', fillClass: 'fill-built' },
                    { label: 'Lost', key: 'avg_lost', fillClass: 'fill-lost' },
                    { label: 'Destroyed (Enemy)', key: 'avg_destroyed', fillClass: 'fill-destroyed' },
                    { label: 'Captured', key: 'avg_captured', fillClass: 'fill-captured' }
                ];
                
                // Compute local max to scale this card's bar chart values
                let localMax = 1;
                metrics.forEach(m => {
                    const val = findPeak(unit, m.key);
                    if (val > localMax) localMax = val;
                });
                
                metrics.forEach(m => {
                    const val = findPeak(unit, m.key);
                    if (val === 0 && m.label !== 'Built') return; // Omit if 0, except for Built
                    
                    const row = document.createElement('div');
                    row.className = 'unit-metric-row';
                    
                    const labelDiv = document.createElement('div');
                    labelDiv.className = 'unit-metric-label';
                    labelDiv.innerHTML = `<span>${m.label}</span><span class="unit-metric-val">${val}</span>`;
                    
                    const barOuter = document.createElement('div');
                    barOuter.className = 'metric-bar-outer';
                    
                    const barFill = document.createElement('div');
                    barFill.className = `metric-bar-fill ${m.fillClass}`;
                    barOuter.appendChild(barFill);
                    
                    row.appendChild(labelDiv);
                    row.appendChild(barOuter);
                    card.appendChild(row);
                    
                    // Trigger fill
                    const percentage = (val / localMax) * 100;
                    setTimeout(() => {
                        barFill.style.width = `${percentage}%`;
                    }, 50);
                });
                
                grid.appendChild(card);
            });
        }

        // Initialize view
        populateMapSelect();
        if (activeSlug) {
            renderActiveView();
        } else {
            document.querySelector('.container').innerHTML = '<div style="padding: 40px; color: var(--text-secondary);">No map data found. Run the extraction scripts first.</div>';
        }
    </script>
</body>
</html>"""

    # Insert JSON data
    html_content = html_template.replace("/* DATA */", json.dumps(map_data, indent=2))
    
    # Save the output file
    try:
        with open(output_path, mode='w', encoding='utf-8') as f:
            f.write(html_content)
        if VERBOSE:
            print(f"Dashboard successfully created at: {output_path}")
    except Exception as e:
        log_err(f"Error: Failed to write HTML file {output_path}: {e}")

def main():
    csv_file = "games.csv"
    stats_dir = "winner_build_stats_by_map"
    output_file = "dashboard.html"
    
    # Simple CLI argument parsing
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--games" and i + 1 < len(args):
            csv_file = args[i+1]
        elif arg == "--stats" and i + 1 < len(args):
            stats_dir = args[i+1]
        elif arg == "--output" and i + 1 < len(args):
            output_file = args[i+1]

    if VERBOSE:
        print("Parsing games.csv spawn heatmaps...")
    map_data = parse_games_csv(csv_file)
    
    if VERBOSE:
        print(f"Parsing winner statistics from directory '{stats_dir}'...")
    stats_data = parse_winner_stats(stats_dir)
    
    # Merge stats_data into map_data
    for slug in map_data:
        if slug in stats_data:
            map_data[slug]["stats"] = stats_data[slug]
        else:
            map_data[slug]["stats"] = {
                "games_count": 0,
                "top_build_orders": [],
                "first_units": {},
                "avg_built": {},
                "avg_lost": {},
                "avg_destroyed": {},
                "avg_captured": {},
                "avg_upgraded": {}
            }
            
    for slug in stats_data:
        if slug not in map_data:
            manifest = fetch_map_manifest(slug)
            base_dim = manifest.get("map", {})
            width = int(base_dim.get("width", 2048))
            height = int(base_dim.get("height", 1024))
            map_data[slug] = {
                "name": manifest.get("name") or slug.capitalize(),
                "width": width,
                "height": height,
                "points": [],
                "stats": stats_data[slug]
            }
            
    # Sort maps by games count (stats games count or points length) descending
    sorted_map_data = dict(sorted(
        map_data.items(),
        key=lambda item: len(item[1]["points"]) if item[1]["points"] else item[1]["stats"]["games_count"],
        reverse=True
    ))
    
    if VERBOSE:
        print("Generating unified dashboard.html...")
    generate_html_dashboard(sorted_map_data, output_file)
    
    total_maps = len(sorted_map_data)
    if not VERBOSE:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] Dashboard updated with {total_maps} maps.")
        
    # Clean up game cache files (optional) - Potentially move to a different file or step
    cleanup_game_cache(csv_file, stats_dir) 

if __name__ == "__main__":
    main()
