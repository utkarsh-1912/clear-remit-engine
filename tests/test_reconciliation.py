"""Unit and Integration Tests for ClearRemit v2.0 (ISO 20022, MT940, BAI2, Email Linking, & DTAA Tax Suite)."""

import pathlib
import unittest
from decimal import Decimal
import app as fastapi_app
from engine.parsers import (
    parse_iso20022_xml,
    parse_mt940_statement,
    parse_bai2_statement,
    enrich_transactions_with_remittance_emails,
    parse_invoices_csv,
    parse_credit_memos_csv,
    extract_unstructured_remittance_hints,
)
from engine.solver import reconcile_batch
from engine.tax_treaty import evaluate_withholding_compliance
from engine.exporters import (
    export_quickbooks_csv,
    export_xero_csv,
    export_netsuite_csv,
    export_tally_xml,
)


BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "sample_data"


class TestClearRemitV2Suite(unittest.TestCase):
    def setUp(self):
        self.xml_text = (SAMPLE_DIR / "sample_camt053.xml").read_text(encoding="utf-8")
        self.mt940_text = (SAMPLE_DIR / "sample_mt940.txt").read_text(encoding="utf-8")
        self.bai2_text = (SAMPLE_DIR / "sample_bai2.txt").read_text(encoding="utf-8")
        self.emails_text = (SAMPLE_DIR / "sample_remittance_emails.txt").read_text(encoding="utf-8")
        self.inv_csv = (SAMPLE_DIR / "open_invoices.csv").read_text(encoding="utf-8")
        self.cm_csv = (SAMPLE_DIR / "credit_memos.csv").read_text(encoding="utf-8")

        self.invoices = parse_invoices_csv(self.inv_csv)
        self.memos = parse_credit_memos_csv(self.cm_csv)

    def test_unstructured_hint_extraction(self):
        hint = extract_unstructured_remittance_hints("PMT INV-2026-001/002/003 LESS 2% EARLY PAY DISC")
        self.assertEqual(hint.referenced_invoices, ["INV-2026-001", "INV-2026-002", "INV-2026-003"])
        self.assertEqual(hint.claimed_discount_pct, Decimal("2.00"))

    def test_iso20022_batch_reconciliation_and_gl_balance(self):
        transactions = parse_iso20022_xml(self.xml_text)
        self.assertEqual(len(transactions), 6)
        proposals = reconcile_batch(transactions, self.invoices, self.memos)
        self.assertEqual(len(proposals), 6)

        by_tx = {p.tx_id: p for p in proposals}

        # TX-101: Multi-invoice slash expansion + 2% Early Pay Discount ($29,500 - $590 = $28,910)
        p101 = by_tx["TX-101"]
        self.assertEqual(p101.status, "AUTO_RECONCILED")
        self.assertEqual(p101.total_gross_invoices, Decimal("29500.00"))
        self.assertEqual(p101.total_deductions, Decimal("590.00"))

        # TX-104: Blind Subset-Sum Wire ($18,414 = INV-2026-008 + INV-2026-009 - 2% Disc $376 - $10 Fee)
        p104 = by_tx["TX-104"]
        self.assertEqual(p104.status, "AUTO_RECONCILED")
        self.assertEqual(p104.match_method, "BLIND_SUBSET_SUM_SOLVER")
        self.assertEqual([a.invoice_id for a in p104.allocations], ["INV-2026-008", "INV-2026-009"])

        # Verify Double-Entry Accounting Invariant: sum(Debits) == sum(Credits)
        for prop in proposals:
            total_debits = sum((j.debit for j in prop.journal_entries), Decimal("0.00"))
            total_credits = sum((j.credit for j in prop.journal_entries), Decimal("0.00"))
            self.assertEqual(total_debits, total_credits)

        self.assertIn("JE-TX-101", export_quickbooks_csv(proposals))
        self.assertIn("Reconciliation TX-101", export_xero_csv(proposals))
        self.assertIn("NS-RECON-TX-101", export_netsuite_csv(proposals))
        self.assertIn("<TALLYMESSAGE", export_tally_xml(proposals))

    def test_mt940_and_bai2_parsers(self):
        mt_txs = parse_mt940_statement(self.mt940_text)
        self.assertEqual(len(mt_txs), 4)
        mt_props = reconcile_batch(mt_txs, self.invoices, self.memos)
        self.assertEqual(mt_props[0].total_gross_invoices, Decimal("29500.00"))
        self.assertEqual(mt_props[3].total_gross_invoices, Decimal("18800.00"))

        bai_txs = parse_bai2_statement(self.bai2_text)
        self.assertEqual(len(bai_txs), 4)
        bai_props = reconcile_batch(bai_txs, self.invoices, self.memos)
        self.assertEqual(bai_props[0].total_gross_invoices, Decimal("29500.00"))
        self.assertEqual(bai_props[2].total_gross_invoices, Decimal("24000.00"))

    def test_decoupled_email_remittance_enrichment(self):
        # Before email enrichment, TX-104 has 0 invoice hints and uses BLIND_SUBSET_SUM_SOLVER
        txs = parse_iso20022_xml(self.xml_text)
        tx104 = [t for t in txs if t.tx_id == "TX-104"][0]
        self.assertEqual(tx104.hints.referenced_invoices, [])

        # After email enrichment, TX-104 links to the NorthStar email and upgrades to HINT_GUIDED_SOLVER
        enrich_transactions_with_remittance_emails(txs, self.emails_text)
        self.assertEqual(tx104.hints.referenced_invoices, ["INV-2026-008", "INV-2026-009"])
        props = reconcile_batch(txs, self.invoices, self.memos)
        p104 = [p for p in props if p.tx_id == "TX-104"][0]
        self.assertEqual(p104.match_method, "HINT_GUIDED_SOLVER")
        self.assertEqual(p104.confidence_score, 99.0)

    def test_dtaa_tax_treaty_validator(self):
        # Compliant 10% IN-US Technical Services withholding
        ok_res = evaluate_withholding_compliance(
            corridor_code="IN-US",
            service_category="TECHNICAL_SERVICES_FTS",
            gross_amount=Decimal("24000.00"),
            withheld_amount=Decimal("2400.00"),
        )
        self.assertEqual(ok_res.status, "COMPLIANT_TREATY_RATE")
        self.assertEqual(ok_res.excess_overwithheld_amount, Decimal("0.00"))

        # Over-withheld 20% penalty rate when Form 10F / TRC is missing
        over_res = evaluate_withholding_compliance(
            corridor_code="IN-US",
            service_category="TECHNICAL_SERVICES_FTS",
            gross_amount=Decimal("24000.00"),
            withheld_amount=Decimal("4800.00"),
        )
        self.assertEqual(over_res.status, "OVERWITHHELD_MISSING_DOCS")
        self.assertEqual(over_res.excess_overwithheld_amount, Decimal("2400.00"))

    def test_fastapi_endpoints_direct(self):
        for fmt in ("iso20022", "mt940", "bai2"):
            res = fastapi_app.get_sample_benchmark(fmt)
            self.assertGreaterEqual(res["summary"]["total_transactions"], 4)
            self.assertIn("TX-103", res["tax_audits"])


if __name__ == "__main__":
    unittest.main()
