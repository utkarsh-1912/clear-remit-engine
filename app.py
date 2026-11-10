"""ClearRemit reconciliation workspace and preview API."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, model_validator

from engine.exporters import (
    ExportJournal,
    export_netsuite_csv,
    export_quickbooks_csv,
    export_tally_xml,
    export_xero_csv,
)
from engine.models import JournalEntryLine, SolverConfig
from engine.parsers import (
    add_ledger_references,
    detect_and_parse_statement,
    enrich_transactions_with_remittance_emails,
    parse_credit_memos_csv,
    parse_invoices_csv,
)
from engine.solver import reconcile_batch
from engine.tax_treaty import DTAA_TREATY_TABLE, evaluate_withholding_compliance
from workspace import ReviewConflict, RunNotFound, Workspace

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "sample_data"
DIST_DIR = BASE_DIR / "dist"
FORMATS = {
    "AUTO": "Auto-detect", "ISO20022_XML": "ISO 20022 XML",
    "MT940": "SWIFT MT940", "BAI2": "BAI2", "BANK_CSV": "Bank CSV",
}
SAMPLES = {
    "iso20022": ("ISO20022_XML", "sample_camt053.xml"),
    "mt940": ("MT940", "sample_mt940.txt"),
    "bai2": ("BAI2", "sample_bai2.txt"),
}
ACCOUNTS = {
    "1010": "Operating Bank Cash",
    "1200": "Accounts Receivable - Trade",
    "4090": "Sales Early-Pay Discounts",
    "1150": "Prepaid Tax / TDS Receivable",
    "2140": "Customer Credit Memos Applied",
    "6120": "Bank & Wire Transfer Charges",
    "1290": "AR Short-Pay Dispute Suspense",
    "2190": "Unapplied Customer Overpayment Credit",
    "2199": "Unreconciled AR Suspense Clearing",
}
EXPORTS = {
    "quickbooks": ("QuickBooks", "quickbooks_csv", "text/csv", "csv"),
    "xero": ("Xero", "xero_csv", "text/csv", "csv"),
    "netsuite": ("NetSuite", "netsuite_csv", "text/csv", "csv"),
    "tally": ("Tally Prime", "tally_xml", "application/xml", "xml"),
}
RULES = {(rule.corridor_code, rule.service_category): rule for rule in DTAA_TREATY_TABLE}
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
OptionalLabel = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Amount = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2)]
Percent = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
InputText = Annotated[str, Field(max_length=2_000_000)]
StatementFormat = Literal["AUTO", "ISO20022_XML", "MT940", "BAI2", "BANK_CSV"]


class TaxContext(BaseModel):
    corridor_code: Label
    service_category: Label

    @model_validator(mode="after")
    def validate_rule(self):
        self.corridor_code = self.corridor_code.upper()
        self.service_category = self.service_category.upper()
        if (self.corridor_code, self.service_category) not in RULES:
            raise ValueError("Unsupported corridor and service category combination.")
        return self


class TaxAuditRequest(TaxContext):
    gross_amount: Annotated[Amount, Field(gt=0)]
    withheld_amount: Amount

    @model_validator(mode="after")
    def validate_amounts(self):
        if self.withheld_amount > self.gross_amount:
            raise ValueError("Withholding cannot exceed the gross amount.")
        return self


class Account(BaseModel):
    code: Label
    name: Label


class ReconcileRequest(BaseModel):
    statement_format: StatementFormat = "AUTO"
    statement_content: InputText
    invoices_csv: InputText
    credit_memos_csv: InputText = ""
    remittance_emails_text: InputText = ""
    fallback_currency: Currency | None = None
    fallback_booking_date: date | None = None
    allowed_discount_pcts: list[Percent] = Field(default_factory=list, max_length=12)
    allowed_tds_pcts: list[Percent] = Field(default_factory=list, max_length=12)
    common_wire_fees: list[Amount] = Field(default_factory=list, max_length=12)
    tax_context: TaxContext | None = None
    accounts: dict[str, Account] = Field(default_factory=dict)
    netsuite_subsidiary: OptionalLabel = ""
    netsuite_department: OptionalLabel = ""
    xero_tax_rate: OptionalLabel = ""

    @model_validator(mode="after")
    def validate_accounts(self):
        if self.accounts.keys() - ACCOUNTS.keys():
            raise ValueError("Unknown GL account role.")
        return self


class RunRequest(ReconcileRequest):
    submission_id: UUID
    name: Label


class ReviewRequest(BaseModel):
    tx_id: str = Field(min_length=1, max_length=512)
    decision: Literal["approved", "rejected"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    version: int = Field(ge=0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    workspace = Workspace(Path(os.getenv("CLEARREMIT_DB_PATH", str(BASE_DIR / "data" / "workspace.sqlite3"))))
    username = os.getenv("CLEARREMIT_USERNAME")
    password = os.getenv("CLEARREMIT_PASSWORD")
    if bool(username) != bool(password):
        raise RuntimeError("Configure both CLEARREMIT_USERNAME and CLEARREMIT_PASSWORD.")
    if os.getenv("CLEARREMIT_REQUIRE_AUTH") == "1" and not username:
        raise RuntimeError("Workspace authentication credentials are required.")
    workspace.initialize()
    app.state.workspace = workspace
    app.state.credentials = f"{username}:{password}".encode("utf-8") if username else None
    app.state.username = username or "local operator"
    yield


app = FastAPI(title="ClearRemit Reconciliation Workspace", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def protect_workspace(request: Request, call_next):
    credentials = getattr(app.state, "credentials", None)
    if credentials and request.url.path != "/api/health":
        scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
        try:
            supplied = base64.b64decode(encoded, validate=True) if scheme.lower() == "basic" else b""
        except (ValueError, binascii.Error):
            supplied = b""
        if not secrets.compare_digest(credentials, supplied):
            return PlainTextResponse("Workspace sign-in required", status_code=401,
                                     headers={"WWW-Authenticate": 'Basic realm="ClearRemit", charset="UTF-8"'})
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("sec-fetch-site") == "cross-site":
            return PlainTextResponse("Cross-site workspace writes are blocked", status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdecimal() or len(length) > 8 or int(length) > 16_000_000:
            return PlainTextResponse("Request exceeds the workspace upload limit", status_code=413)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()
    ]})


@app.exception_handler(RunNotFound)
async def not_found(_request, _exc):
    return JSONResponse(status_code=404, content={"detail": "Run or transaction not found."})


@app.exception_handler(ReviewConflict)
async def conflict(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def _with_zero(values: list[Decimal]) -> list[Decimal]:
    return list(dict.fromkeys([Decimal("0"), *values]))


def _validate_inputs(req, transactions, invoices, memos):
    if not transactions or not invoices:
        raise ValueError("Provide at least one incoming transaction and one invoice.")
    if len(transactions) > 250 or len(invoices) > 10_000 or len(memos) > 5_000:
        raise ValueError("Split large files into batches of at most 250 transactions, 10,000 invoices and 5,000 credit memos.")
    for records, id_field, label in ((transactions, "tx_id", "transaction"), (invoices, "invoice_id", "invoice"),
                                     (memos, "memo_id", "credit memo")):
        seen = set()
        for row, record in enumerate(records, 1):
            record_id = getattr(record, id_field)
            if not record_id or len(record_id) > 512 or record_id.upper() in seen:
                raise ValueError(f"Invalid or duplicate {label} ID at row {row}.")
            seen.add(record_id.upper())
            record.currency = record.currency.strip().upper() or req.fallback_currency or ""
            if len(record.currency) != 3 or not record.currency.isascii() or not record.currency.isalpha():
                raise ValueError(f"Missing or invalid currency on {label} row {row}. Supply it in the source or set a fallback.")
    for row, tx in enumerate(transactions, 1):
        if not 0 < tx.amount < Decimal("1e13"):
            raise ValueError(f"Invalid incoming amount on transaction row {row}.")
        if not tx.booking_date and req.fallback_booking_date:
            tx.booking_date = req.fallback_booking_date.isoformat()
        try:
            tx.booking_date = date.fromisoformat(tx.booking_date).isoformat()
        except ValueError:
            raise ValueError(f"Missing or invalid booking date on transaction row {row}. Use YYYY-MM-DD.") from None
    for row, invoice in enumerate(invoices, 1):
        if not invoice.customer_id or not invoice.customer_name or not 0 <= invoice.open_amount <= invoice.gross_amount < Decimal("1e13"):
            raise ValueError(f"Invalid customer or amount on invoice row {row}.")
        if not all(0 <= rate <= 100 for rate in (invoice.eligible_discount_pct, invoice.expected_tds_pct)):
            raise ValueError(f"Invalid discount or withholding rate on invoice row {row}.")
    for row, memo in enumerate(memos, 1):
        if not memo.customer_id or not 0 < memo.amount < Decimal("1e13"):
            raise ValueError(f"Invalid customer or amount on credit memo row {row}.")


def _run_pipeline(req: ReconcileRequest, *, sample: bool = False) -> dict:
    try:
        transactions = detect_and_parse_statement(req.statement_content, req.statement_format)
        invoices = parse_invoices_csv(req.invoices_csv)
        memos = parse_credit_memos_csv(req.credit_memos_csv) if req.credit_memos_csv.strip() else []
        _validate_inputs(req, transactions, invoices, memos)
        invoice_ids = {invoice.invoice_id.upper() for invoice in invoices}
        memo_ids = {memo.memo_id.upper() for memo in memos}
        for tx in transactions:
            add_ledger_references(tx.hints, tx.raw_remittance_unstructured, invoice_ids, memo_ids)
        if req.remittance_emails_text.strip():
            enrich_transactions_with_remittance_emails(
                transactions, req.remittance_emails_text, invoice_ids=invoice_ids, memo_ids=memo_ids,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (SyntaxError, ArithmeticError, csv.Error) as exc:
        raise HTTPException(status_code=400, detail="The statement or ledger contains invalid input.") from exc

    config = SolverConfig(
        allowed_discount_pcts=_with_zero(req.allowed_discount_pcts),
        allowed_tds_pcts=_with_zero(req.allowed_tds_pcts),
        common_wire_fees=_with_zero(req.common_wire_fees),
    )
    proposals = reconcile_batch(transactions, invoices, memos, config=config)
    totals = {}
    tax_audits = {}
    for prop in proposals:
        bucket = totals.setdefault(prop.currency, dict.fromkeys((
            "total_deposit_cash", "total_gross_ar_cleared", "total_deductions_resolved",
            "unauthorized_short_pay_disputes",
        ), Decimal("0")))
        bucket["total_deposit_cash"] += prop.deposit_amount
        bucket["total_gross_ar_cleared"] += prop.total_gross_invoices
        bucket["total_deductions_resolved"] += prop.total_deductions
        bucket["unauthorized_short_pay_disputes"] += sum(d.amount for d in prop.deductions if not d.is_authorized)
        for deduction in prop.deductions:
            if account := req.accounts.get(deduction.gl_account_code):
                deduction.gl_account_code, deduction.gl_account_name = account.code, account.name
        for line in prop.journal_entries:
            if account := req.accounts.get(line.account_code):
                line.account_code, line.account_name = account.code, account.name
        withheld = sum(d.amount for d in prop.deductions if d.deduction_type == "TAX_WITHHOLDING_TDS")
        if req.tax_context and 0 < withheld <= prop.total_gross_invoices:
            tax_audits[prop.tx_id] = evaluate_withholding_compliance(
                **req.tax_context.model_dump(), gross_amount=prop.total_gross_invoices, withheld_amount=withheld,
            ).to_dict()

    summary = {
        "total_transactions": len(proposals),
        "auto_reconciled_count": sum(p.status == "AUTO_RECONCILED" for p in proposals),
        "action_required_dispute_count": sum(p.status == "ACTION_REQUIRED_SHORT_PAY" for p in proposals),
        "unmatched_count": sum(p.status == "UNMATCHED_SUSPENSE" for p in proposals),
        "totals_by_currency": {code: {k: float(v) for k, v in values.items()} for code, values in totals.items()},
    }
    if len(totals) == 1:
        summary.update(next(iter(summary["totals_by_currency"].values())))
    result = {
        "summary": summary,
        "transactions": [t.to_dict() for t in transactions],
        "invoices": [i.to_dict() for i in invoices],
        "credit_memos": [m.to_dict() for m in memos],
        "proposals": [p.to_dict() for p in proposals],
        "tax_audits": tax_audits,
    }
    if sample:
        result["exports"] = {key: _export(fmt, proposals, {}) for fmt, (_, key, _, _) in EXPORTS.items()}
        result["dtaa_rules"] = [r.to_dict() for r in DTAA_TREATY_TABLE]
    return result


def _export(fmt, journals, settings):
    if fmt == "quickbooks":
        return export_quickbooks_csv(journals)
    if fmt == "xero":
        return export_xero_csv(journals, tax_rate=settings.get("xero_tax_rate", ""))
    if fmt == "netsuite":
        return export_netsuite_csv(journals, subsidiary=settings.get("netsuite_subsidiary", ""),
                                   department=settings.get("netsuite_department", ""))
    return export_tally_xml(journals)


@app.get("/api/health")
def health():
    with app.state.workspace.connect() as db:
        db.execute("SELECT 1 FROM runs LIMIT 1").fetchone()
    return {"status": "ok"}


@app.get("/api/workspace")
def metadata():
    return {
        "statement_formats": FORMATS,
        "demo_formats": {key: FORMATS[value[0]] for key, value in SAMPLES.items()},
        "export_formats": {key: value[0] for key, value in EXPORTS.items()},
        "accounts": ACCOUNTS,
        "treaty_rules": [rule.to_dict() for rule in DTAA_TREATY_TABLE],
    }


@app.get("/api/sample")
def get_sample_benchmark(fmt: str = "iso20022") -> dict:
    if fmt.lower() not in SAMPLES:
        raise HTTPException(status_code=404, detail="Unsupported sample format.")
    stmt_fmt, filename = SAMPLES[fmt.lower()]
    config = SolverConfig()
    req = ReconcileRequest(
        statement_format=stmt_fmt,
        statement_content=(SAMPLE_DIR / filename).read_text(encoding="utf-8"),
        invoices_csv=(SAMPLE_DIR / "open_invoices.csv").read_text(encoding="utf-8"),
        credit_memos_csv=(SAMPLE_DIR / "credit_memos.csv").read_text(encoding="utf-8"),
        allowed_discount_pcts=config.allowed_discount_pcts,
        allowed_tds_pcts=config.allowed_tds_pcts,
        common_wire_fees=config.common_wire_fees,
        tax_context=TaxContext(corridor_code="IN-US", service_category="TECHNICAL_SERVICES_FTS"),
    )
    result = _run_pipeline(req, sample=True)
    result["raw_inputs"] = req.model_dump(include={
        "statement_format", "statement_content", "invoices_csv", "credit_memos_csv",
    })
    result["raw_inputs"]["sample_remittance_emails"] = (SAMPLE_DIR / "sample_remittance_emails.txt").read_text(encoding="utf-8")
    return result


@app.post("/api/reconcile")
def reconcile_custom(req: ReconcileRequest) -> dict:
    return _run_pipeline(req)


@app.get("/api/runs")
def list_runs(limit: Annotated[int, Query(ge=1, le=100)] = 25, offset: Annotated[int, Query(ge=0)] = 0):
    return app.state.workspace.list_runs(limit, offset)


@app.post("/api/runs", status_code=201)
def create_run(req: RunRequest):
    run_id = str(req.submission_id)
    fingerprint = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    existing = app.state.workspace.find_submission(run_id, fingerprint)
    if existing is not None:
        return existing
    settings = req.model_dump(mode="json", exclude={
        "submission_id", "name", "statement_content", "invoices_csv", "credit_memos_csv", "remittance_emails_text",
    })
    return app.state.workspace.save_run(run_id, req.name, app.state.username, fingerprint, settings, _run_pipeline(req))


@app.get("/api/runs/{run_id}")
def get_run(run_id: UUID):
    return app.state.workspace.get_run(str(run_id))


@app.post("/api/runs/{run_id}/reviews")
def review_transaction(run_id: UUID, req: ReviewRequest):
    return app.state.workspace.review(str(run_id), req.tx_id, req.decision, req.note, req.version, app.state.username)


@app.post("/api/tax-audit")
def run_tax_audit(req: TaxAuditRequest) -> dict:
    return evaluate_withholding_compliance(**req.model_dump()).to_dict()


@app.get("/api/runs/{run_id}/exports/{fmt}")
def download_export(run_id: UUID, fmt: str, currency: Currency):
    if fmt not in EXPORTS:
        raise HTTPException(status_code=404, detail="Unsupported ERP format.")
    run = app.state.workspace.get_run(str(run_id))
    journals = []
    for proposal in run["result"]["proposals"]:
        review = run["reviews"].get(proposal["tx_id"])
        if proposal["currency"] != currency or not review or review["decision"] != "approved":
            continue
        lines = [JournalEntryLine(**{**line, "debit": Decimal(str(line["debit"])),
                                    "credit": Decimal(str(line["credit"]))})
                 for line in proposal["journal_entries"]]
        journals.append(ExportJournal(proposal["tx_id"], proposal["booking_date"], proposal["currency"],
                                      proposal["matched_customer_name"], proposal["explanation_summary"], lines))
    if not journals:
        raise HTTPException(status_code=409, detail="Approve at least one matching journal in this currency.")
    _, _, media_type, extension = EXPORTS[fmt]
    return PlainTextResponse(
        _export(fmt, journals, run["settings"]), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{run_id}-{currency}-{fmt}.{extension}"'},
    )


@app.get("/api/export/{fmt}")
def download_sample_export(fmt: str):
    if fmt not in EXPORTS:
        raise HTTPException(status_code=404, detail="Unsupported ERP format.")
    _, key, media_type, extension = EXPORTS[fmt]
    return PlainTextResponse(get_sample_benchmark()["exports"][key], media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="sample-{fmt}.{extension}"'})


app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets", check_dir=False), name="assets")


@app.get("/", include_in_schema=False)
def index():
    path = DIST_DIR / "index.html"
    if not path.is_file():
        return PlainTextResponse("Build the frontend with npm ci and npm run build.", status_code=503)
    return FileResponse(path)
