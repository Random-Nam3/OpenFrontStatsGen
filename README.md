# OpenFront Stats & Spawn Heatmap Generator

A Python toolchain to collect OpenFront match results, extract winner spawn locations, and overlay them onto interactive canvas heatmaps.

## Quick Start

No dependencies required. Just Python 3.8+.

```bash
# Fetch recent games (last 30m) & append to games.csv
python3 find_spawn.py

# Backfill historical games (e.g., last 24 hours)
# Note: Use with care, as larger hours generate high API usage.
python3 backfill_spawns.py 24

# Re-generate the heatmap dashboard
python3 generate_heatmap.py
```

Open the generated `heatmap.html` in any web browser to view the interactive dashboard.

---

## File Structure

- [find_spawn.py](find_spawn.py) – Queries API and writes spawn coordinates to `games.csv`.
- [backfill_spawns.py](backfill_spawns.py) – Historical data backfill helper. *Beware: querying large windows consumes substantial API bandwidth and may trigger rate limits.*
- [generate_heatmap.py](generate_heatmap.py) – Renders points into the interactive `heatmap.html` dashboard.
- [utils.py](utils.py) – Request helper and `map_cache/` manifest caching.
- [API.md](API.md) – Reference documentation for the OpenFront Public API.

---

## macOS Automation (`launchctl`)

On macOS, `launchd` is the preferred daemon manager. To automate the collector to run every 15 minutes, follow these steps:

1. Create a file at `~/Library/LaunchAgents/io.openfront.statsgen.plist` (replacing `/path/to/` with your actual directory path):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.openfront.statsgen</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd /path/to/OpenFrontStatsGen && /usr/bin/python3 find_spawn.py && /usr/bin/python3 generate_heatmap.py</string>
    </array>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>StandardOutPath</key>
    <string>/path/to/OpenFrontStatsGen/output.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/OpenFrontStatsGen/error.log</string>
</dict>
</plist>
```

2. Load and start the background agent:
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.openfront.statsgen.plist
```

3. (Optional) To stop and unload the agent:
```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.openfront.statsgen.plist
```
