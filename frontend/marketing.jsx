import React from 'react';
import { Button, Card, CardBody, Navbar, ThemeToggle } from '@utkristi/ui';
import { ArrowDown, ArrowLeftRight, BookOpen, FileChartColumn, Globe2, Layers3, Upload, WalletCards } from 'lucide-react';
import { ClearRemitLogo, ClearRemitMascot } from './brand';
import Documentation from './public-docs';
import publicRoutes from './public-routes.json';

const capabilities = [
  [BookOpen, 'General ledger', 'Create accounts, post balanced vouchers, and trace balances to individual entries.'],
  [ArrowLeftRight, 'Remittance', 'Match bank deposits to invoices, review deductions, and export proposed journals.'],
  [Globe2, 'FX & treasury', 'Maintain exchange rates, record currency conversions, and preview IAS 21 revaluation.'],
  [FileChartColumn, 'Financial reporting', 'Review your balance sheet, profit and loss, cash flow, and receivables aging.'],
  [WalletCards, 'Investment tax lots', 'Import settled trades, track FIFO cost basis, and review realized gains.'],
  [Upload, 'Bank imports', 'Upload bank CSV and ISO 20022 files for direct receipt posting.'],
];

const pages = {
  '/solutions': ['Financial operations by team', 'Explore how controllers, accounting firms, and treasury teams can use ClearRemit.', [
    ['Finance teams', 'Record day-to-day transactions and review balances before close.', '/solutions/finance'],
    ['Accounting firms', 'Trace client activity from source files to the general ledger.', '/solutions/accounting-firms'],
    ['Enterprise finance', 'Coordinate treasury, receipts, and reporting within one ledger.', '/solutions/enterprise'],
  ]],
  '/solutions/finance': ['Finance teams', 'Keep a clear record of daily activity and review balances when you close.', [
    ['Record', 'Post journal, sales, purchase, and receipt vouchers.'],
    ['Reconcile', 'Upload bank statements and compare receipts against open invoices.'],
    ['Review', 'Track outstanding receivables and drill into account balances.'],
  ]],
  '/solutions/accounting-firms': ['Accounting firms', 'Use a separate deployment for each client ledger.', [
    ['Set up the chart', 'Review the default accounts, then add accounts needed by your client.'],
    ['Bring in source data', 'Review and post journals or upload bank and broker records.'],
    ['Prepare reports', 'Review voucher history, balance sheet, cash flow, and aging.'],
  ]],
  '/solutions/enterprise': ['Enterprise finance', 'Review accounting, treasury, and settlement activity in one ledger.', [
    ['Treasury', 'Manage FX rates, record currency conversions, and preview revaluation.'],
    ['Cash application', 'Review proposed allocations and download journal files for your ERP.'],
    ['Reporting', 'Review changes through account-level drill-down and the daybook.'],
  ]],
  '/integrations': ['File formats & integrations', 'Exchange data with your bank, broker, and accounting system using file imports and exports.', [
    ['Bank statements', 'ISO 20022 camt.053 XML, SWIFT MT940, BAI2, and bank CSV for reconciliation.'],
    ['Supporting records', 'Open invoices and credit memos in CSV, remittance details in TXT, and settled broker trades in CSV.'],
    ['ERP journals', 'Download QuickBooks, Xero, or NetSuite CSV files and Tally XML. Review the journal before importing it into your ERP.'],
  ]],
  '/pricing': ['Hosting', 'Run ClearRemit on your own infrastructure with a persistent SQLite database.', [
    ['Local setup', 'Build the frontend and run FastAPI locally.', '/docs/getting-started'],
    ['Server deployment', 'Use the Docker image with a persistent volume for the ledger.'],
  ]],
  '/security': ['Security & controls', 'Restrict access to operational data and retain the posting history.', [
    ['Workspace access', 'Sign in to use ledger APIs. The initial setup creates the first account.'],
    ['Posting history', 'Use reversal vouchers to correct the ledger and retain the original posting.'],
    ['Reconciliation review', 'Review journal entries before posting a receipt or exporting a journal.'],
  ]],
};

function CapabilityGrid() {
  return <div className="marketing-grid">{capabilities.map(([Icon, title, description]) =>
    <Card className="feature-card" key={title}><div className="feature-icon"><Icon size={21} /></div>
      <h2>{title}</h2><p>{description}</p>
    </Card>
  )}</div>;
}

function Home() {
  return <>
    <section className="marketing-hero">
      <div className="marketing-hero-copy">
        <div className="marketing-kicker">Accounting & treasury</div>
        <h1>From bank statement to balanced books.</h1>
        <p>Reconcile incoming payments, manage foreign currency, and review your financial statements in one workspace.</p>
        <div className="actions"><Button href="/app">Open workspace</Button><Button href="/product" variant="outlined">Explore the product</Button></div>
      </div>
      <div className="workflow-visual" aria-label="How records move through ClearRemit">
        <div className="workflow-title"><Layers3 size={19} /> From intake to reporting</div>
        {[
          [Upload, 'Import', 'Bank statements · invoices · trades'],
          [ArrowLeftRight, 'Reconcile', 'Match deposits and review deductions'],
          [BookOpen, 'Post', 'Review journals and update the ledger'],
          [FileChartColumn, 'Report', 'Check balances, cash flow, and aging'],
        ].map(([Icon, title, text], index) => <React.Fragment key={title}>
          {index > 0 && <ArrowDown className="workflow-arrow" size={15} aria-hidden="true" />}
          <div className="workflow-step"><div className="feature-icon"><Icon size={20} /></div><div><strong>{title}</strong><p>{text}</p></div></div>
        </React.Fragment>)}
      </div>
    </section>
    <section className="marketing-section"><h2>What you can do in ClearRemit</h2><CapabilityGrid /></section>
  </>;
}

export default function MarketingPage({ path }) {
  const isHome = path === '/' || path === '/home';
  const isDoc = path.startsWith('/docs');
  const product = path === '/product';
  const [title, summary, features] = pages[path] ?? ['ClearRemit product', 'Follow financial records from intake and posting through reporting.'];
  return <div className="marketing-shell">
    <Navbar brand={<a className="brand" href="/"><ClearRemitLogo /></a>}
      links={[{ label: 'Product', href: '/product' }, { label: 'Solutions', href: '/solutions' },
        { label: 'Integrations', href: '/integrations' }, { label: 'Docs', href: '/docs' }]}
      right={<div className="actions"><ThemeToggle /><Button href="/app" size="sm">Open workspace</Button></div>} />
    <main className="marketing-main">
      {isHome ? <Home /> : isDoc ? <Documentation path={path} /> :
        <div className="stack">
          <header className="marketing-intro"><h1>{title}</h1><p>{summary}</p></header>
          {product ? <CapabilityGrid /> : <div className="marketing-grid">{features.map(([name, text, href]) =>
            <Card className="panel" key={name}><CardBody>
              <h2>{name}</h2><p>{text}</p>
              {href && <Button href={href} variant="outlined" size="sm">Read more</Button>}
            </CardBody></Card>
          )}</div>}
        </div>}
    </main>
    {isHome && <section className="marketing-brand-band"><ClearRemitMascot /><div className="stack"><h2>Ready to reconcile your first statement?</h2><div className="actions"><Button href="/app">Open workspace</Button><Button href="/docs/workflows" variant="ghost">Read the workflow guide</Button></div></div></section>}
    <footer className="marketing-footer"><a className="brand" href="/"><ClearRemitLogo size={26} /></a>
      <nav aria-label="Footer">{['/security', '/pricing', '/docs'].map(href => <a href={href} key={href}>{publicRoutes[href]}</a>)}</nav>
    </footer>
  </div>;
}
