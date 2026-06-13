#!/usr/bin/env python3
"""
OpenFront Stats Generator - Heatmap Generator
This script reads the spawn coordinates of winners from games.csv,
resolves map dimensions via cached manifests or raw GitHub resources, and generates a beautiful,
interactive HTML page with heatmaps overlaying geographic map thumbnails.
"""

import json
import os
import csv
import sys
from datetime import datetime
from utils import VERBOSE, log_err, get_map_slug, fetch_map_manifest

def parse_games_csv(csv_path: str) -> dict:
    """Reads the CSV file and maps tile numbers to 2D coordinates using fetched map dimensions."""
    if not os.path.isfile(csv_path):
        log_err(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)
        
    map_data = {}
    
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        # Check if header contains columns for x and y
        has_xy = header and len(header) >= 5 and header[3].strip().lower() == "x" and header[4].strip().lower() == "y"
        
        for row in reader:
            if not row or len(row) < 3:
                continue
                
            game_id, map_name, start_loc = row[0].strip(), row[1].strip(), row[2].strip()
            slug = get_map_slug(map_name)
            
            # 1. Try to read x and y columns directly (if present and populated)
            x_coord, y_coord = None, None
            if has_xy and len(row) >= 5:
                try:
                    if row[3].strip() and row[4].strip():
                        x_coord = int(row[3].strip())
                        y_coord = int(row[4].strip())
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
                    "manifest": manifest,
                    "points": []
                }
            
            # 3. Resolve coordinate
            if x_coord is not None and y_coord is not None:
                map_data[slug]["points"].append({"x": x_coord, "y": y_coord})
            else:
                # Fallback for old entries without x, y columns
                # e.g., "Tile 396578" or coordinates encoded in start_loc
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
                    # Resolve tile index using the resolution scale heuristic
                    manifest = map_data[slug]["manifest"]
                    base_w = map_data[slug]["width"]
                    base_h = map_data[slug]["height"]
                    
                    # Heuristic: Check if tile index fits in map4x (Compact game)
                    map4x = manifest.get("map4x", {})
                    w_4x = map4x.get("width")
                    h_4x = map4x.get("height")
                    
                    if w_4x and h_4x and tile_index < (w_4x * h_4x):
                        # Calculate on 4x grid and scale up
                        x_4x = tile_index % w_4x
                        y_4x = tile_index // w_4x
                        scaled_x = int(x_4x * (base_w / w_4x))
                        scaled_y = int(y_4x * (base_h / h_4x))
                        map_data[slug]["points"].append({"x": scaled_x, "y": scaled_y})
                    else:
                        # Assume base map
                        x_base = tile_index % base_w
                        y_base = tile_index // base_w
                        map_data[slug]["points"].append({"x": x_base, "y": y_base})
                        
    # Remove raw manifest objects before passing to template JSON
    for slug in map_data:
        map_data[slug].pop("manifest", None)
        
    # Sort maps by sample (point) count descending
    sorted_map_data = dict(sorted(
        map_data.items(),
        key=lambda item: len(item[1]["points"]),
        reverse=True
    ))
        
    return sorted_map_data

def generate_html_heatmap(map_data: dict, output_path: str):
    """Generates the interactive HTML page with heatmaps overlaying thumbnails."""
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenFront Spawn Heatmaps</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0d0f14;
            --card-color: #161a23;
            --text-color: #e2e8f0;
            --accent-color: #3b82f6;
            --border-color: #2e3548;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
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
            color: #94a3b8;
            margin: 0;
        }

        .container {
            max-width: 95vw;
            width: 95%;
            margin: 40px 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 30px;
        }

        .controls {
            width: 100%;
            display: flex;
            justify-content: center;
        }

        .map-grid {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 16px;
            max-width: 1200px;
            width: 100%;
        }

        .map-card {
            background-color: var(--card-color);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 12px 24px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 14px;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
            min-width: 180px;
        }

        .map-card:hover {
            transform: translateY(-2px);
            border-color: rgba(59, 130, 246, 0.5);
            background: rgba(22, 26, 35, 0.85);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }

        .map-card.active {
            border-color: var(--accent-color);
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.08), rgba(37, 99, 235, 0.15));
            box-shadow: 0 0 16px 2px rgba(37, 99, 235, 0.25);
        }

        .map-card-icon {
            width: 38px;
            height: 38px;
            border-radius: 8px;
            background-size: cover;
            background-position: center;
            border: 1px solid rgba(255, 255, 255, 0.08);
            transition: transform 0.25s ease;
        }
        
        .map-card:hover .map-card-icon {
            transform: scale(1.08);
        }

        .map-card-info {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
        }

        .map-card-name {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--text-color);
        }

        .map-card-count {
            font-size: 0.75rem;
            color: #94a3b8;
            margin-top: 2px;
            background: rgba(255, 255, 255, 0.04);
            padding: 1px 8px;
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        .map-card.active .map-card-count {
            color: #60a5fa;
            background: rgba(59, 130, 246, 0.15);
            border-color: rgba(59, 130, 246, 0.25);
        }

        .visualization {
            position: relative;
            background-color: var(--card-color);
            border-radius: 16px;
            border: 1px solid var(--border-color);
            padding: 20px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
            display: flex;
            justify-content: center;
            align-items: center;
            max-width: 100%;
            width: 100%;
            box-sizing: border-box;
            overflow: hidden;
        }

        .map-wrapper {
            position: relative;
            max-width: 1400px;
            width: 100%;
            aspect-ratio: auto;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #1e293b;
        }

        .map-bg {
            display: block;
            width: 100%;
            height: auto;
            object-fit: contain;
            opacity: 0.65;
            transition: opacity 0.3s;
        }

        .map-bg:hover {
            opacity: 0.8;
        }

        canvas {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
        }

        .stats {
            display: flex;
            gap: 20px;
            margin-top: 10px;
        }

        .stat-card {
            background-color: var(--card-color);
            border: 1px solid var(--border-color);
            padding: 15px 25px;
            border-radius: 12px;
            text-align: center;
        }

        .stat-val {
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--accent-color);
        }

        .stat-lbl {
            font-size: 0.85rem;
            color: #94a3b8;
            margin-top: 5px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        footer {
            margin-top: auto;
            margin-bottom: 30px;
            font-size: 0.9rem;
            color: #475569;
        }
    </style>
</head>
<body>
    <header>
        <h1>OpenFront Spawn Heatmaps</h1>
        <p class="subtitle">Winners' starting locations superimposed on map geography</p>
    </header>

    <div class="container">
        <div class="controls">
            <div class="map-grid" id="mapGrid">
                <!-- Map cards populated dynamically -->
            </div>
        </div>

        <div class="visualization">
            <div class="map-wrapper" id="mapWrapper">
                <img id="mapBackground" class="map-bg" src="" alt="Map Geography">
                <canvas id="heatmapCanvas"></canvas>
            </div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="stat-val" id="winCount">0</div>
                <div class="stat-lbl">Sampled Wins</div>
            </div>
            <div class="stat-card">
                <div class="stat-val" id="dimensions">0 x 0</div>
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

        function populateSelect() {
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
                count.textContent = `${mapData[slug].points.length} samples`;
                
                info.appendChild(name);
                info.appendChild(count);
                
                card.appendChild(icon);
                card.appendChild(info);
                
                grid.appendChild(card);
            });
        }

        function selectMap(slug) {
            if (activeSlug) {
                const prevCard = document.getElementById(`card-${activeSlug}`);
                if (prevCard) prevCard.classList.remove('active');
            }
            
            activeSlug = slug;
            const card = document.getElementById(`card-${slug}`);
            if (card) card.className = 'map-card active';
            
            loadMapHeatmap(slug);
        }

        function loadMapHeatmap(slug) {
            const data = mapData[slug];
            if (!data) return;

            // Update stats
            document.getElementById('winCount').textContent = data.points.length;
            document.getElementById('dimensions').textContent = `${data.width} × ${data.height}`;

            // Load background image from raw GitHub CDN with CORS enabled
            const bgImg = document.getElementById('mapBackground');
            bgImg.crossOrigin = 'anonymous';
            bgImg.src = `https://raw.githubusercontent.com/openfrontio/OpenFrontIO/main/resources/maps/${slug}/thumbnail.webp`;

            // Draw heatmap once image load establishes aspect ratios
            bgImg.onload = () => {
                drawHeatmap(data);
            };
            
            // Fallback draw in case image cached
            if (bgImg.complete) {
                drawHeatmap(data);
            }
        }

        function drawHeatmap(data) {
            const canvas = document.getElementById('heatmapCanvas');
            canvas.width = data.width;
            canvas.height = data.height;
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, data.width, data.height);

            // Draw blurred density onto a temporary helper canvas
            const tempCanvas = document.createElement('canvas');
            tempCanvas.width = data.width;
            tempCanvas.height = data.height;
            const tempCtx = tempCanvas.getContext('2d');

            const radius = Math.max(30, Math.round(data.width * 0.025)); // Dynamic sizing based on map scale
            const intensity = 0.55;

            data.points.forEach(pt => {
                const grad = tempCtx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, radius);
                grad.addColorStop(0, `rgba(0,0,0,${intensity})`);
                grad.addColorStop(1, 'rgba(0,0,0,0)');
                tempCtx.fillStyle = grad;
                tempCtx.beginPath();
                tempCtx.arc(pt.x, pt.y, radius, 0, Math.PI * 2);
                tempCtx.fill();
            });

            // Colorize grayscale alphas on canvas
            const imgData = tempCtx.getImageData(0, 0, data.width, data.height);
            const pixels = imgData.data;
            const palette = getGradientPalette();

            for (let i = 0; i < pixels.length; i += 4) {
                const alpha = pixels[i + 3];
                if (alpha > 0) {
                    const colorIndex = alpha * 4;
                    pixels[i] = palette[colorIndex];
                    pixels[i + 1] = palette[colorIndex + 1];
                    pixels[i + 2] = palette[colorIndex + 2];
                }
            }
            ctx.putImageData(imgData, 0, 0);
        }

        function getGradientPalette() {
            const canvas = document.createElement('canvas');
            canvas.width = 1;
            canvas.height = 256;
            const ctx = canvas.getContext('2d');

            const grad = ctx.createLinearGradient(0, 0, 0, 256);
            grad.addColorStop(0, 'rgba(59, 130, 246, 0)'); // Blue glow transition
            grad.addColorStop(0.15, '#3b82f6');            // Soft Blue
            grad.addColorStop(0.4, '#10b981');             // Green mid-range
            grad.addColorStop(0.7, '#f59e0b');             // Yellow warnings
            grad.addColorStop(1.0, '#ef4444');             // Red hot points

            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 1, 256);
            return ctx.getImageData(0, 0, 1, 256).data;
        }

        // Initialize UI
        populateSelect();
        if (activeSlug) {
            loadMapHeatmap(activeSlug);
        } else {
            document.querySelector('.visualization').innerHTML = '<div style="padding: 40px; color: #64748b;">No coordinate data found. Run the spawn finder script to populate games.csv.</div>';
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
            print(f"Heatmap successfully created at: {output_path}")
    except Exception as e:
        log_err(f"Error: Failed to write HTML file: {e}")

def main():
    csv_file = "games.csv"
    output_file = "heatmap.html"
    
    if VERBOSE:
        print("Parsing games.csv...")
    map_data = parse_games_csv(csv_file)
    
    if VERBOSE:
        print("\nSamples per map:")
        for slug, data in map_data.items():
            print(f"  - {data['name']}: {len(data['points'])} samples")
        print()
        print("Generating interactive HTML visualization...")
        
    generate_html_heatmap(map_data, output_file)
    
    total_samples = sum(len(data["points"]) for data in map_data.values())
    
    if VERBOSE:
        print("=" * 60)
        print("To view the heatmap, simply open 'heatmap.html' in your browser.")
        print("=" * 60)
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] Heatmap updated with {total_samples} samples.")

if __name__ == "__main__":
    main()
