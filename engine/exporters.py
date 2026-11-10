"""Multi-ERP General Ledger Journal Entry Exporters (QuickBooks, Xero, NetSuite, Tally Prime XML)."""

from __future__ import annotations
import csv
import io
import xml.sax.saxutils as saxutils
from dataclasses import dataclass
from typing import List
from engine.models import JournalEntryLine, ReconciliationProposal


@dataclass
class ExportJournal:
    tx_id: str
    booking_date: str
    currency: str
    matched_customer_name: str
    explanation_summary: str
    journal_entries: list[JournalEntryLine]


def _csv_cell(value: str) -> str:
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_quickbooks_csv(proposals: List[ReconciliationProposal | ExportJournal], booking_date: str | None = None) -> str:
    """Generates QuickBooks Online / Desktop Journal Entry Import CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "JournalNo",
            "JournalDate",
            "AccountCode",
            "AccountName",
            "Debits",
            "Credits",
            "Description",
            "Name",
            "InvoiceRef",
        ]
    )

    for prop in proposals:
        j_no = f"JE-{prop.tx_id}"
        for line in prop.journal_entries:
            writer.writerow(
                [
                    j_no,
                    booking_date or prop.booking_date,
                    _csv_cell(line.account_code),
                    _csv_cell(line.account_name),
                    f"{line.debit:.2f}" if line.debit > 0 else "",
                    f"{line.credit:.2f}" if line.credit > 0 else "",
                    _csv_cell(line.memo),
                    _csv_cell(line.entity_name),
                    _csv_cell(line.invoice_ref or ""),
                ]
            )
    return output.getvalue()


def export_xero_csv(
    proposals: List[ReconciliationProposal | ExportJournal],
    booking_date: str | None = None,
    *,
    tax_rate: str = "",
) -> str:
    """Generates Xero Manual Journal / Split Reconciliation CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "*Narration",
            "*Date",
            "Description",
            "*AccountCode",
            "*TaxRate",
            "*Amount",
            "ContactName",
            "Reference",
        ]
    )

    for prop in proposals:
        narration = f"Reconciliation {prop.tx_id} ({prop.matched_customer_name})"
        for line in prop.journal_entries:
            # Xero uses positive amounts for Debits and negative amounts for Credits
            signed_amt = line.debit if line.debit > 0 else -line.credit
            writer.writerow(
                [
                    narration,
                    booking_date or prop.booking_date,
                    _csv_cell(line.memo),
                    _csv_cell(line.account_code),
                    _csv_cell(tax_rate),
                    f"{signed_amt:.2f}",
                    _csv_cell(line.entity_name),
                    _csv_cell(line.invoice_ref or prop.tx_id),
                ]
            )
    return output.getvalue()


def export_netsuite_csv(
    proposals: List[ReconciliationProposal | ExportJournal],
    booking_date: str | None = None,
    *,
    subsidiary: str = "",
    department: str = "",
) -> str:
    """Generates Oracle NetSuite Multi-Line Journal Entry Import CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ExternalID",
            "TranDate",
            "Subsidiary",
            "Currency",
            "AccountNumber",
            "AccountName",
            "Debit",
            "Credit",
            "Memo",
            "Entity",
            "Department",
        ]
    )

    for prop in proposals:
        ext_id = f"NS-RECON-{prop.tx_id}"
        for line in prop.journal_entries:
            writer.writerow(
                [
                    ext_id,
                    booking_date or prop.booking_date,
                    _csv_cell(subsidiary),
                    prop.currency,
                    _csv_cell(line.account_code),
                    _csv_cell(line.account_name),
                    f"{line.debit:.2f}",
                    f"{line.credit:.2f}",
                    _csv_cell(line.memo),
                    _csv_cell(line.entity_name),
                    _csv_cell(department),
                ]
            )
    return output.getvalue()


def export_tally_xml(proposals: List[ReconciliationProposal | ExportJournal], booking_date: str | None = None) -> str:
    """Generates Tally Prime / Tally.ERP 9 Receipt & Journal Voucher XML Envelope."""
    vouchers_xml = []
    for prop in proposals:
        clean_date = saxutils.escape((booking_date or prop.booking_date).replace("-", ""))
        ledger_entries = []
        for line in prop.journal_entries:
            # In Tally XML, Debit is ISDEEMEDPOSITIVE=Yes with negative amount; Credit is ISDEEMEDPOSITIVE=No with positive amount
            is_debit = line.debit > 0
            deemed_pos = "Yes" if is_debit else "No"
            tally_amt = f"-{line.debit:.2f}" if is_debit else f"{line.credit:.2f}"
            ledger_name = saxutils.escape(f"{line.account_code} - {line.account_name}")
            bill_alloc = ""
            if line.invoice_ref:
                bill_alloc = (
                    f"\n            <BILLALLOCATIONS.LIST>"
                    f"\n              <NAME>{saxutils.escape(line.invoice_ref)}</NAME>"
                    f"\n              <BILLTYPE>Agst Ref</BILLTYPE>"
                    f"\n              <AMOUNT>{tally_amt}</AMOUNT>"
                    f"\n            </BILLALLOCATIONS.LIST>"
                )
            ledger_entries.append(
                f"""          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>{ledger_name}</LEDGERNAME>
            <ISDEEMEDPOSITIVE>{deemed_pos}</ISDEEMEDPOSITIVE>
            <AMOUNT>{tally_amt}</AMOUNT>{bill_alloc}
          </ALLLEDGERENTRIES.LIST>"""
            )

        narr = saxutils.escape(f"{prop.tx_id} | {prop.matched_customer_name} | {prop.explanation_summary}")
        vouchers_xml.append(
            f"""        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Receipt" ACTION="Create">
            <DATE>{clean_date}</DATE>
            <VOUCHERNUMBER>{saxutils.escape(prop.tx_id)}</VOUCHERNUMBER>
            <NARRATION>{narr}</NARRATION>
{chr(10).join(ledger_entries)}
          </VOUCHER>
        </TALLYMESSAGE>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
      </REQUESTDESC>
      <REQUESTDATA>
{chr(10).join(vouchers_xml)}
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
"""
