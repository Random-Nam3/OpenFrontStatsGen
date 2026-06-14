import sys
from unittest.mock import MagicMock

# Mock network and SSL modules to prevent sandbox path block during import
sys.modules['urllib.request'] = MagicMock()
sys.modules['urllib.error'] = MagicMock()
sys.modules['ssl'] = MagicMock()

import unittest
import os

# Adjust import path to find functions in parent directory
sys.path.append('.')

# We will import the functions to test. We can define placeholders or define them here.
# For simplicity, we'll write the implementation in find_winner_build_stats.py first,
# then test it. But wait, we can also implement them in the test file or import them directly.
# Let's import them from find_winner_build_stats.
from utils import extract_winner_client_id, fetch_game_details
from find_winner_build_stats import (
    extract_winner_build_order,
    extract_winner_unit_counts
)

class TestBuildStats(unittest.TestCase):
    def setUp(self):
        # Sample mock game details
        self.mock_game_info = {
            "winner": ["player", "win_1234"],
            "info": {
                "config": {
                    "gameMap": "Pluto"
                },
                "players": [
                    {
                        "clientID": "win_1234",
                        "username": "BestPlayer",
                        "stats": {
                            "units": {
                                "city": ["10", "1", "12", "5"],   # 10 built, 1 lost, 12 destroyed, 5 captured
                                "fact": ["3", "0", "4"],          # 3 built, 0 lost, 4 destroyed
                                "wshp": ["5", "2"]                # 5 built, 2 lost
                            }
                        }
                    },
                    {
                        "clientID": "loser_456",
                        "username": "WorstPlayer",
                        "stats": {
                            "units": {
                                "city": ["1", "5"]
                            }
                        }
                    }
                ]
            },
            "turns": [
                {
                    "turnNumber": 10,
                    "intents": [
                        {"type": "spawn", "tile": 1234, "clientID": "win_1234"},
                        {"type": "spawn", "tile": 5678, "clientID": "loser_456"}
                    ]
                },
                {
                    "turnNumber": 11,
                    "intents": [
                        {"type": "build_unit", "unit": "City", "clientID": "win_1234"},
                        {"type": "build_unit", "unit": "Port", "clientID": "loser_456"}
                    ]
                },
                {
                    "turnNumber": 12,
                    "intents": [
                        {"type": "build_unit", "unit": "City", "clientID": "win_1234"},
                        {"type": "upgrade_structure", "tile": 1234, "clientID": "win_1234"}
                    ]
                },
                {
                    "turnNumber": 13,
                    "intents": [
                        {"type": "build_unit", "unit": "Factory", "clientID": "win_1234"},
                        {"type": "build_unit", "unit": "Warship", "clientID": "win_1234"}
                    ]
                },
                {
                    "turnNumber": 14,
                    "intents": [
                        {"type": "build_unit", "unit": "Port", "clientID": "win_1234"}
                    ]
                }
            ]
        }

    def test_extract_winner_client_id(self):
        client_id, name = extract_winner_client_id(self.mock_game_info)
        self.assertEqual(client_id, "win_1234")
        self.assertEqual(name, "BestPlayer")

    def test_extract_winner_build_order_with_limit(self):
        build_order = extract_winner_build_order(self.mock_game_info, limit=3)
        self.assertEqual(build_order, ["City", "City", "Upgrade"])

    def test_extract_winner_build_order_no_limit(self):
        build_order = extract_winner_build_order(self.mock_game_info, limit=10)
        self.assertEqual(build_order, ["City", "City", "Upgrade", "Factory", "Warship", "Port"])

    def test_extract_winner_unit_counts(self):
        built, lost, destroyed, captured, upgraded = extract_winner_unit_counts(self.mock_game_info)
        
        # Verify totals mapped correctly:
        # Index 0: built
        # Index 1: lost
        # Index 2: destroyed
        # Index 3: captured
        self.assertEqual(built, {"city": 10, "fact": 3, "wshp": 5})
        self.assertEqual(lost, {"city": 1, "wshp": 2})
        self.assertEqual(destroyed, {"city": 12, "fact": 4})
        self.assertEqual(captured, {"city": 5})
        self.assertEqual(upgraded, {})

    def test_fetch_game_details_caching(self):
        import utils
        import shutil
        original_cache_dir = utils.GAME_CACHE_DIR
        utils.GAME_CACHE_DIR = "test_game_cache"
        
        # Ensure clean state
        if os.path.exists("test_game_cache"):
            shutil.rmtree("test_game_cache")
            
        mock_data = {"id": "game123", "data": "value"}
        
        # Mock make_request
        from unittest.mock import patch
        with patch('utils.make_request', return_value=mock_data) as mock_req:
            # First fetch (cache miss)
            result = fetch_game_details("game123")
            self.assertEqual(result, mock_data)
            mock_req.assert_called_once()
            
            # Verify cache file exists
            cache_file = os.path.join("test_game_cache", "game123.json")
            self.assertTrue(os.path.exists(cache_file))
            
            # Second fetch (cache hit)
            mock_req.reset_mock()
            result2 = fetch_game_details("game123")
            self.assertEqual(result2, mock_data)
            mock_req.assert_not_called()
            
        # Cleanup
        if os.path.exists("test_game_cache"):
            shutil.rmtree("test_game_cache")
        utils.GAME_CACHE_DIR = original_cache_dir

if __name__ == '__main__':
    unittest.main()
