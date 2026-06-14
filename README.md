# OpenFront Stats & Spawn Heatmap Generator

A Python toolchain to collect OpenFront match results, extract winner spawn locations, and compile detailed winner statistics (early build orders and final unit averages) into an interactive dashboard.

## Quick Start

No dependencies required. Just Python 3.8+.

```bash
# 1. Fetch recent games (last 30m) & append starting spawn locations to games.csv
python3 find_spawn.py

# 2. Extract winner build order sequences & unit stats from games
python3 find_winner_build_stats.py

# 3. Generate the unified match statistics & spawn heatmap dashboard
python3 generate_stats_view.py
```

Open the generated `dashboard.html` in any web browser to view the interactive dashboard.

---

## File Structure

- [find_spawn.py](find_spawn.py) – Queries API and writes spawn coordinates to `games.csv`.
- [find_winner_build_stats.py](find_winner_build_stats.py) – Queries turns/player stats and compiles winner build counts and order stats on a per-map basis under `winner_build_stats_by_map/`.
- [generate_stats_view.py](generate_stats_view.py) – Compiles spawn locations and winner stats to output the unified interactive `dashboard.html` dashboard.
- [backfill_spawns.py](backfill_spawns.py) – Historical data backfill helper. *Beware: querying large windows consumes substantial API bandwidth and may trigger rate limits.*
- [utils.py](utils.py) – Request helper and `map_cache/` manifest caching.
- [API.md](API.md) – Reference documentation for the OpenFront Public API.
- [tests/](tests/) – Unit test suite to verify the stats parser.

---

## macOS Automation (`launchctl`)

We have organized the background service automation files into the `autocounter/` directory (which is configured in `.gitignore` and not tracked in source control) to schedule and manage pipeline updates on macOS.

The pipeline automatically runs `find_spawn.py`, `find_winner_build_stats.py`, and `generate_stats_view.py` in sequence every **30 minutes** and logs execution details.
