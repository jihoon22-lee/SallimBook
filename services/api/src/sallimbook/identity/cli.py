"""Operator-only first-account enrollment. Tokens are never printed or passed as arguments."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.core.errors import DomainError
from sallimbook.identity.service import create_bootstrap_invitation, renew_bootstrap_invitation


def bootstrap_to_file(
    settings: Settings,
    household_name: str,
    login_name: str,
    token_file: Path,
    *,
    renew: bool = False,
) -> None:
    if settings.database_url is None:
        raise ValueError("A dedicated database connection is required")
    destination = token_file.expanduser().absolute()
    parent = destination.parent
    if parent.resolve(strict=True) != parent or not parent.is_dir():
        raise ValueError("Use a real private directory without symlink components")
    metadata = parent.stat()
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("Token directory must be owned by the operator and have mode 0700")
    if any((ancestor / ".git").exists() for ancestor in (parent, *parent.parents)):
        raise ValueError("Registration tokens must be stored outside Git working directories")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    engine = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            engine = make_engine(settings.database_url.get_secret_value())
            with Session(engine) as session:
                invitation = (
                    renew_bootstrap_invitation(session, login_name)
                    if renew
                    else create_bootstrap_invitation(session, household_name, login_name)
                )
                json.dump(
                    {
                        "invitation_token": invitation.token,
                        "expires_at": invitation.expires_at.isoformat(),
                    },
                    output,
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
                session.commit()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if engine is not None:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap", help="Create the first account's 15-minute code")
    bootstrap.add_argument("--household-name", required=True)
    bootstrap.add_argument("--login-name", required=True)
    bootstrap.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="New file in an operator-owned private directory outside Git",
    )
    renewal = commands.add_parser("renew-bootstrap", help="Replace an unused first-account code")
    renewal.add_argument("--login-name", required=True)
    renewal.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="New file in an operator-owned private directory outside Git",
    )
    args = parser.parse_args()
    try:
        bootstrap_to_file(
            Settings(),
            getattr(args, "household_name", ""),
            args.login_name,
            args.token_file,
            renew=args.command == "renew-bootstrap",
        )
    except DomainError as exc:
        print(exc.safe_message, file=sys.stderr)
        return 1
    except Exception:
        # Validation/driver exceptions can include supplied values or connection details.
        print(
            "등록 경로를 만들지 못했습니다. DB 연결과 비공개 파일 경로를 확인해 주세요.",
            file=sys.stderr,
        )
        return 1
    print("일회성 등록 코드를 지정한 비공개 파일에 저장했습니다. 유효 시간은 15분입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
