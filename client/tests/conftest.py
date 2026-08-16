import sys
from pathlib import Path

CLIENT_DIR = str(Path(__file__).resolve().parent.parent)
if CLIENT_DIR not in sys.path:
    sys.path.insert(0, CLIENT_DIR)
