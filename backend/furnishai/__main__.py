"""Run FurnishAI locally: python -m furnishai [--port 8000]. Binds to 127.0.0.1 only."""

import argparse
import os

import uvicorn

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-live", action="store_true", help="never call the AI model (demo/offline use)")
    parser.add_argument("--storage", help="storage directory (default: ./storage)")
    args = parser.parse_args()
    if args.no_live:
        os.environ["FURNISHAI_DISABLE_LIVE"] = "1"
    if args.storage:
        os.environ["FURNISHAI_STORAGE_DIR"] = args.storage
    from .app import create_app
    from .config import get_settings

    settings = get_settings()
    status = settings.public_status()
    print(f"Furniture AI on http://127.0.0.1:{args.port}  model={status['model']}  "
          f"live AI={'available' if status['live_ai_available'] else 'unavailable (demo mode still works)'}  "
          f"key source={status['key_source'] or 'none'}")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
