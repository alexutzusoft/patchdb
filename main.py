"""Entrypoint for PatchDB CLI."""

import sys
from pathlib import Path

# Add root directory to system path to resolve local src package imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
