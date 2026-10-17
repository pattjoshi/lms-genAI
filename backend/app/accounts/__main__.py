"""Manage accounts from the command line. Run from backend/:

uv run python -m app.accounts create-admin --email you@example.com --name "Your Name"
uv run python -m app.accounts set-password --email you@example.com
uv run python -m app.accounts set-role --email someone@example.com --role teacher

create-admin is how the FIRST admin is made: sign-up only creates students, and after that an admin
gives other roles on the Users page. The password is asked for (not passed on the command line), so it
doesn't end up in your shell history. If the email already has an account (for example you signed up
on the website first), it is promoted to admin and the password is set.
"""

import argparse
import asyncio
import getpass
import sys

from app.accounts.passwords import password_problem
from app.accounts.service import AccountError, change_password, create_user, user_by_email
from app.db import SessionLocal, engine
from app.models import Role
from app.schema import ensure_schema


def _ask_password(email: str) -> str:
    while True:
        first = getpass.getpass("New password: ")
        if problem := password_problem(first, email):
            print(problem, file=sys.stderr)
            continue
        if getpass.getpass("Repeat it: ") != first:
            print("The two passwords don't match.", file=sys.stderr)
            continue
        return first


async def main(args: argparse.Namespace) -> int:
    async with engine.begin() as conn:
        await ensure_schema(conn)  # the credential tables exist even before the backend's first start
    async with SessionLocal() as session:
        user = await user_by_email(session, args.email)
        try:
            if args.command == "create-admin":
                password = _ask_password(args.email)
                if user is None:
                    if not args.name:
                        print("New account: pass --name too.", file=sys.stderr)
                        return 1
                    user = await create_user(
                        session, full_name=args.name, email=args.email, password=password, role=Role.admin
                    )
                    print(f"Created admin {user.email}.")
                else:
                    user.role = Role.admin
                    user.is_active = True
                    await change_password(session, user, None, password)
                    print(f"{user.email} is now an admin, with the new password.")
            elif user is None:
                print(f"No account with the email {args.email}.", file=sys.stderr)
                return 1
            elif args.command == "set-password":
                await change_password(session, user, None, _ask_password(user.email))
                print(f"Password set for {user.email}.")
            elif args.command == "set-role":
                user.role = Role(args.role)
                print(f"{user.email} is now {user.role.value}.")
        except AccountError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        await session.commit()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.accounts", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first admin, or promote an existing account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", help="full name (needed when the account doesn't exist yet)")
    pw = sub.add_parser("set-password", help="set a password for any account (also seeded demo users)")
    pw.add_argument("--email", required=True)
    role = sub.add_parser("set-role", help="change someone's role")
    role.add_argument("--email", required=True)
    role.add_argument("--role", required=True, choices=[r.value for r in Role])
    sys.exit(asyncio.run(main(parser.parse_args())))
