"""Organization, operations and controlled ERP handoff API."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


def require_role(request, *roles):
    if request.state.operator["role"] not in roles:
        raise HTTPException(403, "Your role does not allow this action.")


def entity_access(request, entity_id):
    entity = next((e for e in request.app.state.workspace.entities() if e["id"] == entity_id), None)
    if entity is None or not can_access_entity(request, entity):
        raise HTTPException(404, "Entity not found.")
    return entity


def can_access_entity(request, entity):
    operator = request.state.operator
    organizations = operator["organizations"]
    entities = operator.get("entities", ["*"])
    return ("*" in organizations or entity["organization_id"] in organizations) and (
        "*" in entities or entity["id"] in entities
    )


def run_access(request, run_id):
    run = request.app.state.workspace.get_run(run_id)
    entity_access(request, run["entity_id"])
    return run


def batch_access(request, batch_id):
    batch = request.app.state.workspace.export_snapshot(batch_id)
    entity_access(request, batch["entity_id"])
    return batch


class OrganizationRequest(BaseModel):
    name: Name
    mode: Literal["finance", "accounting_firm", "enterprise"]


class EntityRequest(BaseModel):
    name: Name
    organization_id: str
    currency: Currency


class CaseUpdate(BaseModel):
    version: int = Field(ge=0)
    status: Literal["open", "investigating", "waiting_customer", "resolved"]
    assignee: Short = ""
    due_date: date | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class CollectionRequest(BaseModel):
    customer_id: Name
    title: Name
    due_date: date | None = None
    note: Note


class Allocation(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=512)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class ResolveRequest(BaseModel):
    tx_id: str = Field(min_length=1, max_length=512)
    revision: int = Field(ge=0)
    allocations: list[Allocation] = Field(min_length=1, max_length=100)
    note: Note


class ExportRequest(BaseModel):
    submission_id: UUID
    format: Literal["quickbooks", "xero", "netsuite", "tally"]
    currency: Currency


class ReceiptRequest(BaseModel):
    version: int = Field(ge=0)
    status: Literal["confirmed", "rejected"]
    receipt: Note


class CloseRequest(BaseModel):
    period: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    note: Note


def build_manual_proposal(original, invoices, allocations, accounts):
    total = sum((item["amount"] for item in allocations), Decimal("0"))
    cash = Decimal(str(original["deposit_amount"]))
    if total > cash:
        raise HTTPException(409, "Allocations exceed the deposit. Allocate received cash and track any claim in the case queue.")
    if len({item["invoice_id"].upper() for item in allocations}) != len(allocations):
        raise HTTPException(409, "Select each invoice only once.")
    customer = invoices[allocations[0]["invoice_id"].upper()]

    def line(code, name, debit, credit, memo, invoice_ref=None):
        account = accounts.get(code, {"code": code, "name": name})
        return {"line_number": 0, "account_code": account["code"], "account_name": account["name"],
                "debit": float(debit), "credit": float(credit), "memo": memo,
                "entity_name": customer["customer_name"], "invoice_ref": invoice_ref}

    entries = [line("1010", "Operating Bank Cash", cash, 0, "Manual payment allocation")]
    for item in allocations:
        entries.append(line("1200", "Accounts Receivable - Trade", 0, item["amount"],
                            "Apply received cash", invoices[item["invoice_id"].upper()]["invoice_id"]))
    if cash > total:
        entries.append(line("2190", "Unapplied Customer Overpayment Credit", 0, cash - total,
                            "Unapplied customer balance"))
    for index, entry in enumerate(entries, 1):
        entry["line_number"] = index
    return {
        **original, "status": "ACTION_REQUIRED_SHORT_PAY", "match_method": "MANUAL_ALLOCATION",
        "confidence_score": 0, "matched_customer_id": customer["customer_id"],
        "matched_customer_name": customer["customer_name"], "total_gross_invoices": float(total),
        "total_deductions": 0.0, "residual_unexplained": 0.0, "deductions": [],
        "allocations": [{
            "invoice_id": invoices[item["invoice_id"].upper()]["invoice_id"],
            "gross_amount": float(item["amount"]), "discount_applied": 0, "tds_withheld": 0,
            "short_pay_or_memo": 0, "net_settled": float(item["amount"]),
        } for item in allocations],
        "journal_entries": entries, "dispute_notice_draft": None,
        "explanation_summary": "Manually allocated received cash. Approval is required before export.",
    }


def register_routes(app):
    from app import EXPORTS, ReconcileRequest, _export

    class SettingsRequest(BaseModel):
        version: int = Field(ge=0)
        separate_approval: bool = False
        policy: ReconcileRequest

    @app.get("/api/session")
    def session(request: Request):
        return request.state.operator

    @app.get("/api/entities")
    def entities(request: Request):
        return [entity for entity in app.state.workspace.entities()
                if can_access_entity(request, entity)]

    @app.get("/api/organizations")
    def organizations(request: Request):
        memberships = request.state.operator["organizations"]
        return [org for org in app.state.workspace.organizations()
                if "*" in memberships or org["id"] in memberships]

    @app.post("/api/organizations", status_code=201)
    def create_organization(req: OrganizationRequest, request: Request):
        require_role(request, "admin")
        if "*" not in request.state.operator["organizations"]:
            raise HTTPException(403, "A platform administrator must create organizations.")
        return app.state.workspace.create_organization(req.name, req.mode, request.state.operator["username"])

    @app.post("/api/entities", status_code=201)
    def create_entity(req: EntityRequest, request: Request):
        require_role(request, "admin")
        memberships = request.state.operator["organizations"]
        if "*" not in memberships and req.organization_id not in memberships:
            raise HTTPException(404, "Organization not found.")
        return app.state.workspace.create_entity(req.organization_id, req.name, req.currency,
                                                 request.state.operator["username"])

    @app.get("/api/entities/{entity_id}/operations")
    def operations(entity_id: str, request: Request):
        entity_access(request, entity_id)
        return app.state.workspace.operations(entity_id)

    @app.post("/api/entities/{entity_id}/settings")
    def settings(entity_id: str, req: SettingsRequest, request: Request):
        require_role(request, "admin")
        entity_access(request, entity_id)
        policy = req.policy.model_dump(mode="json", exclude={
            "statement_content", "invoices_csv", "credit_memos_csv", "remittance_emails_text",
        })
        settings = {"policy": policy, "separate_approval": req.separate_approval}
        return app.state.workspace.save_settings(entity_id, req.version, settings, request.state.operator["username"])

    @app.post("/api/entities/{entity_id}/cases/{case_id}")
    def update_case(entity_id: str, case_id: UUID, req: CaseUpdate, request: Request):
        require_role(request, "admin", "analyst", "approver")
        entity_access(request, entity_id)
        changes = req.model_dump(mode="json", exclude={"version"})
        changes["due_date"] = changes["due_date"] or ""
        return app.state.workspace.update_case(entity_id, str(case_id), req.version, changes,
                                              request.state.operator["username"])

    @app.post("/api/entities/{entity_id}/collections", status_code=201)
    def create_collection(entity_id: str, req: CollectionRequest, request: Request):
        require_role(request, "admin", "analyst", "approver")
        entity_access(request, entity_id)
        operations = app.state.workspace.operations(entity_id)
        if req.customer_id not in {invoice["customer_id"] for invoice in operations["invoices"]}:
            raise HTTPException(404, "Customer not found in this entity's ledger.")
        return app.state.workspace.create_collection(entity_id, req.customer_id, req.title,
                                                    req.due_date.isoformat() if req.due_date else "", req.note,
                                                    request.state.operator["username"])

    @app.post("/api/runs/{run_id}/resolve")
    def resolve(run_id: UUID, req: ResolveRequest, request: Request):
        require_role(request, "admin", "analyst")
        run = run_access(request, str(run_id))
        return app.state.workspace.resolve(
            str(run_id), req.tx_id, req.revision, [item.model_dump() for item in req.allocations],
            req.note, request.state.operator["username"],
            lambda original, invoices, allocations: build_manual_proposal(original, invoices, allocations,
                                                                          run["settings"].get("accounts", {})),
        )

    @app.post("/api/runs/{run_id}/export-batches", status_code=201)
    def prepare_export(run_id: UUID, req: ExportRequest, request: Request):
        require_role(request, "admin", "approver")
        run_access(request, str(run_id))
        return app.state.workspace.prepare_export(str(run_id), req.format, req.currency,
                                                 request.state.operator["username"], str(req.submission_id))

    @app.get("/api/export-batches/{batch_id}/download")
    def download_batch(batch_id: UUID, request: Request):
        from integrations import export_response

        require_role(request, "admin", "approver", "auditor")
        batch = batch_access(request, str(batch_id))
        return export_response(batch, _export, EXPORTS)

    @app.post("/api/export-batches/{batch_id}/receipt")
    def receipt(batch_id: UUID, req: ReceiptRequest, request: Request):
        require_role(request, "admin", "approver")
        batch_access(request, str(batch_id))
        return app.state.workspace.confirm_export(str(batch_id), req.version, req.status, req.receipt,
                                                 request.state.operator["username"])

    @app.post("/api/entities/{entity_id}/close")
    def close(entity_id: str, req: CloseRequest, request: Request):
        require_role(request, "admin", "approver")
        entity_access(request, entity_id)
        return app.state.workspace.close_period(entity_id, req.period, req.note, request.state.operator["username"])

    @app.get("/api/entities/{entity_id}/audit.csv")
    def audit_csv(entity_id: str, request: Request):
        entity_access(request, entity_id)
        import csv
        import io
        from engine.exporters import _csv_cell
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["Recorded", "Actor", "Action", "Subject", "Detail"])
        with app.state.workspace.connect() as db:
            for row in db.execute("SELECT * FROM events WHERE entity_id = ? ORDER BY id", (entity_id,)):
                writer.writerow([_csv_cell(str(row[key])) for key in ("created_at", "actor", "action", "subject", "detail")])
        return PlainTextResponse(stream.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="clearremit-audit.csv"',
        })
