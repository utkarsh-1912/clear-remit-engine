import React from 'react';
import { Button, Card, CardBody, Footer, Navbar } from '@utkristi/ui';
import { ArrowRight, Banknote, Building2, ClipboardCheck, FileSpreadsheet, Layers3, Plug } from 'lucide-react';
import Demo, { DemoPreview } from './public-demo';
import Documentation from './public-docs';
import './public-site.css';

const workflow = [
  { icon: FileSpreadsheet, title: 'Issue invoices and collect payment details', text: 'Create invoices by entity. Customers can view balances and submit remittance details, disputes, or promises to pay.' },
  { icon: Banknote, title: 'Match incoming cash', text: 'Bring in bank statements, open receivables, credit memos, and remittance advice. Review proposed allocations and the journal entries they produce.' },
  { icon: ClipboardCheck, title: 'Approve and confirm posting', text: 'Route exceptions to an owner. Approve journals, send batches to the ERP, and update receivables when posting is confirmed.' },
];

const audiences = [
  { path: '/solutions/finance', title: 'Finance teams', text: 'Apply incoming cash and track exceptions from a shared queue.',
    steps: ['Import the daily statement and invoice ledger.', 'Review automatic matches and assign unexplained receipts.', 'Prepare approved journals and confirm posting before close.'] },
  { path: '/solutions/accounting-firms', title: 'Accounting firms', text: 'Manage multiple client entities from one workspace with scoped operator access.',
    steps: ['Create an organization for the practice and an entity for each client.', 'Set the client’s currency and matching policy, then grant operators the appropriate scope.', 'Track cases, batches, and audit history for each client.'] },
  { path: '/solutions/enterprise', title: 'Multi-entity enterprises', text: 'Keep legal entities, currencies, and approval policies under separate controls.',
    steps: ['Set up legal entities and define administrator, analyst, approver, and auditor roles.', 'Require separate approval where needed and prepare exports by currency.', 'Confirm ERP receipts and resolve payment cases before closing periods.'] },
];

const links = [
  ['/product', 'Product'], ['/solutions', 'Solutions'], ['/integrations', 'Integrations'],
  ['/pricing', 'Hosting'], ['/demo', 'Demo'], ['/docs', 'Docs'],
];

function Brand() {
  return <a href="/home" className="public-brand"><Layers3 size={22} aria-hidden="true" />ClearRemit</a>;
}

function Intro({ title, children }) {
  return <header className="public-intro"><h1>{title}</h1><p className="public-lead">{children}</p></header>;
}

function Cards({ items }) {
  return <div className="public-grid">
    {items.map(({ icon: Icon, title, text, path }) => <Card className="public-card" key={title}>
      <CardBody className="stack">
        {Icon && <div className="process-icon"><Icon size={20} aria-hidden="true" /></div>}
        <h3>{title}</h3><p>{text}</p>
        {path && <a href={path} aria-label={`Explore ${title}`}>Explore workflow <ArrowRight size={15} aria-hidden="true" /></a>}
      </CardBody>
    </Card>)}
  </div>;
}

function Home() {
  return <>
    <section className="public-hero public-container">
      <div className="stack">
        <div className="eyebrow">Receivables operations</div>
        <h1>From open invoices to confirmed cash.</h1>
        <p className="public-lead">Issue invoices, match payments, and work through exceptions. Track every approval and ERP receipt in the same workspace.</p>
        <div className="actions"><Button href="/demo">Try the sample demo</Button><Button href="/" variant="ghost">Open workspace</Button></div>
      </div>
      <DemoPreview />
    </section>
    <section className="public-container public-band stack"><h2>Follow each payment through close</h2><Cards items={workflow} /></section>
    <section className="public-container public-band stack"><h2>Workflows for different finance teams</h2><Cards items={audiences} /></section>
  </>;
}

function Product() {
  return <>
    <Intro title="Receivables and cash application">See the invoice, incoming payment, exception, journal approval, and ERP receipt in one workflow.</Intro>
    <Cards items={workflow} />
    <section className="public-split">
      <div className="stack"><h2>Work the exceptions that need attention</h2>
        <p>Assign owners, record customer follow-up, and manually allocate incoming cash where a match needs judgment. Revisions go back through approval.</p>
        <p>Use the audit trail and aging views to monitor unresolved cases, remaining balances, and posting status by entity.</p>
        <div><Button href="/docs/workflows" variant="ghost">Read the workflow guide</Button></div>
      </div>
      <DemoPreview />
    </section>
  </>;
}

function Solutions({ path }) {
  const audience = audiences.find(item => item.path === path);
  if (!audience) return <><Intro title="ClearRemit for your finance operation">Choose the workflow that fits how your team manages receivables.</Intro><Cards items={audiences} /></>;
  return <>
    <Intro title={audience.title}>{audience.text}</Intro>
    <Card className="panel"><CardBody className="stack"><h2>How your team can use ClearRemit</h2>
      <ol className="public-steps">{audience.steps.map(step => <li key={step}>{step}</li>)}</ol>
      <div className="actions"><Button href="/demo">Explore the demo</Button><Button href="/docs/getting-started" variant="ghost">Setup guide</Button></div>
    </CardBody></Card>
    <Button href="/solutions" variant="quiet">All solutions</Button>
  </>;
}

function IntegrationsPage() {
  return <>
    <Intro title="Connect your finance systems">Bring bank and remittance data into ClearRemit and send approved journals to the ERP through configured connectors.</Intro>
    <Cards items={[
      { icon: Banknote, title: 'Bank and remittance intake', text: 'Import ISO 20022, MT940, BAI2, and CSV files. Upstream jobs can submit statements and remittance details through entity-scoped endpoints.' },
      { icon: FileSpreadsheet, title: 'ERP handoff', text: 'Export journals for QuickBooks, Xero, NetSuite, and Tally Prime. A configured ERP job can retrieve batches and return receipts.' },
      { icon: Plug, title: 'Payment events and delivery', text: 'Signed Stripe events enter the reconciliation queue. TLS SMTP supports invoice emails. An identity proxy can handle SSO.' },
    ]} />
    <div className="actions"><Button href="/docs/connectors">Connector setup</Button><Button href="/docs/api" variant="ghost">API reference</Button></div>
    <p>Provider accounts and upstream jobs handle live data retrieval and vendor-specific posting.</p>
  </>;
}

function Hosting() {
  return <>
    <Intro title="Hosting and pricing">Run ClearRemit locally or deploy it in your own environment.</Intro>
    <Cards items={[
      { title: 'Local evaluation', text: 'Run the workspace on your machine or explore the public demo using sample statements.', path: '/docs/getting-started' },
      { title: 'Self-hosted deployment', text: 'Deploy the Docker image, mount persistent storage, and configure operator access. Infrastructure and provider costs depend on your deployment.' },
    ]} />
    <Card className="panel"><CardBody className="stack">
      <h2>Hosted plan availability</h2><p>Hosted plans and commercial pricing have yet to be announced.</p>
      <div><Button href="/demo">Explore without an account</Button></div>
    </CardBody></Card>
  </>;
}

function Security() {
  return <>
    <Intro title="Security and controls">Scope operator access, review journals before export, and record the evidence behind posting and close.</Intro>
    <Cards items={[
      { icon: Building2, title: 'Organization and entity access', text: 'Operator roles and memberships control which client and legal entity records a user can access.' },
      { icon: ClipboardCheck, title: 'Journal and period controls', text: 'Optional approval separation requires a second operator. Export batches reserve allocations, and closed periods block changes.' },
      { icon: FileSpreadsheet, title: 'Traceable activity', text: 'The audit trail records imports, allocation revisions, approval decisions, case updates, and ERP acknowledgments.' },
    ]} />
    <p>Self-hosted operators manage HTTPS, backups, secrets, and provider configuration.</p>
    <div><Button href="/docs/connectors" variant="ghost">Read access and connector setup</Button></div>
  </>;
}

export default function PublicSite() {
  const path = location.pathname.replace(/\/$/, '');
  const page = path === '/home' ? <Home />
    : path.startsWith('/demo') ? <Demo path={path} />
    : path.startsWith('/docs') ? <Documentation path={path} />
    : <div className="public-container public-page stack">
      {path === '/product' ? <Product />
        : path.startsWith('/solutions') ? <Solutions path={path} />
        : path === '/integrations' ? <IntegrationsPage />
        : path === '/pricing' ? <Hosting /> : <Security />}
    </div>;
  return <div className="public-site">
    <a className="skip" href="#public-content">Skip to content</a>
    <Navbar sticky={false} brand={<Brand />} links={links.map(([href, label]) => ({
      href, label, active: path === href || path.startsWith(href + '/'),
    }))} right={<Button href="/" variant="ghost" size="sm">Open workspace</Button>} />
    <main id="public-content" tabIndex={-1}>{page}</main>
    <Footer lede={<Brand />} columns={[
      { title: 'Product', links: [
        { href: '/product', label: 'Workflows' }, { href: '/solutions', label: 'Solutions' },
        { href: '/integrations', label: 'Integrations' }, { href: '/security', label: 'Security and controls' }, { href: '/pricing', label: 'Hosting and pricing' },
      ] },
      { title: 'Resources', links: [
        { href: '/demo', label: 'Sample demo' }, { href: '/docs', label: 'Documentation' }, { href: '/docs/api', label: 'API reference' },
      ] },
    ]} />
  </div>;
}
