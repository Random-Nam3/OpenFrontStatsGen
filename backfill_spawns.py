#!/usr/bin/env python3
"""
OpenFront Stats Generator - Historical Backfiller
This script runs find_spawn.py in 15-minute steps going back a specified number of hours
(default 24 hours) to backfill historical match winner spawn coordinates into games.csv.
"""

import sys
import time
import subprocess
from datetime import datetime, timedelta, timezone

def run_backfill():
    # 1. Determine how many hours to go back
    hours = 24
    verbose = False
    
    # Simple CLI argument parsing
    args = sys.argv[1:]
    if "-v" in args or "--verbose" in args:
        verbose = True
        # Remove verbose flags from args list to check for numeric hours
        args = [a for a in args if a not in ("-v", "--verbose")]
        
    if args:
        try:
            hours = int(args[0])
        except ValueError:
            print(f"Error: Invalid hours value '{args[0]}'. Please provide an integer.", file=sys.stderr)
            sys.exit(1)
            
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours)
    
    print(f"Starting historical backfill for the last {hours} hours...")
    print(f"Timeframe: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC to {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Running in 15-minute intervals (with a 2-second delay to avoid rate-limiting)...")
    print("=" * 70)
    
    current_start = start_time
    total_steps = int((now - start_time).total_seconds() / (15 * 60))
    step = 0
    
    while current_start < now:
        step += 1
        current_end = current_start + timedelta(minutes=15)
        
        # Format times as ISO strings
        start_str = current_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = current_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        print(f"[{step}/{total_steps}] Processing interval: {start_str} to {end_str}...", end="", flush=True)
        
        # Prepare subprocess arguments
        cmd = ["python3", "find_spawn.py", "--start", start_str, "--end", end_str]
        if verbose:
            cmd.append("-v")
            print() # Print newline if verbose is active
            
        # Execute find_spawn.py for the window
        result = subprocess.run(cmd, capture_output=not verbose, text=True)
        
        if not verbose:
            if result.returncode == 0:
                # Output the single summary line printed by find_spawn.py
                output_line = result.stdout.strip()
                if output_line:
                    print(f" {output_line}")
                else:
                    print(" Completed.")
            else:
                print(f" Failed with return code {result.returncode}.")
                if result.stderr:
                    print(f"Error Details: {result.stderr.strip()}", file=sys.stderr)
                    
        # Sleep for a short duration to avoid rate limits
        time.sleep(2.0)
        
        current_start = current_end
        
    print("=" * 70)
    print("Historical backfill completed successfully!")

if __name__ == "__main__":
    run_backfill()
