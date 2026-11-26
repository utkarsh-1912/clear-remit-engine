import React from 'react';
import { Button, CodeBlock, Sidebar, SidebarLink } from '@utkristi/ui';

const articles = {
  '/docs/getting-started': ['Getting started', 'Build and run ClearRemit, then set up your ledger.', () => <>
    <h2>Run the application</h2>
    <p>Install Python 3.12 and Node.js 22.12 or newer. Run the following commands from the repository root.</p>
    <CodeBlock language="bash" code={'python -m pip install -r requirements.txt\nnpm ci\nnpm run build\npython -m uvicorn app:app --host 127.0.0.1 --port 8000'} />
    <p>Open the home page and select Open workspace. On a new installation, create the first account for your organization. The ledger starts with a standard chart of accounts.</p>
    <p>For a server deployment, point <code>CLEARLEDGER_DB_PATH</code> to a file on your persistent volume.</p>
    <div><Button href="/app">Open workspace</Button></div>
  </>],
  '/docs/workflows': ['Workflows', 'Post vouchers, apply receipts, and review financial reports.', () => <>
    <h2>Record a voucher</h2>
    <p>Open Vouchers &amp; daybook. Choose a type and posting date, add debit and credit lines, then post the balanced entry. To correct a posting, record a reversal from the daybook.</p>
    <h2>Reconcile a payment</h2>
    <p>Open Remittance &amp; tax. Upload a statement and your open invoice CSV. Add remittance details or credit memos if available. Run reconciliation, select a payment, and review the journal before posting the receipt or downloading an ERP export.</p>
    <h2>Review the ledger</h2>
    <p>Open Statements &amp; aging to review cash flow, receivables aging, and financial balances. Open the account ledger from the chart of accounts to trace a balance to its vouchers.</p>
  </>],
  '/docs/connectors': ['File formats', 'Prepare the files ClearRemit reads and writes.', () => <>
    <h2>Bank statements</h2>
    <p>Reconciliation supports ISO 20022 XML, MT940, BAI2, and bank CSV. The bank CSV takes <code>tx_id</code>, <code>booking_date</code>, <code>payer_name</code>, <code>amount</code>, <code>currency</code>, and optional <code>remittance_info</code>. Use ISO dates and decimal amounts.</p>
    <h2>Open invoices and credit memos</h2>
    <p>Invoice CSV columns include <code>invoice_id</code>, <code>customer_id</code>, <code>customer_name</code>, <code>currency</code>, <code>gross_amount</code>, and <code>open_amount</code>. Credit memo files identify the memo and customer and include the amount and currency.</p>
    <h2>Broker trades</h2>
    <p>Import a CSV with <code>trade_date</code>, <code>action</code>, <code>symbol</code>, <code>asset_class</code>, <code>quantity</code>, <code>unit_price</code>, <code>brokerage_charges</code>, <code>currency</code>, and <code>broker_ref</code>.</p>
    <h2>ERP exports</h2>
    <p>After reconciliation, download the proposed journals as QuickBooks CSV, Xero CSV, NetSuite CSV, or Tally XML. Review the entries and confirm the destination’s import settings before handing off the file.</p>
  </>],
  '/docs/api': ['API reference', 'Use the OpenAPI reference for request and response schemas.', () => <>
    <h2>Authentication</h2>
    <p>Sign in through <code>POST /api/auth/login</code>. The ledger endpoints require the session cookie from the response.</p>
    <h2>Workflow endpoints</h2>
    <ul>
      <li><code>GET /api/core/overview</code> reads workspace balances and recent activity.</li>
      <li><code>POST /api/core/vouchers</code> posts a balanced voucher.</li>
      <li><code>POST /api/reconcile</code> accepts a statement and invoice data and returns proposed journals.</li>
      <li><code>POST /api/investments/ingest</code> imports settled broker trades.</li>
    </ul>
    <div><Button href="/api-reference" variant="outlined">Interactive API reference</Button></div>
  </>],
};
export default function Documentation({ path }) {
  const [title, summary, Article] = articles[path] ?? ['Documentation', 'Set up your ledger, prepare import files, and follow the accounting workflows.'];
  return <div className="docs-layout">
    <Sidebar heading="Documentation" className="docs-sidebar">
      <nav aria-label="Documentation">
        <SidebarLink href="/docs" label="Overview" aria-current={path === '/docs' ? 'page' : undefined} />
        {Object.entries(articles).map(([href, [name]]) => <SidebarLink key={href} href={href} label={name} aria-current={path === href ? 'page' : undefined} />)}
      </nav>
    </Sidebar>
    <article className="docs-article stack">
      <header><h1>{title}</h1><p>{summary}</p></header>
      {Article ? <Article /> : <div className="stack">{Object.entries(articles).map(([href, [name, text]]) =>
        <a className="doc-link" key={href} href={href}><strong>{name}</strong><p>{text}</p></a>
      )}</div>}
    </article>
  </div>;
}
