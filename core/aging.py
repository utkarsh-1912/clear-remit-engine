"""Bill-by-Bill AR Aging Schedule & Operating/Investing/Financing Cash Flow Statement Engine."""

from __future__ import annotations
import pathlib
from datetime import datetime
from typing import Dict, Any, List, Optional
from core.database import get_connection
from core.ledger import from_minor


def generate_cashflow_and_aging(
    as_of_date: str = "2026-11-10",
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """
    Computes:
      1. Direct-Method Cash Flow Statement (Operating, Investing, Financing Cash Flows).
      2. Bill-by-Bill Accounts Receivable Aging Schedule grouped by Bill Ref & Party.
    """
    conn = get_connection(db_path)
    try:
        # 1. Cash Flow classification from all cash/bank/nostro posting lines (1010..1020)
        cf_rows = conn.execute(
            """
            SELECT
                v.voucher_type,
                COALESCE(SUM(pl.functional_amount_minor), 0) AS net_cash_minor
            FROM posting_lines pl
            JOIN accounts a ON a.account_id = pl.account_id
            JOIN vouchers v ON v.voucher_id = pl.voucher_id
            WHERE a.code IN ('1010', '1011', '1012', '1013', '1014', '1020')
            GROUP BY v.voucher_type
            """
        ).fetchall()

        # 2. Bill-by-Bill Open AR Sub-Ledger Balances (Accounts 1200, 1201, 1290)
        bill_rows = conn.execute(
            """
            SELECT
                COALESCE(pl.bill_ref, 'UNALLOCATED') AS bill_ref,
                COALESCE(MAX(pl.party_name), 'Trade Customer') AS party_name,
                a.code AS account_code,
                a.currency_code,
                MIN(v.effective_date) AS first_date,
                COALESCE(SUM(pl.native_amount_minor), 0) AS open_native_minor,
                COALESCE(SUM(pl.functional_amount_minor), 0) AS open_func_minor
            FROM posting_lines pl
            JOIN accounts a ON a.account_id = pl.account_id
            JOIN vouchers v ON v.voucher_id = pl.voucher_id
            WHERE a.code IN ('1200', '1201', '1290')
            GROUP BY COALESCE(pl.bill_ref, 'UNALLOCATED'), a.code
            HAVING open_func_minor != 0
            ORDER BY open_func_minor DESC
            """
        ).fetchall()
    finally:
        conn.close()

    operating_minor = 0
    investing_minor = 0
    financing_minor = 0
    fx_reval_minor = 0

    for r in cf_rows:
        vtype = r["voucher_type"]
        val = r["net_cash_minor"]
        if vtype in ("RECEIPT", "PAYMENT", "SALES", "PURCHASE", "CONTRA_FX"):
            operating_minor += val
        elif vtype == "TRADE_SETTLEMENT":
            investing_minor += val
        elif vtype == "REVALUATION":
            fx_reval_minor += val
        else:
            # Opening capital injections / equity journals
            financing_minor += val

    ref_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    buckets = {"0_30_days": 0, "31_60_days": 0, "61_90_days": 0, "90_plus_days": 0}
    bill_items: List[Dict[str, Any]] = []

    for br in bill_rows:
        try:
            age_days = max(0, (ref_dt - datetime.strptime(br["first_date"], "%Y-%m-%d")).days)
        except Exception:
            age_days = 0
        amt = br["open_func_minor"]
        if age_days <= 30:
            bucket = "0-30 Days"
            buckets["0_30_days"] += amt
        elif age_days <= 60:
            bucket = "31-60 Days"
            buckets["31_60_days"] += amt
        elif age_days <= 90:
            bucket = "61-90 Days"
            buckets["61_90_days"] += amt
        else:
            bucket = "90+ Days"
            buckets["90_plus_days"] += amt

        bill_items.append(
            {
                "bill_ref": br["bill_ref"],
                "party_name": br["party_name"],
                "account_code": br["account_code"],
                "currency_code": br["currency_code"],
                "booking_date": br["first_date"],
                "age_days": age_days,
                "aging_bucket": bucket,
                "open_native": from_minor(br["open_native_minor"]),
                "open_usd": from_minor(amt),
            }
        )

    return {
        "as_of_date": as_of_date,
        "cash_flow_statement": {
            "operating_activities": from_minor(operating_minor),
            "investing_activities": from_minor(investing_minor),
            "financing_activities": from_minor(financing_minor),
            "fx_translation_effect_on_cash": from_minor(fx_reval_minor),
            "net_change_in_cash": from_minor(operating_minor + investing_minor + financing_minor + fx_reval_minor),
        },
        "ar_aging": {
            "buckets": {k: from_minor(v) for k, v in buckets.items()},
            "total_open_ar_usd": from_minor(sum(buckets.values())),
            "bills": bill_items,
        },
    }
