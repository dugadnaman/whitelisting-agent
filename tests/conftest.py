import sys
from pathlib import Path

# Add project root and backend directory to sys.path so tests can import from backend directly
root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"

for p in (str(backend_dir), str(root_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)
