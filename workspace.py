"""Durable reconciliation runs and reviewer decisions for a single workspace."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


class RunNotFound(Exception):
    pass


class ReviewConflict(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    settings TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_created_at ON runs (created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS reviews (
                    run_id TEXT NOT NULL REFERENCES runs (id),
                    tx_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY (run_id, tx_id, version)
                );
                CREATE TABLE IF NOT EXISTS organizations (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, mode TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
                    name TEXT NOT NULL, currency TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
                    run_id TEXT REFERENCES runs(id), tx_id TEXT, customer_id TEXT NOT NULL,
                    title TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                    assignee TEXT NOT NULL, due_date TEXT NOT NULL, note TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (run_id, tx_id, kind)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL,
                    subject TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
                    created_at TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS export_batches (
                    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), format TEXT NOT NULL, currency TEXT NOT NULL,
                    status TEXT NOT NULL, receipt TEXT NOT NULL, created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL, snapshot TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS posting_claims (
                    batch_id TEXT NOT NULL REFERENCES export_batches(id),
                    entity_id TEXT NOT NULL, run_id TEXT NOT NULL, tx_id TEXT NOT NULL,
                    payment_key TEXT NOT NULL, currency TEXT NOT NULL, invoice_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL, amount TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS closed_periods (
                    entity_id TEXT NOT NULL REFERENCES entities(id), period TEXT NOT NULL,
                    actor TEXT NOT NULL, created_at TEXT NOT NULL, note TEXT NOT NULL,
                    PRIMARY KEY (entity_id, period)
                );
                CREATE TABLE IF NOT EXISTS memo_claims (
                    batch_id TEXT NOT NULL REFERENCES export_batches(id),
                    entity_id TEXT NOT NULL, currency TEXT NOT NULL, memo_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ar_customers (
                    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
                    name TEXT NOT NULL, email TEXT NOT NULL, portal_digest TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS ar_invoices (
                    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
                    customer_id TEXT NOT NULL REFERENCES ar_customers(id),
                    number TEXT NOT NULL, currency TEXT NOT NULL, issued_on TEXT NOT NULL,
                    due_on TEXT NOT NULL, lines TEXT NOT NULL, total TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft', UNIQUE(entity_id, number)
                );
                CREATE TABLE IF NOT EXISTS portal_requests (
                    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES ar_invoices(id),
                    kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS integration_events (
                    entity_id TEXT NOT NULL REFERENCES entities(id), source TEXT NOT NULL,
                    external_id TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY (entity_id, source, external_id)
                );
                CREATE TABLE IF NOT EXISTS invoice_deliveries (
                    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
                    invoice_id TEXT NOT NULL REFERENCES ar_invoices(id), recipient TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            if "entity_id" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN entity_id TEXT NOT NULL DEFAULT 'default'")
            db.execute("INSERT OR IGNORE INTO organizations VALUES ('default', 'My organization', 'finance')")
            db.execute("INSERT OR IGNORE INTO entities (id, organization_id, name, currency) VALUES ('default', 'default', 'Main entity', 'USD')")
            db.execute("CREATE INDEX IF NOT EXISTS runs_entity ON runs(entity_id, created_at)")
            # Existing runs gain exception queues during the same migration.
            for row in db.execute("SELECT id, entity_id, result FROM runs").fetchall():
                self._seed_cases(db, row["id"], row["entity_id"], json.loads(row["result"]))

    def list_runs(self, limit: int, offset: int, entity_id: str = "default") -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""
                SELECT id, name, created_at, created_by, summary FROM runs WHERE entity_id = ?
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """, (entity_id, limit, offset)).fetchall()
        return [{**dict(row), "summary": json.loads(row["summary"])} for row in rows]

    def _run(self, db, run_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return row

    def _detail(self, db, row: sqlite3.Row) -> dict:
        reviews = db.execute("""
            SELECT tx_id, decision, note, actor, created_at, version FROM reviews
            WHERE run_id = ? ORDER BY rowid
        """, (row["id"],)).fetchall()
        history = [dict(review) for review in reviews]
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "entity_id": row["entity_id"],
            "settings": json.loads(row["settings"]),
            "result": json.loads(row["result"]),
            "reviews": {review["tx_id"]: review for review in history},
            "review_history": history,
            "revision": self._revision(db, row["id"]),
            "batches": [self._batch(batch) for batch in db.execute(
                "SELECT * FROM export_batches WHERE run_id = ? ORDER BY created_at DESC", (row["id"],)
            )],
        }

    def get_run(self, run_id: str) -> dict:
        with self.connect() as db:
            return self._detail(db, self._run(db, run_id))

    def find_submission(self, run_id: str, fingerprint: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["fingerprint"] != fingerprint:
                raise ReviewConflict("This submission ID was already used for different inputs.")
            return self._detail(db, row)

    def save_run(self, run_id: str, name: str, actor: str, fingerprint: str, settings: dict, result: dict,
                 entity_id: str = "default") -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for tx in result["transactions"]:
                self._open_period(db, entity_id, tx["booking_date"])
            inserted = db.execute("""
                INSERT INTO runs (id, name, created_at, created_by, fingerprint, settings, summary, result, entity_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO NOTHING
            """, (run_id, name, _now(), actor, fingerprint, json.dumps(settings),
                  json.dumps(result["summary"]), json.dumps(result), entity_id))
            row = self._run(db, run_id)
            if row["fingerprint"] != fingerprint:
                raise ReviewConflict("This submission ID was already used for different inputs.")
            if inserted.rowcount:
                self._seed_cases(db, run_id, entity_id, result)
                self._event(db, entity_id, run_id, "run.imported", actor, {"name": name})
            return self._detail(db, row)

    def review(self, run_id: str, tx_id: str, decision: str, note: str, version: int, actor: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._run(db, run_id)
            proposal = next((p for p in json.loads(row["result"])["proposals"] if p["tx_id"] == tx_id), None)
            if proposal is None:
                raise RunNotFound(tx_id)
            self._open_period(db, row["entity_id"], proposal["booking_date"])
            self._editable(db, run_id, tx_id)
            if decision == "approved" and proposal["status"] == "UNMATCHED_SUSPENSE":
                raise ReviewConflict("Unmatched transactions must be resolved in a new run before export.")
            if not note and (decision == "rejected" or proposal["status"] != "AUTO_RECONCILED"):
                raise ReviewConflict("Add a review note for this decision.")
            current = db.execute("""
                SELECT COALESCE(MAX(version), 0) FROM reviews WHERE run_id = ? AND tx_id = ?
            """, (run_id, tx_id)).fetchone()[0]
            if version != current:
                raise ReviewConflict("Another review was saved. Reload the run before changing the decision.")
            db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (run_id, tx_id, decision, note, actor, _now(), current + 1))
            self._event(db, row["entity_id"], run_id, "journal." + decision, actor, {"tx_id": tx_id, "note": note})
            return self._detail(db, row)

    def _event(self, db, entity_id, subject, action, actor, detail):
        db.execute("INSERT INTO events (entity_id, subject, action, actor, created_at, detail) VALUES (?, ?, ?, ?, ?, ?)",
                   (entity_id, subject, action, actor, _now(), json.dumps(detail)))

    def _seed_cases(self, db, run_id, entity_id, result):
        for proposal in result["proposals"]:
            if proposal["status"] == "AUTO_RECONCILED":
                continue
            if db.execute("SELECT 1 FROM cases WHERE run_id = ? AND tx_id = ?", (run_id, proposal["tx_id"])).fetchone():
                continue
            kind = "unmatched" if proposal["status"] == "UNMATCHED_SUSPENSE" else "short_pay"
            db.execute("""
                INSERT OR IGNORE INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, 'open', '', '', '', 0)
            """, (str(uuid4()), entity_id, run_id, proposal["tx_id"], proposal["matched_customer_id"],
                  proposal["matched_customer_name"] + " · " + proposal["tx_id"], kind))

    def _revision(self, db, run_id):
        return db.execute("SELECT COUNT(*) FROM events WHERE subject = ? AND action = 'proposal.resolved'", (run_id,)).fetchone()[0]

    def _open_period(self, db, entity_id, booking_date):
        if db.execute("SELECT 1 FROM closed_periods WHERE entity_id = ? AND period = ?",
                      (entity_id, booking_date[:7])).fetchone():
            raise ReviewConflict("This accounting period is closed.")

    def _editable(self, db, run_id, tx_id):
        if db.execute("""
            SELECT 1 FROM posting_claims p JOIN export_batches b ON b.id = p.batch_id
            WHERE p.run_id = ? AND p.tx_id = ? AND b.status IN ('prepared', 'confirmed')
        """, (run_id, tx_id)).fetchone():
            raise ReviewConflict("This journal belongs to an active export batch. Reject that batch before making changes.")

    def organizations(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM organizations ORDER BY name")]

    def entities(self):
        with self.connect() as db:
            return [{**dict(row), "settings": json.loads(row["settings"])} for row in db.execute(
                "SELECT e.*, o.name AS organization_name, o.mode FROM entities e JOIN organizations o ON o.id = e.organization_id ORDER BY o.name, e.name"
            )]

    def create_organization(self, name, mode, actor):
        org_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO organizations VALUES (?, ?, ?)", (org_id, name, mode))
            self._event(db, "default", org_id, "organization.created", actor, {"name": name, "mode": mode})
        return {"id": org_id, "name": name, "mode": mode}

    def create_entity(self, organization_id, name, currency, actor):
        entity_id = str(uuid4())
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM organizations WHERE id = ?", (organization_id,)).fetchone():
                raise RunNotFound(organization_id)
            db.execute("INSERT INTO entities (id, organization_id, name, currency) VALUES (?, ?, ?, ?)",
                       (entity_id, organization_id, name, currency))
            self._event(db, entity_id, entity_id, "entity.created", actor, {"name": name})
        return next(entity for entity in self.entities() if entity["id"] == entity_id)

    def save_settings(self, entity_id, version, settings, actor):
        with self.connect() as db:
            updated = db.execute("UPDATE entities SET settings = ?, version = version + 1 WHERE id = ? AND version = ?",
                                 (json.dumps(settings), entity_id, version))
            if updated.rowcount != 1:
                raise ReviewConflict("Settings changed. Reload before saving.")
            self._event(db, entity_id, entity_id, "settings.updated", actor, settings)
        return next(entity for entity in self.entities() if entity["id"] == entity_id)

    def _batch(self, row):
        value = dict(row)
        snapshot = json.loads(value.pop("snapshot"))
        value["transaction_count"] = len(snapshot["proposals"])
        value["tx_ids"] = [p["tx_id"] for p in snapshot["proposals"]]
        return value

    def operations(self, entity_id):
        with self.connect() as db:
            db.execute("BEGIN")
            runs = [self._detail(db, row) for row in db.execute(
                "SELECT * FROM runs WHERE entity_id = ? ORDER BY created_at, id", (entity_id,)
            ).fetchall()]
            cases = [dict(row) for row in db.execute("SELECT * FROM cases WHERE entity_id = ? ORDER BY rowid DESC", (entity_id,))]
            batches = [self._batch(row) for row in db.execute(
                "SELECT * FROM export_batches WHERE entity_id = ? ORDER BY created_at DESC", (entity_id,)
            )]
            events = [{**dict(row), "detail": json.loads(row["detail"])} for row in db.execute(
                "SELECT * FROM events WHERE entity_id = ? ORDER BY id DESC LIMIT 500", (entity_id,)
            )]
            periods = [dict(row) for row in db.execute(
                "SELECT * FROM closed_periods WHERE entity_id = ? ORDER BY period DESC", (entity_id,)
            )]
            claims = db.execute("""
                SELECT p.*, b.status AS batch_status FROM posting_claims p JOIN export_batches b ON b.id = p.batch_id
                WHERE p.entity_id = ? AND b.status IN ('prepared', 'confirmed')
            """, (entity_id,)).fetchall()
            registered = db.execute("""
                SELECT i.*, c.name AS customer_name FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id
                WHERE i.entity_id = ? AND i.status = 'issued'
            """, (entity_id,)).fetchall()
        invoices = {}
        payments = []
        for run in runs:
            for inv in run["result"]["invoices"]:
                invoices[(inv["invoice_id"].upper(), inv["currency"])] = {**inv, "run_id": run["id"]}
            for p in run["result"]["proposals"]:
                payments.append({**p, "run_id": run["id"], "run_name": run["name"],
                                 "review": run["reviews"].get(p["tx_id"]), "created_at": run["created_at"]})
        for row in registered:
            key = (row["number"].upper(), row["currency"])
            invoices[key] = {
                **invoices.get(key, {}), "invoice_id": row["number"], "customer_id": row["customer_id"],
                "customer_name": row["customer_name"], "currency": row["currency"],
                "due_date": row["due_on"], "open_amount": float(Decimal(row["total"])),
                "opening_amount": row["total"], "registered": True,
            }
        totals = {}
        for claim in claims:
            key = (claim["invoice_id"].upper(), claim["currency"], claim["batch_status"])
            totals[key] = totals.get(key, Decimal("0")) + Decimal(claim["amount"])
        for key, inv in invoices.items():
            posted = totals.get((*key, "confirmed"), Decimal("0"))
            reserved = totals.get((*key, "prepared"), Decimal("0"))
            opening = Decimal(str(inv.get("opening_amount", inv["open_amount"])))
            inv["open_amount"] = float(opening)
            inv["reserved_amount"] = float(reserved + posted)
            inv["outstanding_amount"] = float(max(Decimal("0"), opening - posted))
            inv["remaining_amount"] = float(max(Decimal("0"), opening - posted - reserved))
        return {"runs_count": len(runs), "payments": payments, "invoices": list(invoices.values()),
                "cases": cases, "batches": batches, "events": events, "periods": periods}

    def update_case(self, entity_id, case_id, version, changes, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = db.execute("SELECT * FROM cases WHERE id = ? AND entity_id = ?", (case_id, entity_id)).fetchone()
            if case is None:
                raise RunNotFound(case_id)
            if case["version"] != version:
                raise ReviewConflict("This case changed. Reload before saving.")
            if changes["status"] == "resolved" and not changes["note"]:
                raise ReviewConflict("Add a resolution note before closing a case.")
            if changes["status"] == "resolved" and case["kind"] == "unmatched":
                run = self._run(db, case["run_id"])
                proposal = next(p for p in json.loads(run["result"])["proposals"] if p["tx_id"] == case["tx_id"])
                if proposal["status"] == "UNMATCHED_SUSPENSE":
                    raise ReviewConflict("Allocate this unmatched payment before closing its case.")
            db.execute("""
                UPDATE cases SET status = ?, assignee = ?, due_date = ?, note = ?, version = version + 1 WHERE id = ?
            """, (changes["status"], changes["assignee"], changes["due_date"], changes["note"], case_id))
            self._event(db, entity_id, case_id, "case.updated", actor, changes)
            return dict(db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone())

    def create_collection(self, entity_id, customer_id, title, due_date, note, actor):
        case_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO cases VALUES (?, ?, NULL, NULL, ?, ?, 'collection', 'open', ?, ?, ?, 0)",
                       (case_id, entity_id, customer_id, title, actor, due_date, note))
            self._event(db, entity_id, case_id, "collection.created", actor,
                        {"customer_id": customer_id, "title": title, "note": note, "due_date": due_date})
        return {"id": case_id}

    def resolve(self, run_id, tx_id, revision, allocations, note, actor, build_proposal):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._run(db, run_id)
            if revision != self._revision(db, run_id):
                raise ReviewConflict("The run changed. Reload before resolving this payment.")
            self._editable(db, run_id, tx_id)
            result = json.loads(row["result"])
            proposal = next((p for p in result["proposals"] if p["tx_id"] == tx_id), None)
            if proposal is None:
                raise RunNotFound(tx_id)
            self._open_period(db, row["entity_id"], proposal["booking_date"])
            other_used = {}
            for other in result["proposals"]:
                if other["tx_id"] != tx_id:
                    for item in other["allocations"]:
                        key = item["invoice_id"].upper()
                        other_used[key] = other_used.get(key, Decimal("0")) + Decimal(str(item["gross_amount"]))
            invoices = {i["invoice_id"].upper(): i for i in result["invoices"]}
            customers = set()
            for allocation in allocations:
                inv = invoices.get(allocation["invoice_id"].upper())
                if not inv or inv["currency"] != proposal["currency"]:
                    raise ReviewConflict("Choose an invoice from this run in the payment currency.")
                customers.add(inv["customer_id"])
                remaining = Decimal(str(inv["open_amount"])) - other_used.get(inv["invoice_id"].upper(), Decimal("0"))
                if allocation["amount"] > remaining:
                    raise ReviewConflict("An allocation exceeds the available invoice balance in this run.")
            if len(customers) != 1:
                raise ReviewConflict("Allocate the payment to invoices for one customer.")
            new_proposal = build_proposal(proposal, invoices, allocations)
            result["proposals"] = [new_proposal if p["tx_id"] == tx_id else p for p in result["proposals"]]
            result["tax_audits"].pop(tx_id, None)
            summary = result["summary"]
            for field, status in (("auto_reconciled_count", "AUTO_RECONCILED"),
                                  ("action_required_dispute_count", "ACTION_REQUIRED_SHORT_PAY"),
                                  ("unmatched_count", "UNMATCHED_SUSPENSE")):
                summary[field] = sum(p["status"] == status for p in result["proposals"])
            totals = summary["totals_by_currency"][proposal["currency"]]
            totals["total_gross_ar_cleared"] += new_proposal["total_gross_invoices"] - proposal["total_gross_invoices"]
            totals["total_deductions_resolved"] -= proposal["total_deductions"]
            totals["unauthorized_short_pay_disputes"] -= sum(d["amount"] for d in proposal["deductions"] if not d["is_authorized"])
            if len(summary["totals_by_currency"]) == 1:
                summary.update(totals)
            db.execute("UPDATE runs SET result = ?, summary = ? WHERE id = ?", (json.dumps(result), json.dumps(summary), run_id))
            current = db.execute("SELECT COALESCE(MAX(version), 0) FROM reviews WHERE run_id = ? AND tx_id = ?", (run_id, tx_id)).fetchone()[0]
            db.execute("INSERT INTO reviews VALUES (?, ?, 'rejected', ?, ?, ?, ?)",
                       (run_id, tx_id, "Re-review required after allocation. " + note, actor, _now(), current + 1))
            self._event(db, row["entity_id"], run_id, "proposal.resolved", actor,
                        {"tx_id": tx_id, "note": note, "previous": proposal, "proposal": new_proposal})
            return self._detail(db, self._run(db, run_id))

    def prepare_export(self, run_id, fmt, currency, actor, batch_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone()
            if existing:
                if (existing["run_id"], existing["format"], existing["currency"]) != (run_id, fmt, currency):
                    raise ReviewConflict("This batch ID was used for a different export.")
                return self._batch(existing)
            row = self._run(db, run_id)
            run = self._detail(db, row)
            proposals = [p for p in run["result"]["proposals"] if p["currency"] == currency
                         and run["reviews"].get(p["tx_id"], {}).get("decision") == "approved"]
            exported_ids = {claim["tx_id"] for claim in db.execute("""
                SELECT c.tx_id FROM posting_claims c JOIN export_batches b ON b.id = c.batch_id
                WHERE c.run_id = ? AND b.status IN ('prepared', 'confirmed')
            """, (run_id,))}
            proposals = [p for p in proposals if p["tx_id"] not in exported_ids]
            if not proposals:
                raise ReviewConflict("Approve a journal in this currency before preparing an export.")
            entity_id = row["entity_id"]
            invoices = {i["invoice_id"].upper(): i for i in run["result"]["invoices"]}
            txs = {t["tx_id"]: t for t in run["result"]["transactions"]}
            for p in proposals:
                self._open_period(db, entity_id, p["booking_date"])
                self._editable(db, run_id, p["tx_id"])
                if sum(Decimal(str(j["debit"])) - Decimal(str(j["credit"])) for j in p["journal_entries"]) != 0:
                    raise ReviewConflict("This journal is unbalanced.")
                tx = txs[p["tx_id"]]
                payment_key = json.dumps([tx["bank_reference"] or tx["tx_id"], tx["booking_date"],
                                          str(Decimal(str(tx["amount"])).quantize(Decimal(".01"))), currency])
                active = db.execute("""
                    SELECT c.* FROM posting_claims c JOIN export_batches b ON b.id = c.batch_id
                    WHERE c.entity_id = ? AND b.status IN ('prepared', 'confirmed')
                """, (entity_id,)).fetchall()
                if any(c["payment_key"] == payment_key for c in active):
                    raise ReviewConflict("This bank payment is already included in an active export.")
                for allocation in p["allocations"]:
                    invoice_id = allocation["invoice_id"].upper()
                    inv = invoices.get(invoice_id)
                    registered = db.execute("""
                        SELECT total, currency, customer_id, status FROM ar_invoices WHERE entity_id = ? AND number = ?
                    """, (entity_id, invoice_id)).fetchone()
                    if registered and (registered["status"] != "issued" or registered["currency"] != currency
                                       or registered["customer_id"] != p["matched_customer_id"]):
                        raise ReviewConflict("An allocation conflicts with the entity's registered invoice.")
                    opening = registered["total"] if registered else inv.get("opening_amount", inv["open_amount"]) if inv else 0
                    used = sum((Decimal(c["amount"]) for c in active if c["invoice_id"].upper() == invoice_id
                                and c["currency"] == currency), Decimal("0"))
                    if inv is None or used + Decimal(str(allocation["gross_amount"])) > Decimal(str(opening)):
                        raise ReviewConflict("This invoice is already reserved or posted in another export.")
                for deduction in p["deductions"]:
                    if deduction["deduction_type"] != "CREDIT_MEMO":
                        continue
                    memo_id = deduction.get("credit_memo_id")
                    if not memo_id:
                        raise ReviewConflict("Reconcile this older credit memo proposal again before export.")
                    if db.execute("""
                        SELECT 1 FROM memo_claims m JOIN export_batches b ON b.id = m.batch_id
                        WHERE m.entity_id = ? AND m.currency = ? AND m.memo_id = ?
                        AND b.status IN ('prepared', 'confirmed')
                    """, (entity_id, currency, memo_id.upper())).fetchone():
                        raise ReviewConflict("This credit memo is already reserved or posted.")
                # Insert the batch first to maintain foreign keys while claiming allocations.
                if not db.execute("SELECT 1 FROM export_batches WHERE id = ?", (batch_id,)).fetchone():
                    db.execute("INSERT INTO export_batches VALUES (?, ?, ?, ?, ?, 'prepared', '', ?, ?, ?, 0)",
                               (batch_id, entity_id, run_id, fmt, currency, _now(), actor,
                                json.dumps({"proposals": proposals, "settings": run["settings"]})))
                for allocation in p["allocations"]:
                    db.execute("INSERT INTO posting_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (batch_id, entity_id, run_id, p["tx_id"], payment_key, currency,
                                allocation["invoice_id"].upper(), p["matched_customer_id"], str(allocation["gross_amount"])))
                for deduction in p["deductions"]:
                    if deduction.get("credit_memo_id"):
                        db.execute("INSERT INTO memo_claims VALUES (?, ?, ?, ?)",
                                   (batch_id, entity_id, currency, deduction["credit_memo_id"].upper()))
            self._event(db, entity_id, batch_id, "export.prepared", actor, {"run_id": run_id, "format": fmt, "currency": currency})
            return self._batch(db.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone())

    def export_snapshot(self, batch_id, *, entity_id=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone()
            if row is None or (entity_id is not None and row["entity_id"] != entity_id):
                raise RunNotFound(batch_id)
            if row["status"] == "rejected":
                raise ReviewConflict("This export was rejected. Prepare a new batch.")
            return {**self._batch(row), "snapshot": json.loads(row["snapshot"])}

    def confirm_export(self, batch_id, version, status, receipt, actor, *, entity_id=None, retry=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone()
            if row is None or (entity_id is not None and row["entity_id"] != entity_id):
                raise RunNotFound(batch_id)
            if retry and row["version"] == version + 1 and row["status"] == status and row["receipt"] == receipt:
                return self._batch(row)
            if row["version"] != version or row["status"] != "prepared":
                raise ReviewConflict("This export changed or has already been acknowledged.")
            db.execute("UPDATE export_batches SET status = ?, receipt = ?, version = version + 1 WHERE id = ?",
                       (status, receipt, batch_id))
            self._event(db, row["entity_id"], batch_id, "export." + status, actor, {"receipt": receipt})
            return self._batch(db.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone())

    def close_period(self, entity_id, period, note, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT * FROM runs WHERE entity_id = ?", (entity_id,)).fetchall():
                run = self._detail(db, row)
                for p in run["result"]["proposals"]:
                    if p["booking_date"][:7] != period:
                        continue
                    confirmed = db.execute("""
                        SELECT 1 FROM posting_claims p JOIN export_batches b ON b.id = p.batch_id
                        WHERE p.run_id = ? AND p.tx_id = ? AND b.status = 'confirmed'
                    """, (run["id"], p["tx_id"])).fetchone()
                    if not confirmed:
                        raise ReviewConflict("Every payment in this period needs a confirmed ERP receipt before closing.")
            if db.execute("SELECT 1 FROM closed_periods WHERE entity_id = ? AND period = ?", (entity_id, period)).fetchone():
                raise ReviewConflict("This period is already closed.")
            unresolved = db.execute("""
                SELECT c.tx_id, r.result FROM cases c JOIN runs r ON r.id = c.run_id
                WHERE c.entity_id = ? AND c.status != 'resolved'
            """, (entity_id,)).fetchall()
            for case in unresolved:
                if any(p["tx_id"] == case["tx_id"] and p["booking_date"][:7] == period
                       for p in json.loads(case["result"])["proposals"]):
                    raise ReviewConflict("Resolve the period's payment cases before closing.")
            db.execute("INSERT INTO closed_periods VALUES (?, ?, ?, ?, ?)", (entity_id, period, actor, _now(), note))
            self._event(db, entity_id, period, "period.closed", actor, {"note": note})
        return {"period": period, "status": "closed"}
