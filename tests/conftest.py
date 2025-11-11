"""
Pytest configuration and shared fixtures.
"""
import sys
from pathlib import Path

# Ensure src is in path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
