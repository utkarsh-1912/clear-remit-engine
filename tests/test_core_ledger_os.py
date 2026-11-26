"""End-to-End Accounting Invariant Tests for ClearLedger Prime (Core GL, FX IAS 21, Remittance, & Investment Tax-Lots)."""

import pathlib
import tempfile
import unittest
from decimal import Decimal

from core.database import init_database
from core.auth import init_auth_tables, register_user, authenticate_user, get_session_user, revoke_session
from core.ledger import PostingInput, post_voucher, reverse_voucher
from core.reports import generate_financial_statements
from core.coa_manager import create_gl_account, get_account_ledger_statement
from core.aging import generate_cashflow_and_aging
from core.fx_engine import post_fx_conversion_contra, run_ias21_revaluation
from core.investment_accounting import ingest_broker_trades_csv, get_investment_tax_summary


BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "sample_data"


class TestClearLedgerPrimeInvariants(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.tmp_dir.name) / "test_clearledger.db"
        init_database(self.db_path, seed_demo=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _assert_accounting_identities(self):
        st = generate_financial_statements(self.db_path)
        self.assertTrue(st["trial_balance"]["is_balanced"], f"Trial Balance out of balance: {st['trial_balance']}")
        self.assertTrue(st["balance_sheet"]["is_balanced"], f"Balance Sheet out of balance: {st['balance_sheet']}")
        return st

    def test_opening_balances_and_voucher_immutability_and_reversal(self):
        st = self._assert_accounting_identities()
        self.assertGreater(st["balance_sheet"]["total_assets"], 400000.0)

        # Reject unbalanced voucher
        with self.assertRaises(ValueError):
            post_voucher(
                voucher_type="JOURNAL",
                effective_date="2026-11-10",
                narration="Invalid Unbalanced Entry",
                lines=[
                    PostingInput(account_code="6120", debit="100.00"),
                    PostingInput(account_code="1010", credit="90.00"),
                ],
                db_path=self.db_path,
            )

        # Post valid voucher and reverse it
        vch = post_voucher(
            voucher_type="PAYMENT",
            effective_date="2026-11-10",
            narration="Cloud Server Payment",
            lines=[
                PostingInput(account_code="6120", debit="250.00"),
                PostingInput(account_code="1010", credit="250.00"),
            ],
            db_path=self.db_path,
        )
        st_after = self._assert_accounting_identities()
        self.assertAlmostEqual(
            st_after["profit_and_loss"]["net_profit"],
            st["profit_and_loss"]["net_profit"] - 250.0,
            places=2,
        )

        reverse_voucher(vch["voucher_id"], reversal_date="2026-11-10", reason="Duplicate Entry", db_path=self.db_path)
        st_rev = self._assert_accounting_identities()
        self.assertAlmostEqual(
            st_rev["profit_and_loss"]["net_profit"],
            st["profit_and_loss"]["net_profit"],
            places=2,
        )

    def test_fx_contra_conversion_realized_gain_and_ias21_revaluation(self):
        # Convert EUR 10,000 from Nostro 1011 (carried @ 1.08) to USD Bank 1010 @ 1.1050 -> Realized FX Gain = $250.00
        conv = post_fx_conversion_contra(
            effective_date="2026-11-10",
            from_account_code="1011",
            to_account_code="1010",
            from_amount_native=Decimal("10000.00"),
            execution_rate_to_usd=Decimal("1.1050"),
            db_path=self.db_path,
        )
        self.assertAlmostEqual(conv["realized_fx_gain_loss"], 250.00, places=2)
        self._assert_accounting_identities()

        # Run IAS 21 Revaluation as of 2026-11-10 (EUR 40k Nostro + EUR 20k Export AR @ 1.1050 vs 1.08 -> +$1,500; INR 4.2M @ 0.011765 vs 0.011905 -> -$588)
        reval = run_ias21_revaluation(
            as_of_date="2026-11-10",
            commit_voucher=True,
            auto_reverse_next_day=False,
            db_path=self.db_path,
        )
        self.assertIsNotNone(reval["committed_voucher"])
        self.assertEqual(reval["monetary_accounts_evaluated"], 3)
        self.assertAlmostEqual(reval["total_unrealized_fx_gain_loss"], 912.00, places=2)
        self._assert_accounting_identities()

        # Verify native foreign units were NOT altered by IAS 21 functional revaluation
        st = generate_financial_statements(self.db_path)
        eur_nostro = [n for n in st["nostro_positions"] if n["code"] == "1011"][0]
        self.assertAlmostEqual(eur_nostro["native_balance"], 40000.00, places=2)
        self.assertAlmostEqual(eur_nostro["functional_usd_value"], 44200.00, places=2)  # 40,000 * 1.105

    def test_post_trade_investment_fifo_tax_lots_and_gl_sync(self):
        csv_text = (SAMPLE_DIR / "sample_broker_trades.csv").read_text(encoding="utf-8")
        res = ingest_broker_trades_csv(csv_text, db_path=self.db_path)
        self.assertEqual(res["trades_processed"], 6)
        self.assertEqual(res["capital_gain_events_recorded"], 2)

        inv_summary = get_investment_tax_summary(self.db_path)
        # VOO: Bought 100 @ 480 + $15 = $48,015 ($480.15/sh) on 2025-05-15. Sold 40 @ 545 - $10 = $21,790 on 2026-11-05 (>365d -> LTCG)
        # FIFO cost for 40 VOO = $19,206.00 -> LTCG = $21,790 - $19,206 = $2,584.00
        self.assertAlmostEqual(inv_summary["summary"]["total_realized_ltcg"], 2584.00, places=2)

        # MSFT: Bought 50 @ 420 + $12.50 = $21,012.50 ($420.25/sh) on 2026-06-10. Sold 20 @ 455 - $8 = $9,092 on 2026-11-08 (<=365d -> STCG)
        # FIFO cost for 20 MSFT = $8,405.00 -> STCG = $9,092 - $8,405 = $687.00
        self.assertAlmostEqual(inv_summary["summary"]["total_realized_stcg"], 687.00, places=2)

        # Verify entire Balance Sheet & Trial Balance stay 100% balanced after all 6 post-trade GL postings!
        self._assert_accounting_identities()

    def test_coa_custom_account_ledger_drilldown_and_cashflow_aging(self):
        # Create custom SGD Nostro account
        acc = create_gl_account(
            code="1015",
            name="DBS Singapore Nostro (SGD)",
            account_type="ASSET",
            parent_group="Current Assets > Nostro / Foreign Banks",
            currency_code="SGD",
            is_monetary=True,
            db_path=self.db_path,
        )
        self.assertEqual(acc["code"], "1015")

        # Verify Tally-style running balance ledger statement on Operating Bank Cash (1010)
        stmt = get_account_ledger_statement("1010", db_path=self.db_path)
        self.assertGreaterEqual(stmt["total_entries"], 1)
        self.assertAlmostEqual(stmt["closing_functional_balance"], 150000.00, places=2)

        # Verify Cash Flow Statement & Bill-by-Bill AR Aging
        cfa = generate_cashflow_and_aging("2026-11-10", db_path=self.db_path)
        self.assertGreater(cfa["cash_flow_statement"]["financing_activities"], 350000.0)
        self.assertGreater(cfa["ar_aging"]["total_open_ar_usd"], 130000.0)

    def test_auth_registration_login_and_session_lifecycle(self):
        init_auth_tables(self.db_path)
        with self.assertRaisesRegex(ValueError, "Invalid email or password"):
            authenticate_user("cfo@clearledger.io", "Prime2026!", db_path=self.db_path)

        # Register new user and verify session + logout revocation
        reg = register_user("controller@acme.com", "SecurePass99!", "Priya Sharma", "Acme Global", db_path=self.db_path)
        self.assertEqual(reg["user"]["company_name"], "Acme Global")
        revoke_session(reg["token"], db_path=self.db_path)
        self.assertIsNone(get_session_user(reg["token"], db_path=self.db_path))
        login = authenticate_user("controller@acme.com", "SecurePass99!", db_path=self.db_path)
        self.assertEqual(get_session_user(login["token"], db_path=self.db_path)["user_id"], reg["user"]["user_id"])


if __name__ == "__main__":
    unittest.main()
