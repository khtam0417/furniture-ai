"""Start FurnishAI without setting PYTHONPATH: .venv/bin/python serve.py [--port 8000] [--no-live]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from furnishai.__main__ import main  # noqa: E402

main()
