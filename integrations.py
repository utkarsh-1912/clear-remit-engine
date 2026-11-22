"""Entity-scoped integration endpoints for bank, ERP, remittance, Stripe and SMTP."""

import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
from decimal import Decimal
from email.errors import MessageDefect, MessageError
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from engine.exporters import ExportJournal
from engine.models import JournalEntryLine
from platform_api import Name, Note, ReceiptRequest, entity_access, require_role
from workspace import ReviewConflict, RunNotFound, _now


def load_connectors():
    connectors = json.loads(os.getenv("CLEARREMIT_CONNECTORS_JSON", "{}"))
    if not isinstance(connectors, dict):
        raise RuntimeError("CLEARREMIT_CONNECTORS_JSON must be an object keyed by entity ID.")
    for config in connectors.values():
        if not isinstance(config, dict) or any(not isinstance(secret, str) or len(secret) < 24
                                               for secret in config.values()):
            raise RuntimeError("Each connector secret must be a string at least 24 characters long.")
    return connectors


def _secret(request, entity_id, kind):
    secret = request.app.state.connectors.get(entity_id, {}).get(kind)
    if not secret:
        raise RunNotFound(entity_id)
    return secret


def _authenticate(request, entity_id, kind):
    expected = _secret(request, entity_id, kind)
    supplied = request.headers.get("authorization", "").encode()
    if not secrets.compare_digest(supplied, ("Bearer " + expected).encode()):
        raise HTTPException(401, "Connector credentials are invalid.")


def _decode(model, data):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


async def _read_body(request, limit):
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > limit:
            raise HTTPException(413, "Connector payload is too large.")
        payload.extend(chunk)
    return bytes(payload)


class Remittance(BaseModel):
    external_id: Name
    customer_id: Name
    detail: Note


def _case_event(workspace, entity_id, source, external_id, customer_id, title, detail):
    case_id = str(uuid5(NAMESPACE_URL, json.dumps([entity_id, source, external_id])))
    encoded = json.dumps([customer_id, title, detail], sort_keys=True)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    with workspace.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("""
            SELECT fingerprint FROM integration_events WHERE entity_id = ? AND source = ? AND external_id = ?
        """, (entity_id, source, external_id)).fetchone()
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise ReviewConflict("The provider event ID was already used with different data.")
            return {"id": case_id}
        customer = db.execute("""
            SELECT 1 FROM ar_customers WHERE id = ? AND entity_id = ?
            UNION ALL
            SELECT 1 FROM runs r, json_each(r.result, '$.invoices') i
            WHERE r.entity_id = ? AND json_extract(i.value, '$.customer_id') = ?
            LIMIT 1
        """, (customer_id, entity_id, entity_id, customer_id)).fetchone()
        if not customer:
            raise RunNotFound(customer_id)
        db.execute("INSERT INTO cases VALUES (?, ?, NULL, NULL, ?, ?, 'remittance', 'open', '', '', ?, 0)",
                   (case_id, entity_id, customer_id, title, detail))
        db.execute("INSERT INTO integration_events VALUES (?, ?, ?, ?, ?, ?)",
                   (entity_id, source, external_id, fingerprint, case_id, _now()))
        workspace._event(db, entity_id, case_id, "integration." + source, "connector:" + source,
                         {"external_id": external_id})
    return {"id": case_id}


def _stripe_event(payload, signature, secret):
    fields = [part.strip().partition("=") for part in signature.split(",")]
    timestamps = [value for key, _, value in fields if key == "t"]
    if len(timestamps) != 1 or not timestamps[0].isascii() or not timestamps[0].isdigit() or len(timestamps[0]) > 12:
        raise HTTPException(400, "Stripe signature is invalid.")
    timestamp = timestamps[0]
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    if abs(time.time() - int(timestamp)) > 300 or not any(
        hmac.compare_digest(value.encode(), expected.encode()) for key, _, value in fields if key == "v1"
    ):
        raise HTTPException(400, "Stripe signature is invalid or expired.")
    try:
        event = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, "Stripe event must be JSON.") from exc
    if not isinstance(event, dict):
        raise HTTPException(400, "Stripe event must be an object.")
    return event


class StripePayment(BaseModel):
    id: Name
    amount_received: int
    currency: str
    metadata: dict[str, str]


def _record_stripe(workspace, entity_id, event):
    if event.get("type") != "payment_intent.succeeded":
        return {"status": "ignored"}
    data = event.get("data")
    payment = _decode(StripePayment, data.get("object") if isinstance(data, dict) else None)
    invoice_id = payment.metadata.get("clearremit_invoice_id")
    if not invoice_id:
        return {"status": "ignored"}
    with workspace.connect() as db:
        invoice = db.execute("""
            SELECT number, customer_id, currency FROM ar_invoices
            WHERE entity_id = ? AND id = ? AND status = 'issued'
        """, (entity_id, invoice_id)).fetchone()
    if not invoice or payment.currency.upper() != invoice["currency"] or payment.amount_received <= 0:
        raise HTTPException(422, "Stripe payment does not match an issued invoice and currency.")
    detail = (
        f"Stripe PaymentIntent {payment.id} received {payment.amount_received} minor units in {invoice['currency']}. "
        "Verify the related bank settlement before allocating cash."
    )
    return _case_event(workspace, entity_id, "stripe", payment.id, invoice["customer_id"],
                       f"{invoice['number']} · Stripe payment", detail)


def _smtp_settings():
    host = os.getenv("CLEARREMIT_SMTP_HOST")
    sender = os.getenv("CLEARREMIT_SMTP_FROM")
    if not host or not sender:
        raise HTTPException(503, "Configure the SMTP host and sender on the deployment.")
    try:
        return host, int(os.getenv("CLEARREMIT_SMTP_PORT", "465")), Address(addr_spec=sender)
    except (ValueError, TypeError, MessageDefect, MessageError) as exc:
        raise HTTPException(503, "The SMTP provider configuration is invalid.") from exc


def _send_invoice(message, host, port):
    with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as server:
        username = os.getenv("CLEARREMIT_SMTP_USERNAME")
        if username:
            server.login(username, os.environ["CLEARREMIT_SMTP_PASSWORD"])
        server.send_message(message)


def register_integrations(app, run_model, submit_run, render_export, formats):
    @app.get("/api/entities/{entity_id}/integrations")
    def status(entity_id: str, request: Request):
        entity_access(request, entity_id)
        config = app.state.connectors.get(entity_id, {})
        with app.state.workspace.connect() as db:
            deliveries = [dict(row) for row in db.execute(
                "SELECT * FROM invoice_deliveries WHERE entity_id = ? ORDER BY created_at DESC LIMIT 100", (entity_id,)
            )]
            events = [dict(row) for row in db.execute("""
                SELECT source, external_id, result, created_at FROM integration_events
                WHERE entity_id = ? ORDER BY created_at DESC LIMIT 100
            """, (entity_id,))]
        return {"connectors": {kind: bool(config.get(kind)) for kind in ("bank", "remittance", "erp", "stripe")},
                "smtp": bool(os.getenv("CLEARREMIT_SMTP_HOST") and os.getenv("CLEARREMIT_SMTP_FROM")),
                "sso_proxy": bool(app.state.sso_proxy_key),
                "deliveries": deliveries, "events": events}

    @app.post("/api/connector-hooks/{entity_id}/bank", status_code=201)
    async def bank(entity_id: str, request: Request):
        _authenticate(request, entity_id, "bank")
        try:
            payload = json.loads(await _read_body(request, 16_000_000))
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(400, "Send a JSON reconciliation request.") from exc
        if not isinstance(payload, dict) or payload.get("entity_id", entity_id) != entity_id:
            raise HTTPException(422, "The import must target this entity.")
        req = _decode(run_model, {**payload, "entity_id": entity_id})
        result = await run_in_threadpool(submit_run, req, "connector:bank")
        return {"id": result["id"], "summary": result["result"]["summary"]}

    @app.post("/api/connector-hooks/{entity_id}/remittance", status_code=201)
    def remittance(entity_id: str, req: Remittance, request: Request):
        _authenticate(request, entity_id, "remittance")
        return _case_event(app.state.workspace, entity_id, "remittance", req.external_id,
                           str(req.customer_id), "Remittance · " + req.external_id, req.detail)

    @app.get("/api/connector-hooks/{entity_id}/erp")
    def erp_queue(entity_id: str, request: Request):
        _authenticate(request, entity_id, "erp")
        workspace = app.state.workspace
        with workspace.connect() as db:
            return [workspace._batch(row) for row in db.execute("""
                SELECT * FROM export_batches WHERE entity_id = ? AND status = 'prepared' ORDER BY created_at, id LIMIT 100
            """, (entity_id,))]

    @app.get("/api/connector-hooks/{entity_id}/erp/{batch_id}")
    def erp_download(entity_id: str, batch_id: UUID, request: Request):
        _authenticate(request, entity_id, "erp")
        batch = app.state.workspace.export_snapshot(str(batch_id), entity_id=entity_id)
        return export_response(batch, render_export, formats)

    @app.post("/api/connector-hooks/{entity_id}/erp/{batch_id}/receipt")
    def erp_receipt(entity_id: str, batch_id: UUID, req: ReceiptRequest, request: Request):
        _authenticate(request, entity_id, "erp")
        return app.state.workspace.confirm_export(str(batch_id), req.version, req.status, req.receipt, "connector:erp",
                                                  entity_id=entity_id, retry=True)

    @app.post("/api/connector-hooks/{entity_id}/stripe")
    async def stripe(entity_id: str, request: Request):
        secret = _secret(request, entity_id, "stripe")
        payload = await _read_body(request, 1_000_000)
        event = _stripe_event(payload, request.headers.get("stripe-signature", ""), secret)
        return await run_in_threadpool(_record_stripe, app.state.workspace, entity_id, event)

    @app.post("/api/entities/{entity_id}/invoices/{invoice_id}/deliveries/{delivery_id}", status_code=201)
    def deliver(entity_id: str, invoice_id: UUID, delivery_id: UUID, request: Request):
        require_role(request, "admin", "analyst")
        entity = entity_access(request, entity_id)
        host, port, sender = _smtp_settings()
        workspace = app.state.workspace
        with workspace.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM invoice_deliveries WHERE id = ?", (str(delivery_id),)).fetchone()
            if existing:
                if (existing["entity_id"], existing["invoice_id"]) != (entity_id, str(invoice_id)):
                    raise ReviewConflict("This delivery ID belongs to a different invoice.")
                return dict(existing)
            invoice = db.execute("""
                SELECT i.*, c.name AS customer, c.email FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id
                WHERE i.entity_id = ? AND i.id = ? AND i.status = 'issued'
            """, (entity_id, str(invoice_id))).fetchone()
            if invoice is None:
                raise RunNotFound(invoice_id)
            try:
                recipient = Address(addr_spec=invoice["email"])
                if not recipient.domain:
                    raise ValueError("Missing mail domain")
            except (ValueError, TypeError, MessageDefect, MessageError) as exc:
                raise HTTPException(422, "This customer needs a valid billing email.") from exc
            message = EmailMessage()
            message["From"] = sender
            message["To"] = recipient
            message["Subject"] = "Invoice " + " ".join(invoice["number"].split())
            message["Message-ID"] = f"<{delivery_id}@{sender.domain}>"
            lines = [f"{line['description']} — {line['quantity']} × {invoice['currency']} {line['unit_price']}"
                     for line in json.loads(invoice["lines"])]
            message.set_content("\n".join([
                entity["name"], f"Invoice {invoice['number']} for {invoice['customer']}",
                f"Issued {invoice['issued_on']} · Due {invoice['due_on']}", "", *lines, "",
                f"Invoice total {invoice['currency']} {invoice['total']}",
            ]))
            db.execute("INSERT INTO invoice_deliveries VALUES (?, ?, ?, ?, 'sending', ?)",
                       (str(delivery_id), entity_id, str(invoice_id), str(recipient), _now()))
        try:
            _send_invoice(message, host, port)
            outcome = "accepted"
        except (OSError, smtplib.SMTPException, KeyError):
            outcome = "unverified"
        with workspace.connect() as db:
            db.execute("UPDATE invoice_deliveries SET status = ? WHERE id = ?", (outcome, str(delivery_id)))
            workspace._event(db, entity_id, str(invoice_id), "invoice.delivery." + outcome,
                             request.state.operator["username"], {"delivery_id": str(delivery_id)})
        return {"id": str(delivery_id), "status": outcome}


def export_response(batch, render_export, formats):
    journals = []
    for proposal in batch["snapshot"]["proposals"]:
        lines = [JournalEntryLine(**{**item, "debit": Decimal(str(item["debit"])),
                                    "credit": Decimal(str(item["credit"]))}) for item in proposal["journal_entries"]]
        journals.append(ExportJournal(proposal["tx_id"], proposal["booking_date"], proposal["currency"],
                                      proposal["matched_customer_name"], proposal["explanation_summary"], lines))
    _, _, media_type, extension = formats[batch["format"]]
    filename = f'{batch["id"]}-{batch["currency"]}.{extension}'
    return PlainTextResponse(render_export(batch["format"], journals, batch["snapshot"]["settings"]),
                             media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
