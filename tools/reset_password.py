#!/usr/bin/env python3
"""Reset a panel account's password from the machine that hosts the panel.

A Waggle panel runs offline on the beekeeper's own computer, so there is no e-mail and
therefore no reset link. Physical access to that computer already means access to the
SQLite file, so running this command locally is the recovery path: it proves ownership
the same way holding the machine does, without weakening the login itself.

    python -m tools.reset_password                 # list the accounts
    python -m tools.reset_password --username ilke # set a new password
"""

from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

# This is the recovery path a locked-out owner reaches for, printed on the sign-in screen,
# so it has to run however it is typed. `python -m tools.reset_password` puts the project
# root on the path; `python tools/reset_password.py` — which the shebang above invites —
# puts only tools/ there, and the import below failed with "No module named 'panel'".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app.auth import hash_password  # noqa: E402 - the path above has to be set first

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def database_path(explicit: str | None) -> Path:
    default = Path(__file__).resolve().parent.parent / "panel" / "data" / "waggle.db"
    return Path(explicit or os.getenv("WAGGLE_DB", default))


def accounts(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT username, display_name, role FROM users ORDER BY created_at"
    ).fetchall()


def read_new_password(supplied: str | None) -> str:
    if supplied is not None:
        return supplied
    password = getpass.getpass("Yeni parola: ")
    if password != getpass.getpass("Yeni parolayı doğrulayın: "):
        raise SystemExit("Parolalar eşleşmedi; hiçbir şey değiştirilmedi.")
    return password


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Waggle panel hesabının parolasını bu bilgisayardan sıfırlar."
    )
    parser.add_argument("--username", help="Parolası sıfırlanacak hesap")
    parser.add_argument("--db", help="Veritabanı yolu (varsayılan: WAGGLE_DB)")
    parser.add_argument(
        "--password",
        help="Parolayı sormadan ayarla. Kabuk geçmişine yazılır; etkileşimli kullanım yeğdir.",
    )
    args = parser.parse_args()

    path = database_path(args.db)
    if not path.exists():
        print(f"Veritabanı bulunamadı: {path}", file=sys.stderr)
        return 1

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = accounts(connection)
        if not rows:
            print("Bu panelde hesap yok. Paneli açıp ilk kurulumu tamamlayın.")
            return 1
        if not args.username:
            print(f"Veritabanı: {path}\nHesaplar:")
            for row in rows:
                print(f"  {row['username']}  ({row['display_name']}, {row['role']})")
            print("\nParolayı sıfırlamak için: --username <kullanıcı adı>")
            return 0

        match = next(
            (row for row in rows if row["username"].lower() == args.username.strip().lower()),
            None,
        )
        if match is None:
            print(f"Hesap bulunamadı: {args.username}", file=sys.stderr)
            return 1

        password = read_new_password(args.password)
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            print(
                f"Parola {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} karakter olmalıdır.",
                file=sys.stderr,
            )
            return 1

        password_salt, password_hash = hash_password(password)
        with connection:
            connection.execute(
                "UPDATE users SET password_salt = ?, password_hash = ? WHERE username = ?",
                (password_salt, password_hash, match["username"]),
            )
        print(f"{match['username']} hesabının parolası değiştirildi. Panelden giriş yapabilirsiniz.")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
