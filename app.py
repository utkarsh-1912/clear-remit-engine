"""FastAPI Application v2.0 for ClearRemit — Multi-Rail B2B Short-Pay & Tax-Treaty Reconciliation Suite."""

from __future__ import annotations
import pathlib
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from engine.models import SolverConfig
from engine.parsers import (
    detect_and_parse_statement,
    enrich_transactions_with_remittance_emails,
    parse_invoices_csv,
    parse_credit_memos_csv,
)
from engine.solver import reconcile_batch
from engine.exporters import (
    export_quickbooks_csv,
    export_xero_csv,
    export_netsuite_csv,
    export_tally_xml,
)
from engine.tax_treaty import (
    DTAA_TREATY_TABLE,
    evaluate_withholding_compliance,
)


BASE_DIR = pathlib.Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "sample_data"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="ClearRemit v2.0 — ISO 20022 / MT940 / BAI2 Short-Pay & DTAA Tax Reconciliation Suite",
    version="2.0.0",
)


class ReconcileRequest(BaseModel):
    statement_format: str = "AUTO"  # "AUTO", "ISO20022_XML", "MT940", "BAI2", "BANK_CSV"
    statement_content: str
    invoices_csv: str
    credit_memos_csv: str = ""
    remittance_emails_text: str = ""
    allowed_discount_pcts: Optional[List[float]] = None
    allowed_tds_pcts: Optional[List[float]] = None
    common_wire_fees: Optional[List[float]] = None


class TaxAuditRequest(BaseModel):
    corridor_code: str = "IN-US"
    service_category: str = "TECHNICAL_SERVICES_FTS"
    gross_amount: float = 24000.0
    withheld_amount: float = 2400.0


def _run_pipeline(req: ReconcileRequest) -> dict:
    try:
        transactions = detect_and_parse_statement(req.statement_content, req.statement_format)
        if req.remittance_emails_text.strip():
            enrich_transactions_with_remittance_emails(transactions, req.remittance_emails_text)
        invoices = parse_invoices_csv(req.invoices_csv)
        memos = parse_credit_memos_csv(req.credit_memos_csv) if req.credit_memos_csv.strip() else []
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Input parsing error: {exc}") from exc

    config = SolverConfig()
    if req.allowed_discount_pcts is not None:
        config.allowed_discount_pcts = [Decimal(str(x)) for x in req.allowed_discount_pcts]
    if req.allowed_tds_pcts is not None:
        config.allowed_tds_pcts = [Decimal(str(x)) for x in req.allowed_tds_pcts]
    if req.common_wire_fees is not None:
        config.common_wire_fees = [Decimal(str(x)) for x in req.common_wire_fees]

    proposals = reconcile_batch(transactions, invoices, memos, config=config)

    # Automatically run Cross-Border DTAA Tax Withholding Audit on any proposal with TDS deductions
    tax_audits = {}
    for prop in proposals:
        tds_deds = [d for d in prop.deductions if d.deduction_type == "TAX_WITHHOLDING_TDS"]
        if tds_deds:
            tds_total = sum((d.amount for d in tds_deds), Decimal("0.00"))
            audit = evaluate_withholding_compliance(
                corridor_code="IN-US",
                service_category="TECHNICAL_SERVICES_FTS",
                gross_amount=prop.total_gross_invoices,
                withheld_amount=tds_total,
            )
            tax_audits[prop.tx_id] = audit.to_dict()

    total_deposit = sum((p.deposit_amount for p in proposals), Decimal("0.00"))
    total_gross = sum((p.total_gross_invoices for p in proposals), Decimal("0.00"))
    total_deductions = sum((p.total_deductions for p in proposals), Decimal("0.00"))
    disputed_amt = sum(
        (d.amount for p in proposals for d in p.deductions if not d.is_authorized),
        Decimal("0.00"),
    )
    auto_count = sum(1 for p in proposals if p.status == "AUTO_RECONCILED")
    dispute_count = sum(1 for p in proposals if p.status == "ACTION_REQUIRED_SHORT_PAY")
    unmatched_count = sum(1 for p in proposals if p.status == "UNMATCHED_SUSPENSE")

    return {
        "summary": {
            "total_transactions": len(proposals),
            "auto_reconciled_count": auto_count,
            "action_required_dispute_count": dispute_count,
            "unmatched_count": unmatched_count,
            "total_deposit_cash": float(total_deposit),
            "total_gross_ar_cleared": float(total_gross),
            "total_deductions_resolved": float(total_deductions),
            "unauthorized_short_pay_disputes": float(disputed_amt),
        },
        "transactions": [t.to_dict() for t in transactions],
        "invoices": [i.to_dict() for i in invoices],
        "credit_memos": [m.to_dict() for m in memos],
        "proposals": [p.to_dict() for p in proposals],
        "tax_audits": tax_audits,
        "dtaa_rules": [r.to_dict() for r in DTAA_TREATY_TABLE],
        "exports": {
            "quickbooks_csv": export_quickbooks_csv(proposals),
            "xero_csv": export_xero_csv(proposals),
            "netsuite_csv": export_netsuite_csv(proposals),
            "tally_xml": export_tally_xml(proposals),
        },
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/sample")
def get_sample_benchmark(fmt: str = "iso20022") -> dict:
    fmt_map = {
        "iso20022": ("ISO20022_XML", "sample_camt053.xml"),
        "mt940": ("MT940", "sample_mt940.txt"),
        "bai2": ("BAI2", "sample_bai2.txt"),
    }
    stmt_fmt, filename = fmt_map.get(fmt.lower(), ("ISO20022_XML", "sample_camt053.xml"))
    stmt_text = (SAMPLE_DIR / filename).read_text(encoding="utf-8")
    inv_csv = (SAMPLE_DIR / "open_invoices.csv").read_text(encoding="utf-8")
    cm_csv = (SAMPLE_DIR / "credit_memos.csv").read_text(encoding="utf-8")
    emails_txt = (SAMPLE_DIR / "sample_remittance_emails.txt").read_text(encoding="utf-8")

    req = ReconcileRequest(
        statement_format=stmt_fmt,
        statement_content=stmt_text,
        invoices_csv=inv_csv,
        credit_memos_csv=cm_csv,
        remittance_emails_text="",
    )
    res = _run_pipeline(req)
    res["raw_inputs"] = {
        "statement_format": stmt_fmt,
        "statement_content": stmt_text,
        "invoices_csv": inv_csv,
        "credit_memos_csv": cm_csv,
        "sample_remittance_emails": emails_txt,
    }
    return res


@app.post("/api/reconcile")
def reconcile_custom(req: ReconcileRequest) -> dict:
    return _run_pipeline(req)


@app.post("/api/tax-audit")
def run_tax_audit(req: TaxAuditRequest) -> dict:
    res = evaluate_withholding_compliance(
        corridor_code=req.corridor_code,
        service_category=req.service_category,
        gross_amount=Decimal(str(req.gross_amount)),
        withheld_amount=Decimal(str(req.withheld_amount)),
    )
    return res.to_dict()


@app.get("/api/export/{erp_format}", response_class=PlainTextResponse)
def download_sample_export(erp_format: str) -> PlainTextResponse:
    sample = get_sample_benchmark()
    exports = sample["exports"]
    key_map = {
        "quickbooks": ("quickbooks_csv", "text/csv", "quickbooks_journal_import.csv"),
        "xero": ("xero_csv", "text/csv", "xero_manual_journal.csv"),
        "netsuite": ("netsuite_csv", "text/csv", "netsuite_journal_import.csv"),
        "tally": ("tally_xml", "application/xml", "tally_prime_vouchers.xml"),
    }
    if erp_format.lower() not in key_map:
        raise HTTPException(status_code=404, detail="Unsupported ERP format")
    key, media_type, filename = key_map[erp_format.lower()]
    return PlainTextResponse(
        content=exports[key],
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
