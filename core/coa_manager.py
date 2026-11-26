"""Chart of Accounts Manager & Tally-Style Running Balance Account Ledger Statement Engine."""

from __future__ import annotations
import pathlib
import uuid
from typing import Dict, Any, List, Optional
from core.database import get_connection
from core.ledger import from_minor


def create_gl_account(
    code: str,
    name: str,
    account_type: str,
    parent_group: str,
    currency_code: str = "USD",
    is_monetary: bool = True,
    enable_bill_by_bill: bool = False,
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Creates a new custom General Ledger account in the Chart of Accounts."""
    atype = account_type.upper().strip()
    if atype not in ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"):
        raise ValueError(f"Invalid account_type: {account_type}")

    acc_id = f"ACC-{code.strip()}-{uuid.uuid4().hex[:4].upper()}"
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO accounts
            (account_id, code, name, account_type, parent_group, currency_code, is_monetary, enable_bill_by_bill)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                acc_id,
                code.strip(),
                name.strip(),
                atype,
                parent_group.strip(),
                currency_code.upper().strip(),
                1 if is_monetary else 0,
                1 if enable_bill_by_bill else 0,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (acc_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_account_ledger_statement(
    account_code: str,
    limit: int = 200,
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """
    Produces a chronological Tally-style Running Balance Ledger Statement for any GL account:
    Every Debit/Credit posting with running native & functional USD balances.
    """
    conn = get_connection(db_path)
    try:
        acc = conn.execute("SELECT * FROM accounts WHERE code = ?", (account_code.strip(),)).fetchone()
        if not acc:
            raise ValueError(f"GL Account {account_code} not found.")

        rows = conn.execute(
            """
            SELECT
                pl.line_id, pl.native_amount_minor, pl.native_currency,
                pl.functional_amount_minor, pl.functional_currency,
                pl.exchange_rate, pl.bill_ref, pl.party_name,
                v.voucher_id, v.voucher_number, v.voucher_type,
                v.effective_date, v.narration, v.status
            FROM posting_lines pl
            JOIN vouchers v ON v.voucher_id = pl.voucher_id
            WHERE pl.account_id = ?
            ORDER BY v.effective_date ASC, v.created_at ASC, pl.rowid ASC
            LIMIT ?
            """,
            (acc["account_id"], limit),
        ).fetchall()
    finally:
        conn.close()

    running_native = 0
    running_func = 0
    total_dr_func = 0
    total_cr_func = 0
    entries: List[Dict[str, Any]] = []

    for r in rows:
        nat = r["native_amount_minor"]
        fn = r["functional_amount_minor"]
        running_native += nat
        running_func += fn
        if fn > 0:
            total_dr_func += fn
        else:
            total_cr_func += -fn

        entries.append(
            {
                "effective_date": r["effective_date"],
                "voucher_number": r["voucher_number"],
                "voucher_type": r["voucher_type"],
                "narration": r["narration"],
                "party_name": r["party_name"] or "",
                "bill_ref": r["bill_ref"] or "",
                "native_currency": r["native_currency"],
                "exchange_rate": r["exchange_rate"],
                "native_debit": from_minor(nat) if nat > 0 else 0.0,
                "native_credit": from_minor(-nat) if nat < 0 else 0.0,
                "functional_debit": from_minor(fn) if fn > 0 else 0.0,
                "functional_credit": from_minor(-fn) if fn < 0 else 0.0,
                "running_native_balance": from_minor(running_native),
                "running_functional_balance": from_minor(running_func),
            }
        )

    return {
        "account": dict(acc),
        "total_entries": len(entries),
        "total_debit_usd": from_minor(total_dr_func),
        "total_credit_usd": from_minor(total_cr_func),
        "closing_native_balance": from_minor(running_native),
        "closing_functional_balance": from_minor(running_func),
        "entries": entries,
    }
