"""Post-Trade Investment & Capital Gains Tax-Lot Accounting Engine (Strictly Post-Settlement Statutory Accounting)."""

from __future__ import annotations
import csv
import io
import pathlib
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN
from typing import List, Dict, Any, Optional
from core.database import get_connection
from core.ledger import PostingInput, post_voucher, to_minor, from_minor


def _parse_date(d_str: str) -> datetime:
    return datetime.strptime(d_str.strip(), "%Y-%m-%d")


def _asset_account_for_class(asset_class: str) -> str:
    if asset_class.upper() in ("BOND", "FIXED_INCOME", "TBILL"):
        return "1410"
    return "1400"


def ingest_broker_trades_csv(
    csv_content: str,
    db_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """
    Ingests post-settlement broker contract notes / trade history CSV purely for
    FIFO Tax-Lot Capital Gains Accounting (STCG/LTCG) and Statutory General Ledger posting.
    Zero live execution, zero OMS/EMS/FIX routing.
    """
    reader = csv.DictReader(io.StringIO(csv_content.strip()))
    trades_processed = 0
    vouchers_created: List[str] = []
    gains_recorded = 0

    for row in reader:
        action = (row.get("action") or "").strip().upper()
        trade_date = (row.get("trade_date") or "2026-11-10").strip()
        symbol = (row.get("symbol") or "").strip().upper()
        asset_class = (row.get("asset_class") or "EQUITY").strip().upper()
        qty = Decimal(str(row.get("quantity") or "0").strip())
        unit_price = Decimal(str(row.get("unit_price") or "0").strip())
        charges = Decimal(str(row.get("brokerage_charges") or "0").strip())
        currency = (row.get("currency") or "USD").strip().upper()
        broker_ref = (row.get("broker_ref") or f"CN-{uuid.uuid4().hex[:6].upper()}").strip()

        # Skip if this exact broker contract note was already posted (idempotency guard)
        conn = get_connection(db_path)
        try:
            exists = conn.execute(
                "SELECT 1 FROM vouchers WHERE source_ref = ? AND status = 'POSTED'",
                (broker_ref,),
            ).fetchone()
        finally:
            conn.close()
        if exists:
            continue

        asset_acc = _asset_account_for_class(asset_class)

        if action == "BUY":
            gross_value = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            # Capitalize brokerage & statutory acquisition charges into cost basis per IFRS/GAAP/IT Act
            total_cost_basis = (gross_value + charges).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            unit_cost_minor = to_minor((total_cost_basis / qty) if qty > 0 else Decimal("0"))
            total_cost_minor = to_minor(total_cost_basis)

            vch = post_voucher(
                voucher_type="TRADE_SETTLEMENT",
                effective_date=trade_date,
                narration=f"Post-Trade BUY Settlement: {qty} {symbol} @ ${unit_price:,.2f} + ${charges:,.2f} charges (Ref: {broker_ref})",
                source_ref=broker_ref,
                lines=[
                    PostingInput(account_code=asset_acc, debit=total_cost_basis, native_currency=currency, party_name=symbol),
                    PostingInput(account_code="1020", credit=total_cost_basis, native_currency=currency, party_name=symbol),
                ],
                db_path=db_path,
            )
            vouchers_created.append(vch["voucher_number"])

            lot_id = f"LOT-{uuid.uuid4().hex[:8].upper()}"
            conn = get_connection(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO investment_lots
                    (lot_id, symbol, asset_class, acquisition_date, quantity_initial, quantity_remaining,
                     unit_cost_minor, total_cost_basis_minor, currency, broker_ref, voucher_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lot_id,
                        symbol,
                        asset_class,
                        trade_date,
                        str(qty),
                        str(qty),
                        unit_cost_minor,
                        total_cost_minor,
                        currency,
                        broker_ref,
                        vch["voucher_id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            trades_processed += 1

        elif action == "SELL":
            gross_proceeds = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            net_cash_received = (gross_proceeds - charges).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

            # FIFO Lot Depletion
            conn = get_connection(db_path)
            try:
                open_lots = conn.execute(
                    """
                    SELECT * FROM investment_lots
                    WHERE symbol = ? AND CAST(quantity_remaining AS REAL) > 0
                    ORDER BY acquisition_date ASC, rowid ASC
                    """,
                    (symbol,),
                ).fetchall()
            finally:
                conn.close()

            qty_to_sell = qty
            consumed_lots = []
            total_fifo_cost_minor = 0

            for lot in open_lots:
                if qty_to_sell <= 0:
                    break
                lot_rem = Decimal(lot["quantity_remaining"])
                take_qty = min(lot_rem, qty_to_sell)
                ratio = take_qty / Decimal(lot["quantity_initial"])
                lot_cost_minor = int(
                    (Decimal(lot["total_cost_basis_minor"]) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
                )
                holding_days = (_parse_date(trade_date) - _parse_date(lot["acquisition_date"])).days
                term_type = "LTCG" if holding_days > 365 else "STCG"

                consumed_lots.append(
                    {
                        "lot_id": lot["lot_id"],
                        "acquisition_date": lot["acquisition_date"],
                        "take_qty": take_qty,
                        "new_rem": lot_rem - take_qty,
                        "cost_minor": lot_cost_minor,
                        "holding_days": holding_days,
                        "term_type": term_type,
                    }
                )
                total_fifo_cost_minor += lot_cost_minor
                qty_to_sell -= take_qty

            if qty_to_sell > 0:
                raise ValueError(f"Insufficient open FIFO tax-lots for {symbol} sale of {qty} units.")

            # Build balanced GL Voucher for Sale Settlement
            fifo_cost_dec = Decimal(total_fifo_cost_minor) / Decimal("100")
            # Allocate proceeds and charges proportionally per consumed lot to split STCG vs LTCG accurately
            stcg_gain_dec = Decimal("0.00")
            ltcg_gain_dec = Decimal("0.00")
            cap_loss_dec = Decimal("0.00")

            lot_gain_records = []
            for cl in consumed_lots:
                share = cl["take_qty"] / qty
                lot_proceeds_minor = to_minor(gross_proceeds * share)
                lot_charges_minor = to_minor(charges * share)
                lot_gain_minor = lot_proceeds_minor - lot_charges_minor - cl["cost_minor"]
                gain_dec = Decimal(lot_gain_minor) / Decimal("100")

                if gain_dec >= 0:
                    if cl["term_type"] == "LTCG":
                        ltcg_gain_dec += gain_dec
                    else:
                        stcg_gain_dec += gain_dec
                else:
                    cap_loss_dec += abs(gain_dec)

                lot_gain_records.append(
                    {
                        **cl,
                        "proceeds_minor": lot_proceeds_minor,
                        "charges_minor": lot_charges_minor,
                        "gain_minor": lot_gain_minor,
                    }
                )

            posting_lines = [
                PostingInput(account_code="1020", debit=net_cash_received, native_currency=currency, party_name=symbol),
                PostingInput(account_code=asset_acc, credit=fifo_cost_dec, native_currency=currency, party_name=symbol),
            ]
            if charges > 0:
                # Net cash already deducted charges; show gross gain/loss net of charges cleanly
                pass
            if stcg_gain_dec > 0:
                posting_lines.append(
                    PostingInput(account_code="4300", credit=stcg_gain_dec, native_currency=currency, party_name=symbol)
                )
            if ltcg_gain_dec > 0:
                posting_lines.append(
                    PostingInput(account_code="4310", credit=ltcg_gain_dec, native_currency=currency, party_name=symbol)
                )
            if cap_loss_dec > 0:
                posting_lines.append(
                    PostingInput(account_code="6300", debit=cap_loss_dec, native_currency=currency, party_name=symbol)
                )

            vch = post_voucher(
                voucher_type="TRADE_SETTLEMENT",
                effective_date=trade_date,
                narration=f"Post-Trade SELL Settlement (FIFO): {qty} {symbol} @ ${unit_price:,.2f} (Proceeds: ${net_cash_received:,.2f}, FIFO Cost: ${fifo_cost_dec:,.2f})",
                source_ref=broker_ref,
                lines=posting_lines,
                db_path=db_path,
            )
            vouchers_created.append(vch["voucher_number"])

            conn = get_connection(db_path)
            try:
                for rec in lot_gain_records:
                    conn.execute(
                        "UPDATE investment_lots SET quantity_remaining = ? WHERE lot_id = ?",
                        (str(rec["new_rem"]), rec["lot_id"]),
                    )
                    conn.execute(
                        """
                        INSERT INTO realized_capital_gains
                        (gain_id, sale_date, acquisition_date, symbol, asset_class, quantity_sold,
                         holding_days, term_type, proceeds_minor, cost_basis_minor, charges_minor,
                         realized_gain_minor, currency, broker_ref, lot_id, voucher_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"CG-{uuid.uuid4().hex[:8].upper()}",
                            trade_date,
                            rec["acquisition_date"],
                            symbol,
                            asset_class,
                            str(rec["take_qty"]),
                            rec["holding_days"],
                            rec["term_type"],
                            rec["proceeds_minor"],
                            rec["cost_minor"],
                            rec["charges_minor"],
                            rec["gain_minor"],
                            currency,
                            broker_ref,
                            rec["lot_id"],
                            vch["voucher_id"],
                        ),
                    )
                    gains_recorded += 1
                conn.commit()
            finally:
                conn.close()
            trades_processed += 1

        elif action == "DIVIDEND":
            div_amt = (qty * unit_price - charges).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            vch = post_voucher(
                voucher_type="RECEIPT",
                effective_date=trade_date,
                narration=f"Dividend Receipt from {symbol} (Ref: {broker_ref})",
                source_ref=broker_ref,
                lines=[
                    PostingInput(account_code="1020", debit=div_amt, native_currency=currency, party_name=symbol),
                    PostingInput(account_code="4320", credit=div_amt, native_currency=currency, party_name=symbol),
                ],
                db_path=db_path,
            )
            vouchers_created.append(vch["voucher_number"])
            trades_processed += 1

    return {
        "trades_processed": trades_processed,
        "vouchers_created": vouchers_created,
        "capital_gain_events_recorded": gains_recorded,
    }


def get_investment_tax_summary(db_path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """Returns open FIFO tax lots and the statutory Realized Capital Gains (STCG vs LTCG) schedule."""
    conn = get_connection(db_path)
    try:
        lot_rows = conn.execute(
            "SELECT * FROM investment_lots ORDER BY symbol ASC, acquisition_date ASC"
        ).fetchall()
        cg_rows = conn.execute(
            "SELECT * FROM realized_capital_gains ORDER BY sale_date DESC, rowid DESC"
        ).fetchall()
    finally:
        conn.close()

    open_lots = []
    total_open_cost_minor = 0
    for l in lot_rows:
        rem = Decimal(l["quantity_remaining"])
        init = Decimal(l["quantity_initial"])
        rem_cost_minor = int(
            (Decimal(l["total_cost_basis_minor"]) * (rem / init)).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
        ) if init > 0 else 0
        if rem > 0:
            total_open_cost_minor += rem_cost_minor
        open_lots.append(
            {
                "lot_id": l["lot_id"],
                "symbol": l["symbol"],
                "asset_class": l["asset_class"],
                "acquisition_date": l["acquisition_date"],
                "quantity_initial": float(init),
                "quantity_remaining": float(rem),
                "unit_cost": from_minor(l["unit_cost_minor"]),
                "remaining_cost_basis": from_minor(rem_cost_minor),
                "currency": l["currency"],
                "broker_ref": l["broker_ref"],
            }
        )

    realized_schedule = []
    total_stcg_minor = 0
    total_ltcg_minor = 0
    for c in cg_rows:
        g = c["realized_gain_minor"]
        if c["term_type"] == "LTCG":
            total_ltcg_minor += g
        else:
            total_stcg_minor += g
        realized_schedule.append(
            {
                "gain_id": c["gain_id"],
                "sale_date": c["sale_date"],
                "acquisition_date": c["acquisition_date"],
                "symbol": c["symbol"],
                "asset_class": c["asset_class"],
                "quantity_sold": float(Decimal(c["quantity_sold"])),
                "holding_days": c["holding_days"],
                "term_type": c["term_type"],
                "proceeds": from_minor(c["proceeds_minor"]),
                "cost_basis": from_minor(c["cost_basis_minor"]),
                "charges": from_minor(c["charges_minor"]),
                "realized_gain": from_minor(g),
                "broker_ref": c["broker_ref"],
            }
        )

    return {
        "summary": {
            "open_lots_count": sum(1 for x in open_lots if x["quantity_remaining"] > 0),
            "total_open_cost_basis": from_minor(total_open_cost_minor),
            "total_realized_stcg": from_minor(total_stcg_minor),
            "total_realized_ltcg": from_minor(total_ltcg_minor),
            "total_realized_capital_gains": from_minor(total_stcg_minor + total_ltcg_minor),
        },
        "open_lots": open_lots,
        "realized_schedule": realized_schedule,
    }
