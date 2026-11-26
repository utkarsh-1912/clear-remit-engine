"""ClearLedger Prime — Unified Tally Prime + Finacle Financial Core OS (FastAPI Backend)."""

from __future__ import annotations
import pathlib
import tempfile
import json
import time
from decimal import Decimal
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from core.database import init_database, DEFAULT_DB_PATH
from core.auth import init_auth_tables, register_user, authenticate_user, get_session_user, revoke_session, registration_available
from core.ledger import (
    PostingInput,
    post_voucher,
    reverse_voucher,
    list_vouchers,
    list_vouchers_paginated,
    list_accounts,
)
from core.reports import generate_financial_statements
from core.coa_manager import create_gl_account, get_account_ledger_statement
from core.aging import generate_cashflow_and_aging
from core.fx_engine import list_fx_rates, upsert_fx_rate, post_fx_conversion_contra, run_ias21_revaluation
from core.investment_accounting import ingest_broker_trades_csv, get_investment_tax_summary
from core.bulk_engine import (
    launch_streaming_upload_job,
    get_job_status,
    list_bulk_jobs,
)

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
from engine.tax_treaty import DTAA_TREATY_TABLE, evaluate_withholding_compliance


BASE_DIR = pathlib.Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"

# Initialize persistent multi-currency ledger & auth tables on startup
init_database(DEFAULT_DB_PATH)
init_auth_tables(DEFAULT_DB_PATH)

app = FastAPI(
    title="ClearLedger Prime v5.0 — Modular Multi-Currency Financial OS",
    version="5.0.0",
    docs_url="/api-reference",
)
app.add_middleware(GZipMiddleware, minimum_size=500)
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="dist_assets")


@app.middleware("http")
async def protect_workspace_data(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        if not await run_in_threadpool(get_session_user, request.cookies.get("cl_session"), db_path=DEFAULT_DB_PATH):
            return JSONResponse({"detail": "Sign in to access the workspace."}, status_code=401)
    return await call_next(request)


PUBLIC_API_PATHS = {
    "/api/health", "/api/auth/me", "/api/auth/login",
    "/api/auth/register", "/api/auth/logout",
}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}



# --- Pydantic Request Schemas ---

class ReconcileRequest(BaseModel):
    statement_format: str = "AUTO"
    statement_content: str
    invoices_csv: str
    credit_memos_csv: str = ""
    remittance_emails_text: str = ""
    allowed_discount_pcts: Optional[List[float]] = None
    allowed_tds_pcts: Optional[List[float]] = None
    common_wire_fees: Optional[List[float]] = None
    tax_corridor: Optional[str] = None
    tax_service_category: Optional[str] = None


class TaxAuditRequest(BaseModel):
    corridor_code: str
    service_category: str
    gross_amount: float
    withheld_amount: float


class VoucherLinePayload(BaseModel):
    account_code: str
    debit: float = 0.0
    credit: float = 0.0
    native_currency: str = "USD"
    exchange_rate: Optional[float] = None
    bill_ref: Optional[str] = None
    party_name: Optional[str] = None


class CreateVoucherRequest(BaseModel):
    voucher_type: str = "JOURNAL"
    effective_date: str
    narration: str
    source_ref: Optional[str] = None
    lines: List[VoucherLinePayload]


class ReverseVoucherRequest(BaseModel):
    reversal_date: str
    reason: str = "Audit Correction"


class FxRateUpsertRequest(BaseModel):
    rate_date: str
    base_currency: str
    spot_rate: float
    buy_rate: Optional[float] = None
    sell_rate: Optional[float] = None


class FxConvertRequest(BaseModel):
    effective_date: str
    from_account_code: str = "1011"
    to_account_code: str = "1010"
    from_amount_native: float = 10000.0
    execution_rate_to_usd: float = 1.1050
    narration: str = "Nostro FX Spot Conversion to USD Operating Bank"


class Ias21RevalRequest(BaseModel):
    as_of_date: str
    commit_voucher: bool = False
    auto_reverse_next_day: bool = False
    next_period_date: Optional[str] = None


class PostProposalToLedgerRequest(BaseModel):
    tx_id: str
    effective_date: str
    customer_name: str
    explanation_summary: str
    journal_entries: List[Dict[str, Any]]


class BrokerTradesIngestRequest(BaseModel):
    csv_content: str


# --- Internal Remittance Pipeline ---

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

    tax_audits = {}
    for prop in proposals:
        tds_deds = [d for d in prop.deductions if d.deduction_type == "TAX_WITHHOLDING_TDS"]
        if tds_deds and req.tax_corridor and req.tax_service_category:
            tds_total = sum((d.amount for d in tds_deds), Decimal("0.00"))
            audit = evaluate_withholding_compliance(
                corridor_code=req.tax_corridor,
                service_category=req.tax_service_category,
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


# --- UI Entrypoints (React + @utkristi/ui Vite SPA Bundle) ---

def _serve_spa(status_code: int = 200) -> HTMLResponse:
    dist_index = DIST_DIR / "index.html"
    if dist_index.exists():
        return HTMLResponse(dist_index.read_text(encoding="utf-8"), status_code=status_code)
    return HTMLResponse("<h1>Frontend not built</h1><p>Run <code>npm run build</code> first.</p>", status_code=503)


# --- Authentication API (PBKDF2-SHA256 + HttpOnly Session Cookie) ---

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    company_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
def api_register(req: RegisterRequest, response: Response, request: Request) -> dict:
    try:
        res = register_user(
            email=req.email,
            password=req.password,
            full_name=req.full_name,
            company_name=req.company_name,
            owner_only=True,
            db_path=DEFAULT_DB_PATH,
        )
        response.set_cookie(key="cl_session", value=res["token"], httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=86400 * 7)
        return {"status": "registered", "user": res["user"]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/login")
def api_login(req: LoginRequest, response: Response, request: Request) -> dict:
    try:
        res = authenticate_user(email=req.email, password=req.password, db_path=DEFAULT_DB_PATH)
        response.set_cookie(key="cl_session", value=res["token"], httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=86400 * 7)
        return {"status": "authenticated", "user": res["user"]}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response) -> dict:
    revoke_session(request.cookies.get("cl_session"), db_path=DEFAULT_DB_PATH)
    response.delete_cookie("cl_session")
    return {"status": "logged_out"}


@app.get("/api/auth/me")
def api_me(request: Request) -> dict:
    user = get_session_user(request.cookies.get("cl_session"), db_path=DEFAULT_DB_PATH)
    return {"authenticated": user is not None, "user": user, "registration_available": registration_available(DEFAULT_DB_PATH)}


# --- Module 1: Core Multi-Currency General Ledger & Statements ---

class CreateAccountRequest(BaseModel):
    code: str
    name: str
    account_type: str
    parent_group: str
    currency_code: str = "USD"
    is_monetary: bool = True
    enable_bill_by_bill: bool = False


@app.get("/api/core/overview")
def get_core_overview() -> dict:
    t0 = time.perf_counter()
    vch_page = list_vouchers_paginated(page=1, page_size=25, db_path=DEFAULT_DB_PATH)
    res = {
        "statements": generate_financial_statements(DEFAULT_DB_PATH),
        "cashflow_and_aging": generate_cashflow_and_aging(db_path=DEFAULT_DB_PATH),
        "accounts": list_accounts(DEFAULT_DB_PATH),
        "vouchers": vch_page["items"],
        "total_vouchers_count": vch_page["total_count"],
        "fx_rates": list_fx_rates(DEFAULT_DB_PATH),
        "investments": get_investment_tax_summary(DEFAULT_DB_PATH),
        "bulk_jobs": list_bulk_jobs(),
    }
    res["query_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return res


@app.post("/api/core/accounts")
def create_account_endpoint(req: CreateAccountRequest) -> dict:
    try:
        return create_gl_account(
            code=req.code,
            name=req.name,
            account_type=req.account_type,
            parent_group=req.parent_group,
            currency_code=req.currency_code,
            is_monetary=req.is_monetary,
            enable_bill_by_bill=req.enable_bill_by_bill,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/core/accounts/{account_code}/ledger")
def account_ledger_drilldown(account_code: str, limit: int = 200) -> dict:
    try:
        return get_account_ledger_statement(account_code, limit=limit, db_path=DEFAULT_DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/core/cashflow-and-aging")
def cashflow_and_aging_endpoint(as_of_date: str) -> dict:
    return generate_cashflow_and_aging(as_of_date=as_of_date, db_path=DEFAULT_DB_PATH)


@app.get("/api/core/vouchers")
def get_paginated_vouchers(
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    voucher_type: str = "ALL",
) -> dict:
    t0 = time.perf_counter()
    res = list_vouchers_paginated(
        page=page,
        page_size=page_size,
        search=search,
        voucher_type=voucher_type,
        db_path=DEFAULT_DB_PATH,
    )
    res["query_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return res


# --- Module 5: GB-Scale Constant-Memory Streaming Ingestion & Stress Telemetry ---

@app.post("/api/bulk/upload-stream")
async def upload_gb_stream(request: Request, filename: str = "statement.csv") -> dict:
    """
    Zero-RAM-overhead raw HTTP stream ingestion endpoint capable of handling multi-GB
    ISO 20022 XML or Bank CSV files without loading the payload into memory.
    """
    safe_name = pathlib.Path(filename).name or "upload.csv"
    suffix = pathlib.Path(safe_name).suffix or ".csv"
    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix="clearledger_stream_", suffix=suffix)
    tmp_path = pathlib.Path(tmp_path_str)
    bytes_written = 0
    try:
        with open(tmp_fd, "wb") as f:
            async for chunk in request.stream():
                if chunk:
                    f.write(chunk)
                    bytes_written += len(chunk)
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Stream write error: {exc}") from exc

    job_id = launch_streaming_upload_job(tmp_path, safe_name, db_path=DEFAULT_DB_PATH)
    return {"job_id": job_id, "filename": safe_name, "bytes_received": bytes_written, "status": "RUNNING"}


@app.get("/api/bulk/jobs")
def get_all_bulk_jobs() -> dict:
    return {"jobs": list_bulk_jobs()}


@app.get("/api/bulk/jobs/{job_id}")
def get_single_bulk_job(job_id: str) -> dict:
    st = get_job_status(job_id)
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    return st


@app.post("/api/core/vouchers")
def create_core_voucher(req: CreateVoucherRequest) -> dict:
    try:
        inputs = [
            PostingInput(
                account_code=l.account_code,
                debit=Decimal(str(l.debit)),
                credit=Decimal(str(l.credit)),
                native_currency=l.native_currency,
                exchange_rate=Decimal(str(l.exchange_rate)) if l.exchange_rate is not None else None,
                bill_ref=l.bill_ref,
                party_name=l.party_name,
            )
            for l in req.lines
        ]
        return post_voucher(
            voucher_type=req.voucher_type,
            effective_date=req.effective_date,
            narration=req.narration,
            lines=inputs,
            source_ref=req.source_ref,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/core/vouchers/{voucher_id}/reverse")
def reverse_core_voucher(voucher_id: str, req: ReverseVoucherRequest) -> dict:
    try:
        return reverse_voucher(
            voucher_id=voucher_id,
            reversal_date=req.reversal_date,
            reason=req.reason,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Module 2: FX Rate Matrix, Contra Conversion & IAS 21 Revaluation ---

@app.post("/api/fx/rate")
def add_fx_rate(req: FxRateUpsertRequest) -> dict:
    return upsert_fx_rate(
        rate_date=req.rate_date,
        base_currency=req.base_currency,
        spot_rate=Decimal(str(req.spot_rate)),
        buy_rate=Decimal(str(req.buy_rate)) if req.buy_rate is not None else None,
        sell_rate=Decimal(str(req.sell_rate)) if req.sell_rate is not None else None,
        db_path=DEFAULT_DB_PATH,
    )


@app.post("/api/fx/convert")
def convert_fx_nostro(req: FxConvertRequest) -> dict:
    try:
        return post_fx_conversion_contra(
            effective_date=req.effective_date,
            from_account_code=req.from_account_code,
            to_account_code=req.to_account_code,
            from_amount_native=Decimal(str(req.from_amount_native)),
            execution_rate_to_usd=Decimal(str(req.execution_rate_to_usd)),
            narration=req.narration,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fx/revalue")
def revalue_ias21(req: Ias21RevalRequest) -> dict:
    try:
        return run_ias21_revaluation(
            as_of_date=req.as_of_date,
            commit_voucher=req.commit_voucher,
            auto_reverse_next_day=req.auto_reverse_next_day,
            next_period_date=req.next_period_date,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Module 3: Remittance & Short-Pay Reconciliation Hub (ClearRemit -> Core GL) ---

@app.post("/api/reconcile")
def reconcile_custom(req: ReconcileRequest) -> dict:
    return _run_pipeline(req)


@app.post("/api/remittance/post-to-ledger")
def post_remittance_proposal_to_ledger(req: PostProposalToLedgerRequest) -> dict:
    """Commits a reconciled ISO 20022 / MT940 / BAI2 proposal directly into the persistent Core GL."""
    try:
        lines = [
            PostingInput(
                account_code=str(je["account_code"]),
                debit=Decimal(str(je.get("debit", 0))),
                credit=Decimal(str(je.get("credit", 0))),
                native_currency="USD",
                exchange_rate=Decimal("1.000000"),
                bill_ref=je.get("invoice_ref"),
                party_name=req.customer_name,
            )
            for je in req.journal_entries
        ]
        return post_voucher(
            voucher_type="RECEIPT",
            effective_date=req.effective_date,
            narration=f"Remittance Auto-Post [{req.tx_id}] {req.customer_name}: {req.explanation_summary}",
            source_ref=f"REMIT-{req.tx_id}",
            lines=lines,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tax-audit")
def run_tax_audit(req: TaxAuditRequest) -> dict:
    res = evaluate_withholding_compliance(
        corridor_code=req.corridor_code,
        service_category=req.service_category,
        gross_amount=Decimal(str(req.gross_amount)),
        withheld_amount=Decimal(str(req.withheld_amount)),
    )
    return res.to_dict()


# --- Module 4: Post-Trade Investment Tax-Lot Accounting ---

@app.post("/api/investments/ingest")
def ingest_broker_trades(req: BrokerTradesIngestRequest) -> dict:
    try:
        res = ingest_broker_trades_csv(req.csv_content, db_path=DEFAULT_DB_PATH)
        return {
            "ingestion": res,
            "investments": get_investment_tax_summary(DEFAULT_DB_PATH),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


PUBLIC_PAGES = json.loads((BASE_DIR / "frontend/public-routes.json").read_text(encoding="utf-8"))


@app.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
def serve_page(path: str) -> HTMLResponse:
    normalized = "/" + path.rstrip("/")
    if normalized.startswith(("/api/", "/assets/")) or normalized == "/api":
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_spa(200 if normalized in {"/", "/app", "/auth", *PUBLIC_PAGES} else 404)
