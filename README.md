# ClearRemit

ClearRemit supports organization and client setup, customer and invoice management, customer self-service, bank imports, cash application, exception and collection work queues, journal approval, controlled ERP export batches, receipt tracking, receivables aging, period close, and audit history. The React frontend uses the published [@utkristi/ui](https://www.npmjs.com/package/@utkristi/ui) design system. FastAPI serves the built frontend and the reconciliation API from the same origin.

## Run locally

Requires Python 3.12 or later and Node.js 22.12 or later.

```powershell
python -m pip install -r requirements.txt
npm ci
npm run build
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open [the local workspace](http://127.0.0.1:8000). It starts empty. Use **Open sample** to inspect fixtures in a read-only view. For frontend development, run `npm run dev` alongside the API on port 8000.

The [public site](http://127.0.0.1:8000/home), [sample demos](http://127.0.0.1:8000/demo), and [user documentation](http://127.0.0.1:8000/docs) are available without workspace credentials. Workspace and API access follow the deployment's authentication settings. Interactive OpenAPI documentation is at `/api/docs`.

## Import, review, and export

1. Create a run and upload a statement and open-invoice ledger. Supported inputs include ISO 20022 camt.053 and pacs.008, MT940, BAI2, and bank CSV. Optional files include credit memo CSV and plain-text remittance advice.
2. Set the fallback currency and booking date when these values are missing from the input. For Bank CSV, booking dates use `YYYY-MM-DD`. The engine matches invoices and credit memos in the payment currency and reports totals by currency.
3. Enter any additional discount, withholding, and wire-fee candidates for the batch. Set the chart of accounts and ERP fields under the run's settings. Treaty screening requires an explicit corridor and service selection. Its rates come from the reference table in the repository and are intended for review.
4. Review each transaction's invoice allocations, deductions, and proposed journal. Rejections and exception approvals require a note. Unmatched deposits stay in review until resolved in a new run. Each decision records its timestamp and operator.
5. Prepare an export batch for approved journals by currency. In ERP handoff, download the immutable file, import it into your ERP, and record the receipt reference or rejection. Active batches reserve payments, invoice balances and credit memos across runs. Rejections release reservations.
6. Use Customers and invoices to review remaining balances and create collection follow-ups. Resolve unmatched payments with Allocate received cash and submit the resulting journal for approval.
7. Resolve the period's payment cases and confirm all ERP receipts, then close the accounting period in Administration. Review the Audit trail for recorded decisions and allocation revisions.

Market research and the product workflow map are available in [the market assessment](docs/market-and-workflows.md).

### Invoice register and customer portal

1. Open **Invoice register**, add a customer, and draft an invoice with line items. Issue the invoice to make it visible in the register and the customer portal.
2. An administrator can create a customer access link and share it privately. Replacing or revoking the link invalidates the old link. Anyone holding an active link can access that customer's issued invoices and submit updates.
3. Customers can view balances and submit remittance details, disputes, or promises to pay. These submissions create cases in **Exceptions and collections**. Case status is visible in the portal.
4. In **New reconciliation**, select the entity's invoice register as the invoice source. The register supplies issued invoices with available balances. Confirm the ERP receipt to update the outstanding amount shown in the operator workspace and customer portal.

Issuing in ClearRemit publishes the invoice to its register and portal. Create the corresponding sales invoice in the accounting system before importing cash application journals. Amounts are based on user-entered line prices. Tax calculation and statutory e-invoicing depend on jurisdiction and remain external.

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
| `CLEARREMIT_USERS_JSON` | Named operators with credentials, roles and organization memberships |

The Render blueprint builds the Docker image, requires sign-in over HTTPS, and mounts a persistent disk for SQLite. It uses a paid Starter service to retain runs across deployments. Supply the credentials in the Render dashboard when configuring the service. The health endpoint is `/api/health`.

The default entity preserves existing saved runs. Add organizations and client or legal entity records in Administration. Each organization can use the finance team, accounting firm, or enterprise operating model.

Named operators use the following JSON structure in the deployment environment. Use your own credentials and the organization IDs returned by the API. An asterisk grants access to all organizations.

```json
[
  {"username":"preparer","password":"SET_IN_DEPLOYMENT","role":"analyst","organizations":["ORGANIZATION_ID"]},
  {"username":"reviewer","password":"SET_IN_DEPLOYMENT","role":"approver","organizations":["ORGANIZATION_ID"]},
  {"username":"audit","password":"SET_IN_DEPLOYMENT","role":"auditor","organizations":["ORGANIZATION_ID"]}
]
```

Admins configure organizations, entities and policies. Analysts import and resolve payments. Approvers approve journals, prepare exports, record receipts and close periods. Auditors have read access and can download existing batches and audit history. Set separate approval on an entity to require the importer and approver to be different operators. The original single-operator credentials remain an administrator login. Named operator entries may also include an `entities` array to restrict access to specific clients or legal entities within their assigned organizations.

Invoice imports represent opening balances managed in this workspace. The ledger subtracts active export allocations from those balances. Direct ERP balance synchronization needs a posting checkpoint before connecting a continuously refreshed open-balance feed.

ClearRemit includes entity-scoped bank and remittance intake, an ERP batch and receipt API, a signed Stripe webhook, TLS SMTP invoice delivery, and an identity proxy integration. Provider-side setup, API contracts, and remaining capabilities are documented in the [connector setup guide](docs/integrations.md).

## Verification

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
npm ci
npm run build
```
