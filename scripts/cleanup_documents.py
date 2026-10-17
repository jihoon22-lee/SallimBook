"""Preview/delete orphan or soft-deleted encrypted documents older than 24 hours."""

import argparse
import json

from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.documents.cleanup import cleanup_files
from sqlalchemy.orm import Session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Delete eligible ciphertext files"
    )
    args = parser.parse_args()
    settings = Settings()
    if settings.database_url is None or settings.document_storage_directory is None:
        raise SystemExit(
            "Configure the SallimBook database and private document store first."
        )
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as session:
            counts = cleanup_files(session, settings, apply=args.apply)
        print(json.dumps({"applied": args.apply, **counts}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
