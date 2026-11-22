"""Integration checks for client isolation and the full cash application lifecycle."""

import json
import hashlib
import hmac
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from app import app


class TestPlatform(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict("os.environ", {
            "CLEARREMIT_DB_PATH": str(Path(directory) / "platform.db"),
            "CLEARREMIT_USERNAME": "admin", "CLEARREMIT_PASSWORD": "admin-test",
            "CLEARREMIT_USERS_JSON": json.dumps([
                {"username": "analyst", "password": "analyst-test", "role": "analyst", "organizations": ["*"]},
                {"username": "approver", "password": "approver-test", "role": "approver", "organizations": ["*"]},
                {"username": "restricted", "password": "read-test", "role": "auditor", "organizations": ["default"]},
            ]),
        }))
        self.client = self.enterContext(TestClient(app))
        self.admin = ("admin", "admin-test")
        self.analyst = ("analyst", "analyst-test")
        self.approver = ("approver", "approver-test")
        self.reader = ("restricted", "read-test")

    def send(self, path, data, auth=None, expected=200):
        response = self.client.post(path, json=data, auth=auth or self.admin)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def entity(self):
        org = self.send("/api/organizations", {"name": "Practice", "mode": "accounting_firm"}, expected=201)
        return self.send("/api/entities", {"name": "Client A", "organization_id": org["id"], "currency": "EUR"}, expected=201)

    def request(self, entity_id):
        return {
            "submission_id": str(uuid4()), "name": "November cash", "entity_id": entity_id,
            "statement_content": "tx_id,booking_date,payer_name,amount,currency\nPAY-80,2026-11-22,Unknown buyer,80.00,EUR",
            "invoices_csv": "invoice_id,customer_id,customer_name,gross_amount,open_amount,currency,due_date\nAC-100,C-1,Customer A,100,100,EUR,2026-11-01",
        }

    def test_allocate_review_export_receipt_close(self):
        entity = self.entity()
        entity_id = entity["id"]
        policy = self.send(f"/api/entities/{entity_id}/settings", {
            "version": 0, "separate_approval": True,
            "policy": {"statement_content": "", "invoices_csv": "", "allowed_discount_pcts": ["2"]},
        })
        self.assertEqual(policy["version"], 1)
        run = self.send("/api/runs", self.request(entity_id), self.analyst, expected=201)
        path = f"/api/runs/{run['id']}"
        self.assertEqual(run["result"]["proposals"][0]["status"], "UNMATCHED_SUSPENSE")
        self.send(path + "/reviews", {"tx_id": "PAY-80", "decision": "approved", "version": 0}, self.analyst, expected=403)
        run = self.send(path + "/resolve", {
            "tx_id": "PAY-80", "revision": 0, "note": "Advice confirms partial payment",
            "allocations": [{"invoice_id": "AC-100", "amount": "80"}],
        }, self.analyst)
        self.assertEqual(run["revision"], 1)
        self.send(path + "/resolve", {
            "tx_id": "PAY-80", "revision": 0, "note": "Stale edit",
            "allocations": [{"invoice_id": "AC-100", "amount": "80"}],
        }, self.analyst, expected=409)
        self.send(path + "/reviews", {"tx_id": "PAY-80", "decision": "approved", "note": "Checked advice", "version": 1}, self.approver)
        export = {"submission_id": str(uuid4()), "format": "netsuite", "currency": "EUR"}
        batch = self.send(path + "/export-batches", export, self.approver, expected=201)
        self.assertEqual(self.send(path + "/export-batches", export, self.approver, expected=201)["id"], batch["id"])
        download = self.client.get(f"/api/export-batches/{batch['id']}/download", auth=self.approver)
        self.assertEqual(download.status_code, 200)
        self.assertIn("2026-11-22,,EUR", download.text)
        self.send(path + "/reviews", {"tx_id": "PAY-80", "decision": "rejected", "note": "Locked", "version": 2}, self.approver, expected=409)
        self.send(f"/api/entities/{entity_id}/close", {"period": "2026-11", "note": "Close"}, self.approver, expected=409)
        self.send(f"/api/export-batches/{batch['id']}/receipt", {"version": 0, "status": "confirmed", "receipt": "NS-JE-900"}, self.approver)
        operations = self.client.get(f"/api/entities/{entity_id}/operations", auth=self.admin).json()
        self.assertEqual(operations["invoices"][0]["remaining_amount"], 20)
        case = operations["cases"][0]
        self.send(f"/api/entities/{entity_id}/cases/{case['id']}", {
            "version": 0, "status": "resolved", "assignee": "analyst", "note": "Partial allocation accepted",
        }, self.analyst)
        self.send(f"/api/entities/{entity_id}/close", {"period": "2026-11", "note": "ERP receipt verified"}, self.approver)
        self.send("/api/runs", self.request(entity_id), self.analyst, expected=409)
        self.assertIn("period.closed", self.client.get(f"/api/entities/{entity_id}/audit.csv", auth=self.approver).text)

    def test_organization_isolation_and_read_only_role(self):
        entity = self.entity()
        run = self.send("/api/runs", self.request(entity["id"]), self.analyst, expected=201)
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}", auth=self.reader).status_code, 404)
        self.assertEqual(self.client.get(f"/api/runs?entity_id={entity['id']}", auth=self.reader).status_code, 404)
        self.send("/api/runs", self.request("default"), self.reader, expected=403)
        visible = self.client.get("/api/entities", auth=self.reader).json()
        self.assertEqual([row["id"] for row in visible], ["default"])

    def test_invoice_portal_to_confirmed_receipt(self):
        entity = self.entity()
        base = f"/api/entities/{entity['id']}"
        customer = self.send(base + "/customers", {"name": "Buyer"}, self.analyst, expected=201)
        other = self.send(base + "/customers", {"name": "Other buyer"}, self.analyst, expected=201)
        invoice_input = {
            "customer_id": customer["id"], "number": "AR-700", "currency": "EUR",
            "issued_on": "2026-11-01", "due_on": "2026-11-21",
            "lines": [{"description": "Services", "quantity": "2", "unit_price": "50"}],
        }
        invoice = self.send(base + "/invoices", invoice_input, self.analyst, expected=201)
        other_invoice = self.send(base + "/invoices", {
            **invoice_input, "customer_id": other["id"], "number": "AR-701",
        }, self.analyst, expected=201)
        link_endpoint = f"{base}/customers/{customer['id']}/portal"
        token = self.send(link_endpoint + "/rotate", {})["path"].split("#")[1]
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/portal", headers=headers).json()["invoices"], [])
        for item in (invoice, other_invoice):
            self.send(f"{base}/invoices/{item['id']}/issue", {}, self.analyst)
        data = self.client.get("/api/portal", headers=headers).json()
        self.assertEqual([row["number"] for row in data["invoices"]], ["AR-700"])
        payload = {"invoice_id": other_invoice["id"], "kind": "remittance", "detail": "Bank reference 80"}
        self.assertEqual(self.client.post("/api/portal/requests", headers=headers, json=payload).status_code, 404)
        response = self.client.post("/api/portal/requests", headers=headers, json={**payload, "invoice_id": invoice["id"]})
        self.assertEqual(response.status_code, 201, response.text)
        operations = self.client.get(base + "/operations", auth=self.analyst).json()
        self.assertIn(response.json()["id"], {case["id"] for case in operations["cases"]})
        self.assertEqual(self.client.get(base + "/receivables", headers=headers).status_code, 401)
        for amount, payment_id, balance in ((80, "PAY-80", "20.00"), (20, "PAY-20", "0.00")):
            req = self.request(entity["id"])
            req.update({"use_registered_ledger": True, "invoices_csv": "", "statement_content": (
                "tx_id,booking_date,payer_name,amount,currency,remittance_info\n"
                f"{payment_id},2026-11-22,Buyer,{amount},EUR,AR-700"
            )})
            run = self.send("/api/runs", req, self.analyst, expected=201)
            path = f"/api/runs/{run['id']}"
            version = 0
            if run["result"]["proposals"][0]["match_method"] == "UNMATCHED":
                run = self.send(path + "/resolve", {"tx_id": payment_id, "revision": 0, "note": "Applied received cash",
                                                   "allocations": [{"invoice_id": "AR-700", "amount": amount}]}, self.analyst)
                version = run["reviews"][payment_id]["version"]
            self.send(path + "/reviews", {"tx_id": payment_id, "decision": "approved", "note": "Verified", "version": version}, self.approver)
            batch = self.send(path + "/export-batches", {
                "submission_id": str(uuid4()), "format": "netsuite", "currency": "EUR",
            }, self.approver, expected=201)
            self.send(f"/api/export-batches/{batch['id']}/receipt", {
                "version": 0, "status": "confirmed", "receipt": payment_id,
            }, self.approver)
            snapshot = self.client.get("/api/portal", headers=headers).json()
            self.assertEqual(snapshot["invoices"][0]["balance"], balance)
        self.send(link_endpoint + "/revoke", {})
        self.assertEqual(self.client.get("/api/portal", headers=headers).status_code, 401)

    def test_duplicate_export_rejection_and_recovery(self):
        req = self.request("default")
        req["statement_content"] = req["statement_content"].replace("Unknown buyer,80.00", "Customer A,100.00")
        run = self.send("/api/runs", req, expected=201)
        route = f"/api/runs/{run['id']}"
        self.send(route + "/reviews", {"tx_id": "PAY-80", "decision": "approved", "version": 0})
        batch = self.send(route + "/export-batches", {"submission_id": str(uuid4()), "format": "xero", "currency": "EUR"}, expected=201)
        req["submission_id"] = str(uuid4())
        duplicate = self.send("/api/runs", req, expected=201)
        duplicate_route = f"/api/runs/{duplicate['id']}"
        self.send(duplicate_route + "/reviews", {"tx_id": "PAY-80", "decision": "approved", "version": 0})
        self.send(duplicate_route + "/export-batches", {"submission_id": str(uuid4()), "format": "xero", "currency": "EUR"}, expected=409)
        self.send(f"/api/export-batches/{batch['id']}/receipt", {"version": 0, "status": "rejected", "receipt": "ERP validation failed"})
        self.send(duplicate_route + "/export-batches", {"submission_id": str(uuid4()), "format": "xero", "currency": "EUR"}, expected=201)

    def test_connectors_are_scoped_and_retryable(self):
        entity_id = self.entity()["id"]
        bank_key, erp_key = "bank-test-" * 4, "erp-test-" * 4
        stripe_key = "whsec_test_" * 4
        self.addCleanup(setattr, app.state, "connectors", app.state.connectors)
        app.state.connectors = {
            "default": {"bank": bank_key, "erp": erp_key, "stripe": stripe_key, "remittance": "remit-test-" * 4},
            entity_id: {"erp": erp_key},
        }
        req = self.request("default")
        req["statement_content"] = req["statement_content"].replace("Unknown buyer,80.00", "Customer A,100.00")
        bank = "/api/connector-hooks/default/bank"
        self.assertEqual(self.client.post(bank, json=req).status_code, 401)
        headers = {"Authorization": f"Bearer {bank_key}"}
        created = self.client.post(bank, json=req, headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.client.post(bank, json=req, headers=headers).json()["id"], created.json()["id"])
        remit = "/api/connector-hooks/default/remittance"
        headers = {"Authorization": "Bearer " + "remit-test-" * 4}
        payload = {"external_id": "mail-700", "customer_id": "C-1", "detail": "Remittance for PAY-80"}
        received = self.client.post(remit, json=payload, headers=headers)
        self.assertEqual(received.status_code, 201, received.text)
        self.assertEqual(self.client.post(remit, json=payload, headers=headers).json(), received.json())
        self.assertEqual(self.client.post(remit, json={**payload, "detail": "Changed"}, headers=headers).status_code, 409)
        route = f"/api/runs/{created.json()['id']}"
        self.send(route + "/reviews", {"tx_id": "PAY-80", "decision": "approved", "version": 0})
        batch = self.send(route + "/export-batches", {
            "submission_id": str(uuid4()), "format": "xero", "currency": "EUR",
        }, expected=201)
        headers = {"Authorization": f"Bearer {erp_key}"}
        erp = "/api/connector-hooks/default/erp"
        self.assertEqual(self.client.get(erp, headers=headers).json()[0]["id"], batch["id"])
        self.assertIn("PAY-80", self.client.get(f"{erp}/{batch['id']}", headers=headers).text)
        self.assertEqual(self.client.get(f"/api/connector-hooks/{entity_id}/erp/{batch['id']}", headers=headers).status_code, 404)
        receipt = {"version": 0, "status": "confirmed", "receipt": "ERP-700"}
        for _ in range(2):
            result = self.client.post(f"{erp}/{batch['id']}/receipt", headers=headers, json=receipt)
            self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get(erp, headers=headers).json(), [])

        customer = self.send("/api/entities/default/customers", {"name": "Buyer"}, expected=201)
        invoice = self.send("/api/entities/default/invoices", {
            "customer_id": customer["id"], "number": "AR-800", "currency": "EUR",
            "issued_on": "2026-11-01", "due_on": "2026-11-21",
            "lines": [{"description": "Services", "quantity": "1", "unit_price": "100"}],
        }, expected=201)
        self.send(f"/api/entities/default/invoices/{invoice['id']}/issue", {})
        event = json.dumps({"type": "payment_intent.succeeded", "data": {"object": {
            "id": "pi_example", "amount_received": 10000, "currency": "eur",
            "metadata": {"clearremit_invoice_id": invoice["id"]},
        }}}).encode()
        stripe = "/api/connector-hooks/default/stripe"
        self.assertEqual(self.client.post(stripe, content=event).status_code, 400)
        timestamp = str(int(time.time()))
        digest = hmac.new(stripe_key.encode(), timestamp.encode() + b"." + event, hashlib.sha256).hexdigest()
        headers = {"Stripe-Signature": f"t={timestamp},v1={digest}"}
        accepted = self.client.post(stripe, headers=headers, content=event)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(self.client.post(stripe, headers=headers, content=event).json(), accepted.json())
        register = self.client.get("/api/entities/default/receivables", auth=self.admin).json()
        self.assertEqual(register["invoices"][0]["balance"], "100.00")

    def test_smtp_delivery_reuses_attempt_id(self):
        base = "/api/entities/default"
        customer = self.send(base + "/customers", {"name": "Buyer", "email": "buyer@example.invalid"}, expected=201)
        invoice = self.send(base + "/invoices", {
            "customer_id": customer["id"], "number": "INV-SMTP", "currency": "EUR",
            "issued_on": "2026-11-01", "due_on": "2026-11-21",
            "lines": [{"description": "Services", "quantity": "1", "unit_price": "100"}],
        }, expected=201)
        self.send(f"{base}/invoices/{invoice['id']}/issue", {})
        endpoint = f"{base}/invoices/{invoice['id']}/deliveries/{uuid4()}"
        with patch.dict("os.environ", {"CLEARREMIT_SMTP_HOST": "smtp.example.invalid",
                                       "CLEARREMIT_SMTP_FROM": "billing@example.invalid"}):
            with patch("integrations._send_invoice") as send:
                self.assertEqual(self.send(endpoint, {}, expected=201)["status"], "accepted")
                self.assertEqual(self.send(endpoint, {}, expected=201)["status"], "accepted")
                send.assert_called_once()
                self.assertEqual(str(send.call_args.args[0]["To"]), "buyer@example.invalid")

    def test_sso_identity_requires_trusted_proxy_key(self):
        proxy_key = "proxy-test-" * 4
        self.addCleanup(setattr, app.state, "sso_proxy_key", app.state.sso_proxy_key)
        self.addCleanup(setattr, app.state, "users", app.state.users)
        app.state.sso_proxy_key = proxy_key
        app.state.users = [{"username": "federated-operator", "sso_subject": "provider-user-7",
                            "role": "auditor", "organizations": ["default"]}]
        headers = {"X-ClearRemit-Identity": "provider-user-7"}
        self.assertEqual(self.client.get("/api/session", headers=headers).status_code, 401)
        headers["X-ClearRemit-Proxy-Key"] = proxy_key
        session = self.client.get("/api/session", headers=headers).json()
        self.assertEqual(session["username"], "federated-operator")
        self.assertEqual(self.client.post("/api/runs", headers=headers, json=self.request("default")).status_code, 403)
