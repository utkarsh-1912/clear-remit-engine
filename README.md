# ClearRemit

ClearRemit is a receivables workspace for importing bank statements, matching payments to open invoices, and reviewing proposed journals before exporting them to QuickBooks, Xero, NetSuite, or Tally Prime. The React frontend uses the published [@utkristi/ui](https://www.npmjs.com/package/@utkristi/ui) design system. FastAPI serves the built frontend and the reconciliation API from the same origin.

## Run locally

Requires Python 3.12 or later and Node.js 22.12 or later.

```powershell
python -m pip install -r requirements.txt
npm ci
npm run build
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open [the local workspace](http://127.0.0.1:8000). It starts empty. Use **Open sample** to inspect fixtures in a read-only view. For frontend development, run `npm run dev` alongside the API on port 8000.

## Import, review, and export

1. Create a run and upload a statement and open-invoice ledger. Supported inputs include ISO 20022 camt.053 and pacs.008, MT940, BAI2, and bank CSV. Optional files include credit memo CSV and plain-text remittance advice.
2. Set the fallback currency and booking date when these values are missing from the input. For Bank CSV, booking dates use `YYYY-MM-DD`. The engine matches invoices and credit memos in the payment currency and reports totals by currency.
3. Enter any additional discount, withholding, and wire-fee candidates for the batch. Set the chart of accounts and ERP fields under the run's settings. Treaty screening requires an explicit corridor and service selection. Its rates come from the reference table in the repository and are intended for review.
4. Review each transaction's invoice allocations, deductions, and proposed journal. Rejections and exception approvals require a note. Unmatched deposits stay in review until resolved in a new run. Each decision records its timestamp and operator.
5. Export approved journals by currency. The files use the source booking date and the run's account mapping. The export workflow generates files for manual import into the ERP.

### CSV inputs

Use UTF-8 files with a header row. Amounts use decimal notation with up to two fractional digits. Example fixtures live in [sample_data](sample_data).

| Input | Required columns | Optional columns |
| --- | --- | --- |
| Bank CSV | `amount`, `booking_date`, `currency` | `tx_id`, `payer_name`, `payment_rail`, `bank_reference`, `remittance_info` |
| Open invoices | `invoice_id`, `customer_id`, `customer_name`, `gross_amount`, `currency` | `open_amount` (defaults to gross), `issue_date`, `due_date`, `payment_terms`, `eligible_discount_pct`, `expected_tds_pct`, `po_number` |
| Credit memos | `memo_id`, `customer_id`, `amount`, `currency` | `customer_name`, `reason`, `related_invoice_id` |

Booking date and currency columns can be omitted when a fallback is supplied. Imports support up to 250 incoming transactions, 10,000 invoices and 5,000 credit memos per run. The browser accepts up to 2 MB per input file.

## Storage and deployment

| Setting | Purpose |
| --- | --- |
| `CLEARREMIT_DB_PATH` | SQLite file, defaulting to `data/workspace.sqlite3` |
| `CLEARREMIT_USERNAME` and `CLEARREMIT_PASSWORD` | HTTP Basic credentials for the workspace operator |
| `CLEARREMIT_REQUIRE_AUTH=1` | Refuse to start without both credentials |

The Render blueprint builds the Docker image, requires sign-in over HTTPS, and mounts a persistent disk for SQLite. It uses a paid Starter service to retain runs across deployments. Supply the credentials in the Render dashboard when configuring the service. The health endpoint is `/api/health`.

This implementation runs as a single workspace with one configured operator. SQLite stores parsed financial records, proposals, settings, and review history. Run review decisions apply to the selected run. Identity federation, separate preparer and approver roles, and cross-run ERP posting controls would require additional integration.

## Verification

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
npm ci
npm run build
```
