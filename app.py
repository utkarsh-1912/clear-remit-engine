"""ClearRemit reconciliation workspace and preview API."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine.exporters import (
    export_netsuite_csv,
    export_quickbooks_csv,
    export_tally_xml,
    export_xero_csv,
)
from engine.models import SolverConfig
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
PUBLIC_PAGES = json.loads((BASE_DIR / "frontend" / "public-routes.json").read_text(encoding="utf-8"))
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
    entity_id: str = "default"
    use_registered_ledger: bool = False


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
    users = json.loads(os.getenv("CLEARREMIT_USERS_JSON", "[]"))
    if not isinstance(users, list):
        raise RuntimeError("CLEARREMIT_USERS_JSON must be an array of operators.")
    proxy_key = os.getenv("CLEARREMIT_SSO_PROXY_SECRET", "")
    for user in users:
        if (not isinstance(user, dict) or not user.get("username")
                or not (user.get("password") or (proxy_key and user.get("sso_subject")))
                or user.get("role") not in {"admin", "analyst", "approver", "auditor"}):
            raise RuntimeError("Each operator requires a username, credential and supported role.")
        if any(not isinstance(user.get(key, []), list) for key in ("organizations", "entities")):
            raise RuntimeError("Operator organizations and entities must be lists of IDs.")
    if bool(username) != bool(password):
        raise RuntimeError("Configure both CLEARREMIT_USERNAME and CLEARREMIT_PASSWORD.")
    if os.getenv("CLEARREMIT_REQUIRE_AUTH") == "1" and not username and not users:
        raise RuntimeError("Workspace authentication credentials are required.")
    workspace.initialize()
    app.state.workspace = workspace
    app.state.credentials = f"{username}:{password}".encode("utf-8") if username else None
    app.state.username = username or "local operator"
    app.state.users = users
    app.state.connectors = load_connectors()
    if proxy_key and len(proxy_key) < 32:
        raise RuntimeError("CLEARREMIT_SSO_PROXY_SECRET must have at least 32 characters.")
    app.state.sso_proxy_key = proxy_key
    yield


app = FastAPI(title="ClearRemit Reconciliation Workspace", version="3.0.0", lifespan=lifespan,
              docs_url="/api/docs", redoc_url="/api/redoc")


@app.middleware("http")
async def protect_workspace(request: Request, call_next):
    credentials = getattr(app.state, "credentials", None)
    users = getattr(app.state, "users", [])
    proxy_key = getattr(app.state, "sso_proxy_key", "")
    request.state.operator = {"username": app.state.username, "role": "admin", "organizations": ["*"]}
    public = request.url.path in {"/api/health", "/portal", "/api/portal", "/api/portal/requests"}
    public = public or request.url.path.rstrip("/") in PUBLIC_PAGES
    public = public or request.url.path.startswith(("/api/connector-hooks/", "/api/public/demo/"))
    if (credentials or users or proxy_key) and not public and not request.url.path.startswith("/assets/"):
        scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
        try:
            supplied = base64.b64decode(encoded, validate=True) if scheme.lower() == "basic" else b""
        except (ValueError, binascii.Error):
            supplied = b""
        operator = None
        proxy_supplied = request.headers.get("x-clearremit-proxy-key", "")
        subject = request.headers.get("x-clearremit-identity", "")
        verified_proxy = proxy_key and secrets.compare_digest(proxy_key.encode(), proxy_supplied.encode()) and subject
        for user in users:
            matches_basic = user.get("password") and secrets.compare_digest(
                f'{user["username"]}:{user["password"]}'.encode(), supplied
            )
            if matches_basic or (verified_proxy and subject == user.get("sso_subject")):
                operator = {key: user.get(key, []) for key in ("username", "role", "organizations")}
                if "entities" in user:
                    operator["entities"] = user["entities"]
        if credentials and secrets.compare_digest(credentials, supplied):
            operator = {"username": app.state.username, "role": "admin", "organizations": ["*"]}
        if operator is None:
            return PlainTextResponse("Workspace sign-in required", status_code=401,
                                     headers={"WWW-Authenticate": 'Basic realm="ClearRemit", charset="UTF-8"'})
        request.state.operator = operator
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


@lru_cache(maxsize=3)
def public_sample(fmt: str) -> dict:
    return get_sample_benchmark(fmt)


@app.get("/api/public/demo/{fmt}")
def demo_fixture(fmt: Literal["iso20022", "mt940", "bai2"]):
    sample = public_sample(fmt)
    return {
        "summary": sample["summary"],
        "proposals": sample["proposals"],
        "statement": sample["raw_inputs"]["statement_content"],
        "export_formats": {key: item[0] for key, item in EXPORTS.items()},
    }


@app.get("/api/public/demo/{fmt}/exports/{erp}")
def demo_export(fmt: Literal["iso20022", "mt940", "bai2"], erp: str):
    if erp not in EXPORTS:
        raise HTTPException(status_code=404, detail="Unknown demo export format.")
    _, key, media_type, extension = EXPORTS[erp]
    return PlainTextResponse(public_sample(fmt)["exports"][key], media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="clearremit-demo-{erp}.{extension}"'})


@app.post("/api/reconcile")
def reconcile_custom(req: ReconcileRequest, request: Request) -> dict:
    require_role(request, "admin", "analyst", "approver")
    return _run_pipeline(req)


@app.get("/api/runs")
def list_runs(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 25,
              offset: Annotated[int, Query(ge=0)] = 0, entity_id: str = "default"):
    entity_access(request, entity_id)
    return app.state.workspace.list_runs(limit, offset, entity_id)


@app.post("/api/runs", status_code=201)
def create_run(req: RunRequest, request: Request):
    require_role(request, "admin", "analyst")
    entity_access(request, req.entity_id)
    return submit_run(req, request.state.operator["username"])


def submit_run(req: RunRequest, actor: str):
    run_id = str(req.submission_id)
    fingerprint_data = req.model_dump_json(exclude={"use_registered_ledger"} if not req.use_registered_ledger else set())
    fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()
    existing = app.state.workspace.find_submission(run_id, fingerprint)
    if existing is not None:
        return existing
    settings = req.model_dump(mode="json", exclude={
        "submission_id", "name", "statement_content", "invoices_csv", "credit_memos_csv", "remittance_emails_text",
    })
    pipeline_request = req
    if req.use_registered_ledger:
        if req.invoices_csv.strip():
            raise HTTPException(422, "Choose either the invoice register or an uploaded ledger.")
        ledger = registered_ledger(app.state.workspace, req.entity_id)
        pipeline_request = req.model_copy(update={"invoices_csv": ledger})
    result = _run_pipeline(pipeline_request)
    if req.use_registered_ledger:
        for invoice in result["invoices"]:
            invoice["opening_amount"] = invoice["gross_amount"]
    return app.state.workspace.save_run(run_id, req.name, actor, fingerprint,
                                       settings, result, req.entity_id)


@app.get("/api/runs/{run_id}")
def get_run(run_id: UUID, request: Request):
    return run_access(request, str(run_id))


@app.post("/api/runs/{run_id}/reviews")
def review_transaction(run_id: UUID, req: ReviewRequest, request: Request):
    require_role(request, "admin", "approver")
    run = run_access(request, str(run_id))
    entity = entity_access(request, run["entity_id"])
    if req.decision == "approved" and entity["settings"].get("separate_approval") and run["created_by"] == request.state.operator["username"]:
        raise HTTPException(409, "A different operator must approve this entity's journals.")
    return app.state.workspace.review(str(run_id), req.tx_id, req.decision, req.note,
                                      req.version, request.state.operator["username"])


@app.post("/api/tax-audit")
def run_tax_audit(req: TaxAuditRequest) -> dict:
    return evaluate_withholding_compliance(**req.model_dump()).to_dict()


@app.get("/api/runs/{run_id}/exports/{fmt}")
def download_export(run_id: UUID, fmt: str, currency: Currency, request: Request):
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Open exports from the workspace.")
    run = run_access(request, str(run_id))
    require_role(request, "admin", "approver")
    if fmt not in EXPORTS:
        raise HTTPException(status_code=404, detail="Unsupported ERP format.")
    key = json.dumps([str(run_id), fmt, currency, run["revision"], run["reviews"]], sort_keys=True)
    batch_id = str(uuid5(NAMESPACE_URL, key))
    app.state.workspace.prepare_export(str(run_id), fmt, currency, request.state.operator["username"], batch_id)
    return RedirectResponse(f"/api/export-batches/{batch_id}/download", status_code=307)


@app.get("/api/export/{fmt}")
def download_sample_export(fmt: str):
    if fmt not in EXPORTS:
        raise HTTPException(status_code=404, detail="Unsupported ERP format.")
    _, key, media_type, extension = EXPORTS[fmt]
    return PlainTextResponse(get_sample_benchmark()["exports"][key], media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="sample-{fmt}.{extension}"'})


app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets", check_dir=False), name="assets")


from platform_api import entity_access, register_routes, require_role, run_access
from receivables import register_receivables, registered_ledger
from integrations import load_connectors, register_integrations

register_routes(app)
register_receivables(app)
register_integrations(app, RunRequest, submit_run, _export, EXPORTS)


@app.get("/", include_in_schema=False)
@app.get("/portal", include_in_schema=False)
def index():
    path = DIST_DIR / "index.html"
    if not path.is_file():
        return PlainTextResponse("Build the frontend with npm ci and npm run build.", status_code=503)
    return FileResponse(path, headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})


def public_page(request: Request):
    path = DIST_DIR / "index.html"
    if not path.is_file():
        return PlainTextResponse("Frontend build is unavailable.", status_code=503)
    title = f"{PUBLIC_PAGES[request.url.path]} | ClearRemit"
    html = path.read_text(encoding="utf-8").replace(
        "<title>ClearRemit | Reconciliation Workspace</title>", f"<title>{escape(title)}</title>", 1,
    )
    return HTMLResponse(html)


for page_path in PUBLIC_PAGES:
    app.add_api_route(page_path, public_page, methods=["GET", "HEAD"], include_in_schema=False)


def is_page_request(request: Request) -> bool:
    path = request.url.path.split("/", 2)[1]
    return request.method in {"GET", "HEAD"} and path not in {"api", "assets"}


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and is_page_request(request):
        path = DIST_DIR / "index.html"
        if path.is_file():
            return FileResponse(path, status_code=404, headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Page not found · ClearRemit</title>'
            '<main><h1>Page not found</h1><a href="/">Back to workspace</a></main></html>',
            status_code=404,
        )
    return await http_exception_handler(request, exc)


@app.exception_handler(500)
async def unexpected_error(request: Request, _exc: Exception):
    if is_page_request(request):
        return FileResponse(BASE_DIR / "static" / "500.html", status_code=500,
                            headers={"Cache-Control": "no-store"})
    return JSONResponse({"detail": "Something went wrong. Try again."}, status_code=500,
                        headers={"Cache-Control": "no-store"})
