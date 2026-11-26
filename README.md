# ClearRemit

ClearRemit manages a double-entry ledger, bank reconciliation, FX, broker lots, and financial reporting in one workspace.

## Run locally

Install Python 3.12+ and Node.js 22.12+.

```sh
python -m pip install -r requirements.txt
npm ci
npm run build
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open the [home page](http://127.0.0.1:8000) and select **Open workspace**. On a fresh installation, set up the first account. The default chart of accounts is available immediately. Vouchers, imported records, and FX rates come from your own activity. See the [user documentation](http://127.0.0.1:8000/docs) and [interactive API reference](http://127.0.0.1:8000/api-reference).

For frontend development, run `npm run dev` alongside the API on port 8000.

## Workflows

- **Vouchers & daybook** posts balanced entries and records reversals.
- **Chart of accounts** defines accounts and opens the account ledger.
- **FX & revaluation** stores rates, posts conversions, and previews IAS 21 adjustments.
- **Remittance & tax** reconciles bank statements against an open invoice CSV. Attach credit memos and remittance text as needed. Review proposals, post USD receipts, or download ERP journals.
- **Investment tax lots** ingests settled broker trades and computes FIFO lot balances and gains.
- **Statements & aging** reports ledger balances, cash flow, and receivables.
- **Bank imports** posts receipts directly from ISO 20022 or CSV files. Use reconciliation when you need to review proposed allocations first.

## Storage and deployment

The default database is `clearledger.db`. Set `CLEARLEDGER_DB_PATH` to a file on a persistent volume before deploying a fresh installation. For an existing installation, back up and migrate the existing database before switching paths. Upgrading preserves posted ledger history, including any data created with earlier versions. The application revokes the built-in demo user's sessions and removes that user on startup.

The Docker image builds the frontend and runs FastAPI. The health check is `/api/health`. Configure TLS at the reverse proxy and complete initial account setup before exposing a new installation publicly. Each database is a single shared ledger.

## Tests

Install `requirements-dev.txt` and run `python -m unittest discover -s tests`. The `sample_data` directory contains fixtures for parser and reconciliation tests.
