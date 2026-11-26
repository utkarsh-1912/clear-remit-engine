"""SQLite Persistence Layer & Default Chart of Accounts for ClearLedger Prime (Tally + Finacle EGL)."""

from __future__ import annotations
import pathlib
import sqlite3
from datetime import datetime, timezone
from typing import Optional

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "clearledger.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entity_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    entity_name TEXT NOT NULL,
    functional_currency TEXT NOT NULL DEFAULT 'USD',
    fiscal_year_start TEXT NOT NULL DEFAULT '2026-04-01'
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')),
    parent_group TEXT NOT NULL,
    currency_code TEXT NOT NULL DEFAULT 'USD',
    is_monetary INTEGER NOT NULL DEFAULT 1,
    enable_bill_by_bill INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vouchers (
    voucher_id TEXT PRIMARY KEY,
    voucher_number TEXT UNIQUE NOT NULL,
    voucher_type TEXT NOT NULL CHECK (
        voucher_type IN (
            'RECEIPT', 'PAYMENT', 'JOURNAL', 'CONTRA_FX',
            'SALES', 'PURCHASE', 'TRADE_SETTLEMENT', 'REVALUATION', 'REVERSAL'
        )
    ),
    effective_date TEXT NOT NULL,
    narration TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED', 'REVERSED')),
    reversed_by_voucher_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posting_lines (
    line_id TEXT PRIMARY KEY,
    voucher_id TEXT NOT NULL REFERENCES vouchers(voucher_id),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    native_amount_minor INTEGER NOT NULL,
    native_currency TEXT NOT NULL,
    functional_amount_minor INTEGER NOT NULL,
    functional_currency TEXT NOT NULL,
    exchange_rate TEXT NOT NULL,
    bill_ref TEXT,
    party_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_posting_voucher ON posting_lines(voucher_id);
CREATE INDEX IF NOT EXISTS idx_posting_account ON posting_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_posting_bill ON posting_lines(bill_ref);
CREATE INDEX IF NOT EXISTS idx_posting_acc_vch ON posting_lines(account_id, voucher_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_date_created ON vouchers(effective_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vouchers_type_status ON vouchers(voucher_type, status);
CREATE INDEX IF NOT EXISTS idx_vouchers_source_ref ON vouchers(source_ref);

CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    spot_rate TEXT NOT NULL,
    buy_rate TEXT NOT NULL,
    sell_rate TEXT NOT NULL,
    PRIMARY KEY (rate_date, base_currency, quote_currency)
);

CREATE TABLE IF NOT EXISTS investment_lots (
    lot_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    quantity_initial TEXT NOT NULL,
    quantity_remaining TEXT NOT NULL,
    unit_cost_minor INTEGER NOT NULL,
    total_cost_basis_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    broker_ref TEXT NOT NULL,
    voucher_id TEXT NOT NULL REFERENCES vouchers(voucher_id)
);

CREATE TABLE IF NOT EXISTS realized_capital_gains (
    gain_id TEXT PRIMARY KEY,
    sale_date TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    quantity_sold TEXT NOT NULL,
    holding_days INTEGER NOT NULL,
    term_type TEXT NOT NULL CHECK (term_type IN ('STCG', 'LTCG')),
    proceeds_minor INTEGER NOT NULL,
    cost_basis_minor INTEGER NOT NULL,
    charges_minor INTEGER NOT NULL,
    realized_gain_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    broker_ref TEXT NOT NULL,
    lot_id TEXT NOT NULL REFERENCES investment_lots(lot_id),
    voucher_id TEXT NOT NULL REFERENCES vouchers(voucher_id)
);
"""

# Default Chart of Accounts blending Tally Prime Groups + Finacle EGL Nostro/FX + Investment Tax Accounts
DEFAULT_ACCOUNTS = [
    # ASSETS
    ("ACC-1010", "1010", "Operating Bank Cash (USD)", "ASSET", "Current Assets > Bank Accounts", "USD", 1, 0),
    ("ACC-1011", "1011", "Nostro Bank Account (EUR)", "ASSET", "Current Assets > Nostro / Foreign Banks", "EUR", 1, 0),
    ("ACC-1012", "1012", "Nostro Bank Account (INR)", "ASSET", "Current Assets > Nostro / Foreign Banks", "INR", 1, 0),
    ("ACC-1013", "1013", "Nostro Bank Account (GBP)", "ASSET", "Current Assets > Nostro / Foreign Banks", "GBP", 1, 0),
    ("ACC-1014", "1014", "Nostro Bank Account (AED)", "ASSET", "Current Assets > Nostro / Foreign Banks", "AED", 1, 0),
    ("ACC-1020", "1020", "Brokerage Settlement Cash (USD)", "ASSET", "Current Assets > Cash & Equivalents", "USD", 1, 0),
    ("ACC-1150", "1150", "Prepaid Tax / TDS & FTC Receivable", "ASSET", "Current Assets > Statutory Receivables", "USD", 1, 0),
    ("ACC-1200", "1200", "Accounts Receivable - Trade (USD)", "ASSET", "Current Assets > Sundry Debtors", "USD", 1, 1),
    ("ACC-1201", "1201", "Accounts Receivable - Export (EUR)", "ASSET", "Current Assets > Sundry Debtors", "EUR", 1, 1),
    ("ACC-1290", "1290", "AR Short-Pay Dispute Suspense", "ASSET", "Current Assets > Sundry Debtors", "USD", 1, 1),
    ("ACC-1400", "1400", "Investment Portfolio - Equities & ETFs (At Cost)", "ASSET", "Investments > Marketable Securities", "USD", 0, 0),
    ("ACC-1410", "1410", "Investment Portfolio - Bonds & Fixed Income", "ASSET", "Investments > Fixed Income", "USD", 0, 0),
    ("ACC-1900", "1900", "FX Position & Currency Clearing", "ASSET", "Current Assets > Treasury Clearing", "USD", 0, 0),
    # LIABILITIES
    ("ACC-2000", "2000", "Accounts Payable - Trade", "LIABILITY", "Current Liabilities > Sundry Creditors", "USD", 1, 1),
    ("ACC-2140", "2140", "Customer Credit Memos Liability", "LIABILITY", "Current Liabilities > Customer Credits", "USD", 1, 0),
    ("ACC-2190", "2190", "Unapplied Customer Overpayment", "LIABILITY", "Current Liabilities > Suspense", "USD", 1, 0),
    ("ACC-2199", "2199", "Unreconciled AR Suspense Clearing", "LIABILITY", "Current Liabilities > Suspense", "USD", 1, 0),
    ("ACC-2200", "2200", "Statutory Tax / TDS Payable", "LIABILITY", "Current Liabilities > Duties & Taxes", "USD", 1, 0),
    # EQUITY
    ("ACC-3000", "3000", "Owner Capital / Share Capital", "EQUITY", "Capital Account", "USD", 0, 0),
    ("ACC-3100", "3100", "Retained Earnings", "EQUITY", "Reserves & Surplus", "USD", 0, 0),
    # REVENUE
    ("ACC-4000", "4000", "B2B Trade & Export Revenue", "REVENUE", "Direct Income", "USD", 0, 0),
    ("ACC-4090", "4090", "Sales Early-Pay Discounts (Contra-Rev)", "EXPENSE", "Direct Expenses > Discounts", "USD", 0, 0),
    ("ACC-4200", "4200", "Realized FX Gain", "REVENUE", "Indirect Income > Treasury FX", "USD", 0, 0),
    ("ACC-4210", "4210", "Unrealized FX Revaluation Gain (IAS 21)", "REVENUE", "Indirect Income > Treasury FX", "USD", 0, 0),
    ("ACC-4300", "4300", "Realized Capital Gain - STCG", "REVENUE", "Indirect Income > Investment Gains", "USD", 0, 0),
    ("ACC-4310", "4310", "Realized Capital Gain - LTCG", "REVENUE", "Indirect Income > Investment Gains", "USD", 0, 0),
    ("ACC-4320", "4320", "Dividend & Interest Income", "REVENUE", "Indirect Income > Investment Gains", "USD", 0, 0),
    # EXPENSES
    ("ACC-6120", "6120", "Bank & SWIFT Wire Charges", "EXPENSE", "Indirect Expenses > Banking", "USD", 0, 0),
    ("ACC-6200", "6200", "Realized FX Loss", "EXPENSE", "Indirect Expenses > Treasury FX", "USD", 0, 0),
    ("ACC-6210", "6210", "Unrealized FX Revaluation Loss (IAS 21)", "EXPENSE", "Indirect Expenses > Treasury FX", "USD", 0, 0),
    ("ACC-6300", "6300", "Realized Capital Loss - STCG/LTCG", "EXPENSE", "Indirect Expenses > Investment Losses", "USD", 0, 0),
    ("ACC-6310", "6310", "Brokerage, STT & Statutory Charges", "EXPENSE", "Indirect Expenses > Investment Charges", "USD", 0, 0),
    ("ACC-6999", "6999", "FX Rounding Differences", "EXPENSE", "Indirect Expenses > Adjustments", "USD", 0, 0),
]

# Initial FX Spot Rates (Foreign Currency -> USD Functional Currency)
DEFAULT_FX_RATES = [
    ("2026-10-01", "USD", "USD", "1.000000", "1.000000", "1.000000"),
    ("2026-10-01", "EUR", "USD", "1.080000", "1.076000", "1.084000"),
    ("2026-10-01", "GBP", "USD", "1.270000", "1.265000", "1.275000"),
    ("2026-10-01", "INR", "USD", "0.011905", "0.011850", "0.011960"),  # ~84.00 INR/USD
    ("2026-10-01", "AED", "USD", "0.272294", "0.271800", "0.272800"),
    ("2026-11-10", "USD", "USD", "1.000000", "1.000000", "1.000000"),
    ("2026-11-10", "EUR", "USD", "1.105000", "1.101000", "1.109000"),  # EUR strengthened vs Oct
    ("2026-11-10", "GBP", "USD", "1.292000", "1.287000", "1.297000"),  # GBP strengthened vs Oct
    ("2026-11-10", "INR", "USD", "0.011765", "0.011710", "0.011820"),  # ~85.00 INR/USD
    ("2026-11-10", "AED", "USD", "0.272294", "0.271800", "0.272800"),
]


def get_connection(db_path: Optional[pathlib.Path] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # High-throughput SQLite tuning for GB-scale ingestion & sub-10ms concurrent reads
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -64000;")       # 64 MB page cache
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 268435456;")     # 256 MB memory-mapped I/O
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_database(db_path: Optional[pathlib.Path] = None, seed_demo: bool = False) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT OR IGNORE INTO entity_config (id, entity_name, functional_currency, fiscal_year_start)
            VALUES (1, 'ClearLedger Global Operations LLC', 'USD', '2026-04-01')
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO accounts
            (account_id, code, name, account_type, parent_group, currency_code, is_monetary, enable_bill_by_bill)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            DEFAULT_ACCOUNTS,
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO fx_rates
            (rate_date, base_currency, quote_currency, spot_rate, buy_rate, sell_rate)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            DEFAULT_FX_RATES,
        )
        conn.commit()
    finally:
        conn.close()

    if seed_demo:
        _seed_initial_opening_balances(db_path)


def _seed_initial_opening_balances(db_path: Optional[pathlib.Path] = None) -> None:
    """Seeds realistic opening capital, multi-currency Nostro balances, and open AR balances if DB is empty."""
    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]
        if count > 0:
            return
    finally:
        conn.close()

    # Import lazily to avoid circular import
    from core.ledger import post_voucher, PostingInput

    # 1. Opening Capital & Multi-Currency Nostro Bank Balances (2026-10-01)
    # USD Bank: $150,000 | EUR Nostro: EUR 50,000 (@ 1.08 = $54,000) | INR Nostro: INR 4,200,000 (@ 0.011905 = $50,001)
    # Brokerage Cash: $100,000 | Total Opening Equity = $354,001.00
    post_voucher(
        voucher_type="JOURNAL",
        effective_date="2026-10-01",
        narration="Opening Capital Injection & Multi-Currency Nostro Funding (USD, EUR, INR, Brokerage)",
        source_ref="OPENING-FY26",
        lines=[
            PostingInput(account_code="1010", debit="150000.00", native_currency="USD", exchange_rate="1.000000"),
            PostingInput(account_code="1011", debit="50000.00", native_currency="EUR", exchange_rate="1.080000"),
            PostingInput(account_code="1012", debit="4200000.00", native_currency="INR", exchange_rate="0.011905"),
            PostingInput(account_code="1020", debit="100000.00", native_currency="USD", exchange_rate="1.000000"),
            PostingInput(account_code="3000", credit="354001.00", native_currency="USD", exchange_rate="1.000000"),
        ],
        db_path=db_path,
    )

    # 2. Book Open AR Export Invoice in EUR (EUR 20,000 @ 1.08 = $21,600) to demonstrate IAS 21 FX Revaluation
    post_voucher(
        voucher_type="SALES",
        effective_date="2026-10-01",
        narration="Export SaaS & Consulting Invoice INV-EUR-901 to EuroTech GmbH (EUR 20,000 @ 1.08)",
        source_ref="INV-EUR-901",
        lines=[
            PostingInput(
                account_code="1201",
                debit="20000.00",
                native_currency="EUR",
                exchange_rate="1.080000",
                bill_ref="INV-EUR-901",
                party_name="EuroTech GmbH",
            ),
            PostingInput(
                account_code="4000",
                credit="21600.00",
                native_currency="USD",
                exchange_rate="1.000000",
                bill_ref="INV-EUR-901",
                party_name="EuroTech GmbH",
            ),
        ],
        db_path=db_path,
    )

    # 3. Book USD Open AR Invoices matching our ClearRemit Benchmark ($112,200 total across customers)
    post_voucher(
        voucher_type="SALES",
        effective_date="2026-10-25",
        narration="B2B Trade Sales Batch — Open AR Invoices (INV-2026-001 through INV-2026-013)",
        source_ref="AR-BATCH-OCT26",
        lines=[
            PostingInput(account_code="1200", debit="112200.00", native_currency="USD", exchange_rate="1.000000", bill_ref="AR-BATCH-OCT26"),
            PostingInput(account_code="4000", credit="112200.00", native_currency="USD", exchange_rate="1.000000"),
        ],
        db_path=db_path,
    )

    # 4. Book Approved Credit Memo Liability CM-501 ($800) for MedCore Hospital Supply
    post_voucher(
        voucher_type="JOURNAL",
        effective_date="2026-10-28",
        narration="Approved Q3 Volume Rebate Credit Memo CM-501 for MedCore Hospital Supply LLC",
        source_ref="CM-501",
        lines=[
            PostingInput(account_code="4090", debit="800.00", native_currency="USD", exchange_rate="1.000000", party_name="MedCore Hospital Supply LLC"),
            PostingInput(account_code="2140", credit="800.00", native_currency="USD", exchange_rate="1.000000", bill_ref="CM-501", party_name="MedCore Hospital Supply LLC"),
        ],
        db_path=db_path,
    )
