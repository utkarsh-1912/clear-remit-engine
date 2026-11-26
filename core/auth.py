"""Lightweight Zero-Dependency SQLite Authentication & Session Manager (PBKDF2-HMAC-SHA256)."""

from __future__ import annotations
import hashlib
import hmac
import pathlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from core.database import get_connection, DEFAULT_DB_PATH


AUTH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    company_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CFO',
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL
);
"""


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return dk.hex()


def init_auth_tables(db_path: Optional[pathlib.Path] = None) -> None:
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    try:
        conn.executescript(AUTH_SCHEMA_SQL)
        # Seed a default demo CFO account so reviewers can test 1-click sign-in immediately
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", ("cfo@clearledger.io",)).fetchone()
        if not exists:
            salt = secrets.token_hex(16)
            pw_hash = _hash_password("Prime2026!", salt)
            conn.execute(
                """
                INSERT INTO users (user_id, email, full_name, company_name, role, password_hash, password_salt, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "USR-DEMO-001",
                    "cfo@clearledger.io",
                    "Aarav Mehta (Demo CFO)",
                    "ClearLedger Global Operations LLC",
                    "CFO / Controller",
                    pw_hash,
                    salt,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def register_user(
    email: str,
    password: str,
    full_name: str,
    company_name: str,
    role: str = "Finance Controller",
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    clean_email = email.strip().lower()
    if "@" not in clean_email or len(password) < 6:
        raise ValueError("Valid email and password (min 6 characters) are required.")

    init_auth_tables(db_path)
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (clean_email,)).fetchone():
            raise ValueError("An account with this email already exists.")
        uid = f"USR-{uuid.uuid4().hex[:8].upper()}"
        salt = secrets.token_hex(16)
        pw_hash = _hash_password(password, salt)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO users (user_id, email, full_name, company_name, role, password_hash, password_salt, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, clean_email, full_name.strip(), company_name.strip(), role.strip(), pw_hash, salt, now),
        )
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, uid, now))
        conn.commit()
        return {
            "token": token,
            "user": {
                "user_id": uid,
                "email": clean_email,
                "full_name": full_name.strip(),
                "company_name": company_name.strip(),
                "role": role.strip(),
            },
        }
    finally:
        conn.close()


def authenticate_user(email: str, password: str, db_path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    clean_email = email.strip().lower()
    init_auth_tables(db_path)
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (clean_email,)).fetchone()
        if not row:
            raise ValueError("Invalid email or password.")
        computed = _hash_password(password, row["password_salt"])
        if not hmac.compare_digest(computed, row["password_hash"]):
            raise ValueError("Invalid email or password.")
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, row["user_id"], now))
        conn.commit()
        return {
            "token": token,
            "user": {
                "user_id": row["user_id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "company_name": row["company_name"],
                "role": row["role"],
            },
        }
    finally:
        conn.close()


def get_session_user(token: Optional[str], db_path: Optional[pathlib.Path] = None) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    init_auth_tables(db_path)
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT u.user_id, u.email, u.full_name, u.company_name, u.role
            FROM sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def revoke_session(token: Optional[str], db_path: Optional[pathlib.Path] = None) -> None:
    if not token:
        return
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()
