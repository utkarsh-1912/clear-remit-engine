"""Native invoice register and customer self-service."""

import csv
import hashlib
import io
import json
import secrets
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints, model_validator

from platform_api import Currency, Name, Note, entity_access, require_role
from workspace import ReviewConflict, RunNotFound, _now


class CustomerInput(BaseModel):
    name: Name
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] = ""


class InvoiceLine(BaseModel):
    description: Name
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class InvoiceInput(BaseModel):
    customer_id: UUID
    number: Name
    currency: Currency
    issued_on: date
    due_on: date
    lines: list[InvoiceLine] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.due_on < self.issued_on:
            raise ValueError("Due date must be on or after the issue date.")
        return self


class PortalRequest(BaseModel):
    invoice_id: UUID
    kind: Literal["remittance", "dispute", "promise_to_pay"]
    detail: Note


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _invoices(db, entity_id, customer_id=None):
    scope = " AND i.customer_id = ?" if customer_id is not None else ""
    args = (entity_id, customer_id) if customer_id is not None else (entity_id,)
    rows = db.execute("""
        SELECT i.*, c.name AS customer_name FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id
        WHERE i.entity_id = ?
    """ + scope + " ORDER BY i.issued_on DESC, i.number", args).fetchall()
    claims = db.execute("""
        SELECT p.invoice_id, p.currency, p.customer_id, p.amount, b.status
        FROM posting_claims p JOIN export_batches b ON b.id = p.batch_id
        WHERE p.entity_id = ? AND b.status IN ('prepared', 'confirmed')
    """, (entity_id,))
    posted = {}
    reserved = {}
    for claim in claims:
        key = (claim["invoice_id"], claim["currency"], claim["customer_id"])
        target = posted if claim["status"] == "confirmed" else reserved
        target[key] = target.get(key, Decimal("0")) + Decimal(claim["amount"])
    result = []
    for row in rows:
        key = (row["number"].upper(), row["currency"], row["customer_id"])
        total = Decimal(row["total"])
        applied = posted.get(key, Decimal("0"))
        result.append({**dict(row), "lines": json.loads(row["lines"]), "applied": str(applied),
                       "balance": str(max(total - applied, Decimal("0"))),
                       "reserved": str(reserved.get(key, Decimal("0")))})
    return result


def registered_ledger(workspace, entity_id):
    with workspace.connect() as db:
        rows = _invoices(db, entity_id)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["invoice_id", "customer_id", "customer_name", "currency", "issue_date", "due_date",
                     "gross_amount", "open_amount"])
    for row in rows:
        if row["status"] == "issued":
            writer.writerow([row[key] for key in ("number", "customer_id", "customer_name", "currency",
                                                 "issued_on", "due_on", "total")] +
                            [str(max(Decimal(row["balance"]) - Decimal(row["reserved"]), Decimal("0")))])
    return stream.getvalue()


def register_receivables(app):
    @app.get("/api/entities/{entity_id}/receivables")
    def register(entity_id: str, request: Request):
        entity_access(request, entity_id)
        with app.state.workspace.connect() as db:
            customers = [dict(row) for row in db.execute(
                "SELECT id, name, email, portal_digest IS NOT NULL AS portal_enabled FROM ar_customers WHERE entity_id = ? ORDER BY name",
                (entity_id,),
            )]
            return {"customers": customers, "invoices": _invoices(db, entity_id)}

    @app.post("/api/entities/{entity_id}/customers", status_code=201)
    def customer(entity_id: str, req: CustomerInput, request: Request):
        require_role(request, "admin", "analyst")
        entity_access(request, entity_id)
        customer_id = str(uuid4())
        workspace = app.state.workspace
        with workspace.connect() as db:
            db.execute("INSERT INTO ar_customers (id, entity_id, name, email) VALUES (?, ?, ?, ?)",
                       (customer_id, entity_id, req.name, req.email))
            workspace._event(db, entity_id, customer_id, "customer.created", request.state.operator["username"], {"name": req.name})
        return {"id": customer_id}

    @app.post("/api/entities/{entity_id}/invoices", status_code=201)
    def invoice(entity_id: str, req: InvoiceInput, request: Request):
        require_role(request, "admin", "analyst")
        entity_access(request, entity_id)
        invoice_id = str(uuid4())
        workspace = app.state.workspace
        lines = [{**line.model_dump(mode="json"),
                  "amount": str((line.quantity * line.unit_price).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))}
                 for line in req.lines]
        total = sum(Decimal(line["amount"]) for line in lines)
        if total <= 0 or total >= Decimal("1e13"):
            raise HTTPException(422, "Invoice total must be positive and within the supported ledger limit.")
        with workspace.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM ar_customers WHERE entity_id = ? AND id = ?", (entity_id, str(req.customer_id))).fetchone():
                raise RunNotFound(req.customer_id)
            number = req.number.upper()
            if db.execute("SELECT 1 FROM ar_invoices WHERE entity_id = ? AND number = ?", (entity_id, number)).fetchone():
                raise ReviewConflict("This invoice number is already in use.")
            db.execute("INSERT INTO ar_invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')",
                       (invoice_id, entity_id, str(req.customer_id), number, req.currency,
                        req.issued_on.isoformat(), req.due_on.isoformat(), json.dumps(lines), str(total)))
            workspace._event(db, entity_id, invoice_id, "invoice.drafted", request.state.operator["username"], {"number": number})
        return {"id": invoice_id}

    @app.post("/api/entities/{entity_id}/invoices/{invoice_id}/{action}")
    def invoice_state(entity_id: str, invoice_id: UUID, action: Literal["issue", "void"], request: Request):
        require_role(request, "admin", "analyst")
        entity_access(request, entity_id)
        workspace = app.state.workspace
        with workspace.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ar_invoices WHERE id = ? AND entity_id = ?", (str(invoice_id), entity_id)).fetchone()
            if row is None:
                raise RunNotFound(invoice_id)
            state = {"issue": "issued", "void": "void"}[action]
            if row["status"] != "draft":
                raise ReviewConflict("Only draft invoices can be issued or voided.")
            if action == "issue":
                workspace._open_period(db, entity_id, row["issued_on"])
            db.execute("UPDATE ar_invoices SET status = ? WHERE id = ?", (state, str(invoice_id)))
            workspace._event(db, entity_id, str(invoice_id), "invoice." + state, request.state.operator["username"], {})
        return {"status": state}

    @app.post("/api/entities/{entity_id}/customers/{customer_id}/portal/{action}")
    def portal_access(entity_id: str, customer_id: UUID, action: Literal["rotate", "revoke"], request: Request):
        require_role(request, "admin")
        entity_access(request, entity_id)
        workspace = app.state.workspace
        token = secrets.token_urlsafe(32) if action == "rotate" else None
        with workspace.connect() as db:
            changed = db.execute("UPDATE ar_customers SET portal_digest = ? WHERE id = ? AND entity_id = ?",
                                 (_digest(token) if token else None, str(customer_id), entity_id))
            if not changed.rowcount:
                raise RunNotFound(customer_id)
            workspace._event(db, entity_id, str(customer_id), "portal." + action, request.state.operator["username"], {})
        return {"path": f"/portal#{token}" if token else None}

    def portal_customer(db, request):
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not 40 <= len(token) <= 100:
            raise HTTPException(401, "This customer link is invalid or has been revoked.")
        row = db.execute("SELECT id, entity_id, name FROM ar_customers WHERE portal_digest = ?", (_digest(token),)).fetchone()
        if row is None:
            raise HTTPException(401, "This customer link is invalid or has been revoked.")
        return row

    @app.get("/api/portal")
    def portal(request: Request):
        with app.state.workspace.connect() as db:
            customer = portal_customer(db, request)
            invoices = [row for row in _invoices(db, customer["entity_id"], customer["id"]) if row["status"] == "issued"]
            requests = [dict(row) for row in db.execute("""
                SELECT r.*, i.number, c.status FROM portal_requests r JOIN ar_invoices i ON i.id = r.invoice_id
                JOIN cases c ON c.id = r.id
                WHERE i.customer_id = ? ORDER BY r.created_at DESC
            """, (customer["id"],))]
            return {"customer": customer["name"], "invoices": invoices, "requests": requests}

    @app.post("/api/portal/requests", status_code=201)
    def submit(req: PortalRequest, request: Request):
        workspace = app.state.workspace
        with workspace.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            customer = portal_customer(db, request)
            invoice = db.execute("SELECT * FROM ar_invoices WHERE id = ? AND customer_id = ? AND status = 'issued'",
                                 (str(req.invoice_id), customer["id"])).fetchone()
            if invoice is None:
                raise RunNotFound(req.invoice_id)
            case_id = str(uuid4())
            db.execute("INSERT INTO portal_requests VALUES (?, ?, ?, ?, ?)",
                       (case_id, str(req.invoice_id), req.kind, req.detail, _now()))
            db.execute("""INSERT INTO cases VALUES (?, ?, NULL, NULL, ?, ?, ?, 'open', '', '', ?, 0)""",
                       (case_id, customer["entity_id"], customer["id"],
                        f"{invoice['number']} · {customer['name']}", req.kind, req.detail))
            workspace._event(db, customer["entity_id"], case_id, "portal.submitted",
                             "customer:" + customer["id"], {"invoice": invoice["number"], "kind": req.kind})
        return {"id": case_id}
