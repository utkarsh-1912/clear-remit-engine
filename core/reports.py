"""Real-Time Financial Statements Engine: Trial Balance, Profit & Loss, Balance Sheet, and Nostro Exposure."""

from __future__ import annotations
import pathlib
from typing import Dict, Any, List, Optional
from core.database import get_connection
from core.ledger import from_minor


def generate_financial_statements(db_path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """
    Computes live, real-time Trial Balance, Income Statement (P&L), Balance Sheet, and
    Multi-Currency Nostro Cash Exposure directly from immutable posting lines.
    """
    conn = get_connection(db_path)
    try:
        cfg = conn.execute("SELECT * FROM entity_config WHERE id = 1").fetchone()
        func_curr = cfg["functional_currency"] if cfg else "USD"

        rows = conn.execute(
            """
            SELECT
                a.account_id,
                a.code,
                a.name,
                a.account_type,
                a.parent_group,
                a.currency_code,
                a.is_monetary,
                COALESCE(SUM(pl.native_amount_minor), 0) AS net_native_minor,
                COALESCE(SUM(pl.functional_amount_minor), 0) AS net_func_minor
            FROM accounts a
            LEFT JOIN posting_lines pl ON pl.account_id = a.account_id
            GROUP BY a.account_id
            ORDER BY a.code ASC
            """
        ).fetchall()
    finally:
        conn.close()

    trial_balance: List[Dict[str, Any]] = []
    tb_total_dr_minor = 0
    tb_total_cr_minor = 0

    revenues: List[Dict[str, Any]] = []
    expenses: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []
    liabilities: List[Dict[str, Any]] = []
    equity: List[Dict[str, Any]] = []
    nostro_positions: List[Dict[str, Any]] = []

    total_rev_minor = 0
    total_exp_minor = 0
    total_assets_minor = 0
    total_liab_minor = 0
    total_eq_minor = 0

    for r in rows:
        net_func = r["net_func_minor"]
        net_nat = r["net_native_minor"]
        if net_func == 0 and net_nat == 0:
            continue

        dr_minor = net_func if net_func > 0 else 0
        cr_minor = -net_func if net_func < 0 else 0
        tb_total_dr_minor += dr_minor
        tb_total_cr_minor += cr_minor

        entry = {
            "code": r["code"],
            "name": r["name"],
            "account_type": r["account_type"],
            "parent_group": r["parent_group"],
            "currency_code": r["currency_code"],
            "is_monetary": bool(r["is_monetary"]),
            "native_balance": from_minor(net_nat),
            "functional_debit": from_minor(dr_minor),
            "functional_credit": from_minor(cr_minor),
            "net_functional_signed": from_minor(net_func),
        }
        trial_balance.append(entry)

        atype = r["account_type"]
        if atype == "REVENUE":
            # Revenue has a normal Credit (negative) balance -> display positive
            rev_val = -net_func
            total_rev_minor += rev_val
            revenues.append({**entry, "display_amount": from_minor(rev_val)})
        elif atype == "EXPENSE":
            # Expense has a normal Debit (positive) balance
            total_exp_minor += net_func
            expenses.append({**entry, "display_amount": from_minor(net_func)})
        elif atype == "ASSET":
            total_assets_minor += net_func
            assets.append({**entry, "display_amount": from_minor(net_func)})
            if "Bank" in r["parent_group"] or "Cash" in r["parent_group"]:
                nostro_positions.append(
                    {
                        "code": r["code"],
                        "name": r["name"],
                        "currency_code": r["currency_code"],
                        "native_balance": from_minor(net_nat),
                        "functional_usd_value": from_minor(net_func),
                    }
                )
        elif atype == "LIABILITY":
            # Liability has normal Credit (negative) balance
            liab_val = -net_func
            total_liab_minor += liab_val
            liabilities.append({**entry, "display_amount": from_minor(liab_val)})
        elif atype == "EQUITY":
            eq_val = -net_func
            total_eq_minor += eq_val
            equity.append({**entry, "display_amount": from_minor(eq_val)})

    net_profit_minor = total_rev_minor - total_exp_minor
    total_liab_and_equity_minor = total_liab_minor + total_eq_minor + net_profit_minor

    return {
        "entity_name": cfg["entity_name"] if cfg else "ClearLedger Global Operations LLC",
        "functional_currency": func_curr,
        "trial_balance": {
            "rows": trial_balance,
            "total_debits": from_minor(tb_total_dr_minor),
            "total_credits": from_minor(tb_total_cr_minor),
            "is_balanced": tb_total_dr_minor == tb_total_cr_minor,
        },
        "profit_and_loss": {
            "revenues": revenues,
            "expenses": expenses,
            "total_revenue": from_minor(total_rev_minor),
            "total_expense": from_minor(total_exp_minor),
            "net_profit": from_minor(net_profit_minor),
        },
        "balance_sheet": {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "current_period_net_profit": from_minor(net_profit_minor),
            "total_assets": from_minor(total_assets_minor),
            "total_liabilities": from_minor(total_liab_minor),
            "total_equity_including_profit": from_minor(total_eq_minor + net_profit_minor),
            "total_liabilities_and_equity": from_minor(total_liab_and_equity_minor),
            "is_balanced": total_assets_minor == total_liab_and_equity_minor,
        },
        "nostro_positions": nostro_positions,
    }
