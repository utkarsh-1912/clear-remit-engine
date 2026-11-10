import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app import app


def inputs():
    return {
        "submission_id": str(uuid4()),
        "name": "July collections",
        "statement_content": (
            "tx_id,booking_date,payer_name,amount,currency,remittance_info\n"
            "BANK-20,2025-07-22,Unrecognized payer,42.10,EUR,AC-20\n"
            "BANK-21,2025-07-23,Acme,50.00,USD,INV-21"
        ),
        "invoices_csv": (
            "invoice_id,customer_id,customer_name,gross_amount,open_amount,currency\n"
            "AC-20,ACME,Acme,42.10,42.10,EUR\n"
            "INV-21,ACME,Acme,50.00,50.00,EUR"
        ),
        "accounts": {"1010": {"code": "1005", "name": "Collection bank"}},
        "netsuite_subsidiary": "EU Operations",
    }


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict("os.environ", {
            "CLEARREMIT_DB_PATH": str(Path(directory) / "runs.db"),
            "CLEARREMIT_REQUIRE_AUTH": "1",
            "CLEARREMIT_USERNAME": "reviewer",
            "CLEARREMIT_PASSWORD": "workspace-test",
        }))
        self.auth = ("reviewer", "workspace-test")

    def test_review_gate_and_persistence(self):
        req = inputs()
        route = f"/api/runs/{req['submission_id']}"
        download = f"{route}/exports/netsuite?currency=EUR"
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.get("/api/runs").status_code, 401)
            self.assertEqual(client.get("/api/runs", auth=self.auth).json(), [])
            create = client.post("/api/runs", json=req, auth=self.auth)
            self.assertEqual(create.status_code, 201, create.text)
            result = create.json()["result"]
            self.assertEqual(result["summary"]["unmatched_count"], 1)
            self.assertEqual(set(result["summary"]["totals_by_currency"]), {"EUR", "USD"})
            self.assertEqual(result["tax_audits"], {})
            self.assertEqual(client.get(download, auth=self.auth).status_code, 409)
            retry = client.post("/api/runs", json=req, auth=self.auth)
            self.assertEqual(retry.json()["id"], create.json()["id"])
            self.assertEqual(client.post("/api/runs", json={**req, "name": "Different"}, auth=self.auth).status_code, 409)
            review = {"tx_id": "BANK-20", "decision": "approved", "version": 0}
            self.assertEqual(client.post(f"{route}/reviews", json={**review, "tx_id": "BANK-21"}, auth=self.auth).status_code, 409)
            self.assertEqual(client.post(f"{route}/reviews", json=review, auth=self.auth).status_code, 200)
            self.assertEqual(client.post(f"{route}/reviews", json=review, auth=self.auth).status_code, 409)
            self.assertEqual(len(client.get("/api/runs", auth=self.auth).json()), 1)
        with TestClient(app) as client:
            response = client.get(download, auth=self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertIn("2025-07-22,EU Operations,EUR,1005,Collection bank", response.text)
            self.assertNotIn("BANK-21", response.text)
            run = client.get(route, auth=self.auth).json()
            self.assertEqual(run["review_history"][0]["actor"], "reviewer")
            rejected = {"tx_id": "BANK-20", "decision": "rejected", "note": "Reopened", "version": 1}
            self.assertEqual(client.post(f"{route}/reviews", json=rejected, auth=self.auth).status_code, 200)
            self.assertEqual(client.get(download, auth=self.auth).status_code, 409)

    def test_rejects_invalid_inputs_and_tax_context(self):
        req = inputs()
        with TestClient(app) as client:
            invalid_date = {**req, "statement_content": req["statement_content"].replace("2025-07-22", "")}
            self.assertEqual(client.post("/api/runs", json=invalid_date, auth=self.auth).status_code, 400)
            self.assertEqual(client.post("/api/runs", json={
                **invalid_date, "fallback_booking_date": "2025-07-21",
            }, auth=self.auth).status_code, 201)
            audit = client.post("/api/tax-audit", auth=self.auth, json={
                "corridor_code": "IN-US", "service_category": "UNSUPPORTED",
                "gross_amount": "100", "withheld_amount": "10",
            })
            self.assertEqual(audit.status_code, 422)
