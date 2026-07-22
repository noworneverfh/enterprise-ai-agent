"""Create the initial administrator from environment variables."""

from __future__ import annotations

import os

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.auth import Role
from app.services.auth import create_user, ensure_default_roles, get_user_by_username


def main() -> int:
    username = os.getenv("INITIAL_ADMIN_USERNAME", "").strip().lower()
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")

    if not username or not password:
        raise SystemExit(
            "INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD are required."
        )
    if len(username) < 3:
        raise SystemExit("INITIAL_ADMIN_USERNAME must contain at least 3 characters.")
    if len(password) < 8:
        raise SystemExit("INITIAL_ADMIN_PASSWORD must contain at least 8 characters.")

    with SessionLocal() as db:
        ensure_default_roles(db)
        existing = get_user_by_username(db, username)
        if existing is not None:
            if any(role.name == "admin" for role in existing.roles):
                print(f"Administrator '{username}' already exists.")
                return 0

            admin_role = db.scalar(select(Role).where(Role.name == "admin"))
            if admin_role is None:
                raise RuntimeError("The admin role was not initialized.")
            existing.roles.append(admin_role)
            db.commit()
            print(f"Administrator role granted to existing user '{username}'.")
            return 0

        create_user(
            db,
            username=username,
            password=password,
            role_name="admin",
        )
        print(f"Administrator '{username}' created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
