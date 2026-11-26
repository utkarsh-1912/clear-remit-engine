"""Multi-Currency FX Rate Matrix, Cross-Currency Contra Transfers, & IAS 21 Period-End Revaluation Engine."""

from __future__ import annotations
import pathlib
from decimal import Decimal
from typing import List, Dict, Any, Optional
from core.database import get_connection
from core.ledger import (
    PostingInput,
    post_voucher,
    reverse_voucher,
    lookup_fx_rate,
    to_minor,
    from_minor,
)


def list_fx_rates(db_path: Optional[pathlib.Path] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM fx_rates ORDER BY rate_date DESC, base_currency ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_fx_rate(
    rate_date: str,
    base_currency: str,
    spot_rate: str | Decimal,
    buy_rate: Optional[str | Decimal] = None,
    sell_rate: Optional[str | Decimal] = None,
    quote_currency: str = "USD",
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    spot_d = Decimal(str(spot_rate))
    buy_d = Decimal(str(buy_rate)) if buy_rate is not None else (spot_d * Decimal("0.996"))
    sell_d = Decimal(str(sell_rate)) if sell_rate is not None else (spot_d * Decimal("1.004"))

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO fx_rates (rate_date, base_currency, quote_currency, spot_rate, buy_rate, sell_rate)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rate_date, base_currency, quote_currency) DO UPDATE SET
                spot_rate = excluded.spot_rate,
                buy_rate = excluded.buy_rate,
                sell_rate = excluded.sell_rate
            """,
            (
                rate_date,
                base_currency.upper(),
                quote_currency.upper(),
                f"{spot_d:.6f}",
                f"{buy_d:.6f}",
                f"{sell_d:.6f}",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "rate_date": rate_date,
        "base_currency": base_currency.upper(),
        "quote_currency": quote_currency.upper(),
        "spot_rate": f"{spot_d:.6f}",
        "buy_rate": f"{buy_d:.6f}",
        "sell_rate": f"{sell_d:.6f}",
    }


def post_fx_conversion_contra(
    effective_date: str,
    from_account_code: str,
    to_account_code: str,
    from_amount_native: Decimal | str,
    execution_rate_to_usd: Decimal | str,
    narration: str = "Cross-Currency Treasury FX Conversion",
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """
    Converts funds from a foreign-currency Nostro account (e.g., EUR 1011) into USD Operating Bank (1010)
    or vice-versa, automatically booking Realized FX Gain (4200) or Loss (6200) vs. carrying book rate.
    """
    conn = get_connection(db_path)
    try:
        from_acc = conn.execute(
            """
            SELECT a.*, COALESCE(SUM(pl.native_amount_minor), 0) AS nat_bal,
                   COALESCE(SUM(pl.functional_amount_minor), 0) AS func_bal
            FROM accounts a
            LEFT JOIN posting_lines pl ON pl.account_id = a.account_id
            WHERE a.code = ?
            GROUP BY a.account_id
            """,
            (from_account_code,),
        ).fetchone()
        to_acc = conn.execute("SELECT * FROM accounts WHERE code = ?", (to_account_code,)).fetchone()
    finally:
        conn.close()

    if not from_acc or not to_acc:
        raise ValueError("Invalid source or destination account code for FX conversion.")

    amt_dec = Decimal(str(from_amount_native))
    exec_rate = Decimal(str(execution_rate_to_usd))

    # Weighted-average carrying book rate of the source Nostro account
    if from_acc["nat_bal"] > 0:
        carrying_rate = Decimal(from_acc["func_bal"]) / Decimal(from_acc["nat_bal"])
    else:
        carrying_rate = lookup_fx_rate(from_acc["currency_code"], effective_date, db_path=db_path)

    book_usd_value = (amt_dec * carrying_rate).quantize(Decimal("0.01"))
    realized_usd_value = (amt_dec * exec_rate).quantize(Decimal("0.01"))
    fx_delta = (realized_usd_value - book_usd_value).quantize(Decimal("0.01"))

    lines = [
        # Credit foreign Nostro at carrying book rate so its average cost basis stays mathematically clean
        PostingInput(
            account_code=from_account_code,
            credit=amt_dec,
            native_currency=from_acc["currency_code"],
            exchange_rate=f"{carrying_rate:.6f}",
            party_name="Treasury FX Desk",
        ),
        # Debit destination USD bank for exact USD cash received
        PostingInput(
            account_code=to_account_code,
            debit=realized_usd_value,
            native_currency=to_acc["currency_code"],
            exchange_rate="1.000000",
            party_name="Treasury FX Desk",
        ),
    ]

    if fx_delta > Decimal("0.00"):
        lines.append(
            PostingInput(
                account_code="4200",  # Realized FX Gain
                credit=fx_delta,
                native_currency="USD",
                exchange_rate="1.000000",
                party_name="Treasury FX Desk",
            )
        )
    elif fx_delta < Decimal("0.00"):
        lines.append(
            PostingInput(
                account_code="6200",  # Realized FX Loss
                debit=abs(fx_delta),
                native_currency="USD",
                exchange_rate="1.000000",
                party_name="Treasury FX Desk",
            )
        )

    vch = post_voucher(
        voucher_type="CONTRA_FX",
        effective_date=effective_date,
        narration=f"{narration}: {from_acc['currency_code']} {amt_dec:,.2f} -> {to_acc['currency_code']} {realized_usd_value:,.2f} @ {exec_rate:.6f} (Realized FX Delta: ${fx_delta:,.2f})",
        lines=lines,
        source_ref=f"FX-{from_acc['currency_code']}-{to_acc['currency_code']}",
        db_path=db_path,
    )
    return {
        "voucher": vch,
        "carrying_rate": float(carrying_rate),
        "execution_rate": float(exec_rate),
        "book_usd_value": float(book_usd_value),
        "realized_usd_value": float(realized_usd_value),
        "realized_fx_gain_loss": float(fx_delta),
    }


def run_ias21_revaluation(
    as_of_date: str,
    commit_voucher: bool = False,
    auto_reverse_next_day: bool = False,
    next_period_date: Optional[str] = None,
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """
    IAS 21 / Ind AS 21 Period-End FX Revaluation Engine:
      1. Filters all monetary accounts (is_monetary = 1) denominated in foreign currencies (!= USD).
      2. Compares carrying functional book value vs. closing-rate translated value (Native * R_close).
      3. Computes Unrealized FX Gain (4210) or Unrealized FX Loss (6210).
      4. Optionally commits an immutable REVALUATION voucher and a Day-1 REVERSAL voucher.
    """
    conn = get_connection(db_path)
    try:
        cfg = conn.execute("SELECT functional_currency FROM entity_config WHERE id = 1").fetchone()
        func_curr = cfg["functional_currency"] if cfg else "USD"

        rows = conn.execute(
            """
            SELECT
                a.account_id, a.code, a.name, a.currency_code, a.account_type,
                COALESCE(SUM(pl.native_amount_minor), 0) AS net_native_minor,
                COALESCE(SUM(pl.functional_amount_minor), 0) AS net_func_minor
            FROM accounts a
            LEFT JOIN posting_lines pl ON pl.account_id = a.account_id
            WHERE a.is_monetary = 1 AND a.currency_code != ?
            GROUP BY a.account_id
            HAVING net_native_minor != 0
            ORDER BY a.code ASC
            """,
            (func_curr,),
        ).fetchall()
    finally:
        conn.close()

    reval_items: List[Dict[str, Any]] = []
    posting_lines: List[PostingInput] = []
    total_unrealized_delta_minor = 0

    for r in rows:
        closing_rate = lookup_fx_rate(r["currency_code"], as_of_date, db_path=db_path, functional_currency=func_curr)
        native_dec = Decimal(r["net_native_minor"]) / Decimal("100")
        carrying_func_minor = r["net_func_minor"]
        new_func_minor = to_minor(native_dec * closing_rate)
        delta_minor = new_func_minor - carrying_func_minor
        total_unrealized_delta_minor += delta_minor

        reval_items.append(
            {
                "account_code": r["code"],
                "account_name": r["name"],
                "currency_code": r["currency_code"],
                "native_balance": from_minor(r["net_native_minor"]),
                "carrying_functional_value": from_minor(carrying_func_minor),
                "closing_spot_rate": float(closing_rate),
                "revalued_functional_value": from_minor(new_func_minor),
                "unrealized_fx_delta": from_minor(delta_minor),
            }
        )

        if delta_minor > 0:
            # Gain on Monetary Asset (or reduction of Monetary Liability): Debit Account (functional adj), Credit 4210
            amt = Decimal(delta_minor) / Decimal("100")
            posting_lines.append(
                PostingInput(
                    account_code=r["code"],
                    debit=amt,
                    native_currency=func_curr,  # Functional value adjustment without altering foreign native units
                    exchange_rate="1.000000",
                    party_name="IAS 21 Revaluation",
                )
            )
            posting_lines.append(
                PostingInput(
                    account_code="4210",
                    credit=amt,
                    native_currency=func_curr,
                    exchange_rate="1.000000",
                    party_name="IAS 21 Revaluation",
                )
            )
        elif delta_minor < 0:
            # Loss on Monetary Asset: Debit 6210, Credit Account (functional adj)
            amt = Decimal(abs(delta_minor)) / Decimal("100")
            posting_lines.append(
                PostingInput(
                    account_code="6210",
                    debit=amt,
                    native_currency=func_curr,
                    exchange_rate="1.000000",
                    party_name="IAS 21 Revaluation",
                )
            )
            posting_lines.append(
                PostingInput(
                    account_code=r["code"],
                    credit=amt,
                    native_currency=func_curr,
                    exchange_rate="1.000000",
                    party_name="IAS 21 Revaluation",
                )
            )

    posted_voucher = None
    reversal_voucher = None
    if commit_voucher and posting_lines:
        # Note: For pure IAS 21 functional adjustment without distorting foreign native_amount_minor,
        # we insert directly with native_amount_minor=0 for the foreign account legs so native units stay exact!
        posted_voucher = _commit_ias21_voucher(
            as_of_date=as_of_date,
            reval_items=reval_items,
            func_curr=func_curr,
            db_path=db_path,
        )
        if auto_reverse_next_day and posted_voucher:
            rev_date = next_period_date or as_of_date
            reversal_voucher = reverse_voucher(
                posted_voucher["voucher_id"],
                reversal_date=rev_date,
                reason="IAS 21 Day-1 Auto-Reversal",
                db_path=db_path,
            )

    return {
        "as_of_date": as_of_date,
        "functional_currency": func_curr,
        "monetary_accounts_evaluated": len(reval_items),
        "total_unrealized_fx_gain_loss": from_minor(total_unrealized_delta_minor),
        "items": reval_items,
        "committed_voucher": posted_voucher,
        "day1_reversal_voucher": reversal_voucher,
    }


def _commit_ias21_voucher(
    as_of_date: str,
    reval_items: List[Dict[str, Any]],
    func_curr: str,
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Commits an IAS 21 functional-currency-only adjustment voucher so foreign native units remain untouched."""
    import uuid
    from datetime import datetime, timezone

    conn = get_connection(db_path)
    try:
        acc_rows = conn.execute("SELECT account_id, code, name, currency_code FROM accounts").fetchall()
        acc_by_code = {r["code"]: dict(r) for r in acc_rows}

        seq = conn.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0] + 1
        voucher_id = f"VCH-{uuid.uuid4().hex[:8].upper()}"
        voucher_number = f"VCH-2026-{seq:04d}"
        created_at = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO vouchers
            (voucher_id, voucher_number, voucher_type, effective_date, narration, source_ref, status, created_at)
            VALUES (?, ?, 'REVALUATION', ?, ?, ?, 'POSTED', ?)
            """,
            (
                voucher_id,
                voucher_number,
                as_of_date,
                f"IAS 21 Period-End FX Revaluation of Monetary Foreign Accounts as of {as_of_date}",
                f"IAS21-{as_of_date}",
                created_at,
            ),
        )

        lines_inserted = 0
        for item in reval_items:
            delta_minor = to_minor(item["unrealized_fx_delta"])
            if delta_minor == 0:
                continue
            acc = acc_by_code[item["account_code"]]
            gain_acc = acc_by_code["4210"]
            loss_acc = acc_by_code["6210"]

            # Foreign monetary account leg: native_amount_minor = 0 (units unchanged), functional_amount_minor = delta
            conn.execute(
                """
                INSERT INTO posting_lines
                (line_id, voucher_id, account_id, native_amount_minor, native_currency,
                 functional_amount_minor, functional_currency, exchange_rate, bill_ref, party_name)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, NULL, 'IAS 21 Revaluation')
                """,
                (
                    f"LN-{uuid.uuid4().hex[:10].upper()}",
                    voucher_id,
                    acc["account_id"],
                    item["currency_code"],
                    delta_minor,
                    func_curr,
                    f"{item['closing_spot_rate']:.6f}",
                ),
            )
            lines_inserted += 1

            # Offset leg to Unrealized FX Gain (4210) or Loss (6210)
            offset_acc = gain_acc if delta_minor > 0 else loss_acc
            conn.execute(
                """
                INSERT INTO posting_lines
                (line_id, voucher_id, account_id, native_amount_minor, native_currency,
                 functional_amount_minor, functional_currency, exchange_rate, bill_ref, party_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, '1.000000', NULL, 'IAS 21 Revaluation')
                """,
                (
                    f"LN-{uuid.uuid4().hex[:10].upper()}",
                    voucher_id,
                    offset_acc["account_id"],
                    -delta_minor,
                    func_curr,
                    -delta_minor,
                    func_curr,
                ),
            )
            lines_inserted += 1

        conn.commit()
        return {
            "voucher_id": voucher_id,
            "voucher_number": voucher_number,
            "voucher_type": "REVALUATION",
            "effective_date": as_of_date,
            "lines_count": lines_inserted,
        }
    finally:
        conn.close()
