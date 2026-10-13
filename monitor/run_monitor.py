"""PyInstaller entry script (and a convenient `python run_monitor.py` when working from source)."""
import sys

from barpi_monitor.main import main

if __name__ == "__main__":
    sys.exit(main())
