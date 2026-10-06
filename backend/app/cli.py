"""Management commands.

  python -m app.cli gen-key                         # print a new ENCRYPTION_KEY
  python -m app.cli create-user EMAIL PASSWORD [NAME]
"""

import sys

from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.db import session_scope
from app.models import User
from app.security import hash_password


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command = argv[0]
    if command == "gen-key":
        print(Fernet.generate_key().decode())
        return 0
    if command == "create-user":
        if len(argv) < 3:
            print("usage: create-user EMAIL PASSWORD [NAME]")
            return 2
        email, password = argv[1].lower(), argv[2]
        name = " ".join(argv[3:]) or email.split("@")[0]
        with session_scope() as db:
            if db.scalar(select(User).where(func.lower(User.email) == email)):
                print(f"{email} already exists")
                return 1
            first = not db.scalar(select(func.count(User.id)))
            db.add(User(email=email, password_hash=hash_password(password), name=name, role="owner" if first else "member"))
        print(f"Created {email}")
        return 0
    print(f"unknown command {command}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
