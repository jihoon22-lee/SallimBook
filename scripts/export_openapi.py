"""Export the API implementation's contract; no independent hand-written schema."""
import json
from pathlib import Path

from sallimbook.main import create_app

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "packages/api-client/openapi.json"

if __name__ == "__main__":
    DESTINATION.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
