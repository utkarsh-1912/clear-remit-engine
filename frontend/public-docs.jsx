import React from 'react';
import { Button, CodeBlock, Sidebar, SidebarLink, Table } from '@utkristi/ui';

const docs = [
  ['/docs/getting-started', 'Getting started', 'Run ClearRemit and reconcile your first bank statement.'],
  ['/docs/workflows', 'Receivables workflows', 'Follow an invoice from issue to payment, ERP posting, and close.'],
  ['/docs/connectors', 'Connector setup', 'Configure bank and remittance intake, ERP handoff, Stripe, SMTP, and SSO.'],
  ['/docs/api', 'API reference', 'Find request paths, authentication methods, and retry behavior.'],
];

function Section({ title, children }) {
  return <section className="doc-section"><h2>{title}</h2>{children}</section>;
}

function GettingStarted() {
  return <>
    <Section title="Start the app">
      <p>Install Python 3.12+ and Node.js 22.12+. Run these commands from the repository root.</p>
      <CodeBlock language="powershell" code={'python -m pip install -r requirements.txt\nnpm ci\nnpm run build\npython -m uvicorn app:app --host 127.0.0.1 --port 8000'} />
      <p>Open the workspace on port 8000. Use Administration to add a client or legal entity and set its default currency.</p>
    </Section>
    <Section title="Import your first payment">
      <ol>
        <li>Open Reconciliation and select New reconciliation.</li>
        <li>Upload an ISO 20022, MT940, BAI2, or bank CSV statement. Choose the entity’s invoice register or upload an open invoice ledger.</li>
        <li>Supply a fallback currency and booking date if your statement omits them. Add credit memos and remittance details when available.</li>
        <li>Run reconciliation and review the proposed invoice allocations and journal entries.</li>
      </ol>
      <Button href="/demo/iso20022" variant="ghost">Try with sample data</Button>
    </Section>
  </>;
}

function Workflows() {
  return <>
    <Section title="Issue an invoice">
      <p>In Invoice register, add the customer and draft an invoice with line items, issue date, due date, and currency. Issue it to publish it to the register and customer portal. Record the underlying sales invoice in the accounting system before importing cash application journals.</p>
    </Section>
    <Section title="Collaborate with the customer">
      <p>An administrator can create a customer access link and share it privately. Customers can view issued invoices and balances, submit remittance details, raise a dispute, or record a promise to pay. A replacement link revokes the existing one.</p>
    </Section>
    <Section title="Resolve an exception">
      <p>Assign an owner and next action date in Exceptions and collections. Open the source run and allocate received cash to invoices for the same customer and currency. Add evidence and submit the revised journal for approval.</p>
    </Section>
    <Section title="Approve, post, and close">
      <p>An authorized approver reviews journals and prepares an export batch by currency. Download the file from ERP handoff or let a configured ERP bridge retrieve it. Import it into the ERP and record the confirmation or rejection. Confirmed receipts update invoice balances. Close the period once payment cases are resolved and all ERP receipts are confirmed.</p>
    </Section>
  </>;
}

function Connectors() {
  return <>
    <Section title="Bank, remittance, and ERP bridges">
      <p>Configure distinct secrets of at least 24 characters per entity in the deployment environment. A bank, mailbox, or ERP job supplies the source data and calls ClearRemit over HTTPS.</p>
      <CodeBlock language="json" code={'{\n  "ENTITY_ID": {\n    "bank": "BANK_BEARER_SECRET_FROM_DEPLOYMENT",\n    "remittance": "REMITTANCE_SECRET_FROM_DEPLOYMENT",\n    "erp": "ERP_BEARER_SECRET_FROM_DEPLOYMENT",\n    "stripe": "STRIPE_WEBHOOK_SIGNING_SECRET"\n  }\n}'} />
      <p>Set this JSON as <code>CLEARREMIT_CONNECTORS_JSON</code>. Use a separate, randomly generated secret for each bridge.</p>
    </Section>
    <Section title="Stripe">
      <p>Send <code>payment_intent.succeeded</code> events to <code>/api/connector-hooks/&#123;entity_id&#125;/stripe</code>. The PaymentIntent must carry the internal invoice UUID in <code>clearremit_invoice_id</code> metadata. A verified event creates a case for the operator to link to the bank settlement.</p>
    </Section>
    <Section title="Invoice email and SSO">
      <p>Set <code>CLEARREMIT_SMTP_HOST</code>, <code>CLEARREMIT_SMTP_PORT</code>, and <code>CLEARREMIT_SMTP_FROM</code> for implicit TLS email delivery. Supply SMTP username and password if required by the provider.</p>
      <p>For SSO, use an identity-aware reverse proxy. It must overwrite the identity and proxy-key headers, strip client-supplied values, and restrict direct access to the application origin. Map each verified subject to an operator role and organization or entity scope.</p>
    </Section>
  </>;
}

const endpoints = [
  ['POST', '/bank', 'Submit a statement and opening invoice ledger or use the invoice register. Reuse the same submission UUID when retrying.'],
  ['POST', '/remittance', 'Send external_id, customer_id, and detail. Reuse the provider message ID on retry.'],
  ['GET', '/erp', 'List approved and prepared ERP batches for this entity.'],
  ['GET', '/erp/{batch_id}', 'Download the immutable journal file. Deduplicate by batch UUID before posting.'],
  ['POST', '/erp/{batch_id}/receipt', 'Send version, status (confirmed or rejected), and the receipt reference or error.'],
  ['POST', '/stripe', 'Send payment_intent.succeeded with Stripe’s original signature header and raw body.'],
];

function ApiReference() {
  return <>
    <Section title="Entity connector endpoints">
      <p>Prefix these paths with <code>/api/connector-hooks/&#123;entity_id&#125;</code>. Use the connector’s bearer secret. Stripe uses its webhook signature header instead.</p>
      <Table density="compact" rows={endpoints} getRowKey={row => row[0] + row[1]} columns={[
        { key: 'method', header: 'Method', render: row => row[0] },
        { key: 'path', header: 'Path', render: row => <code>{row[1]}</code> },
        { key: 'purpose', header: 'Purpose', render: row => row[2] },
      ]} />
    </Section>
    <Section title="Request example">
      <CodeBlock language="bash" code={'curl --request POST "$CLEARREMIT_URL/api/connector-hooks/$ENTITY_ID/remittance" \\\n  --header "Authorization: Bearer $REMITTANCE_SECRET" \\\n  --header "Content-Type: application/json" \\\n  --data \'{"external_id":"msg-123","customer_id":"CUSTOMER_ID","detail":"Wire reference 7001"}\''} />
      <p>Successful intake returns a case ID. A repeated request with the same external ID and different content returns HTTP 409. Invalid or inaccessible resources return HTTP 404.</p>
      <Button href="/openapi.json" variant="ghost">Workspace OpenAPI schema</Button>
    </Section>
  </>;
}

const articles = {
  '/docs/getting-started': GettingStarted,
  '/docs/workflows': Workflows,
  '/docs/connectors': Connectors,
  '/docs/api': ApiReference,
};

export default function Documentation({ path }) {
  const Article = articles[path];
  const item = docs.find(([href]) => href === path);
  return <div className="public-container documentation">
    <Sidebar heading="Documentation">
      <nav aria-label="Documentation">
        <SidebarLink href="/docs" label="Overview" aria-current={path === '/docs' ? 'page' : undefined} />
        {docs.map(([href, title]) => <SidebarLink key={href} href={href} label={title} aria-current={path === href ? 'page' : undefined} />)}
      </nav>
    </Sidebar>
    <article className="stack">
      <h1>{item?.[1] ?? 'Documentation'}</h1>
      <p className="public-lead">{item?.[2] ?? 'Set up a workspace, follow the receivables workflow, and connect the systems your team already uses.'}</p>
      {Article ? <Article /> : <div className="public-grid">
        {docs.map(([href, title, summary]) => <a className="public-doc-link" href={href} key={href}><strong>{title}</strong><p>{summary}</p></a>)}
      </div>}
    </article>
  </div>;
}
