import React, { useEffect, useState } from 'react';
import {
  Badge, Button, Card, CardBody, CardHeader, Footer, Navbar, Spinner, Stat, ThemeToggle,
} from '@utkristi/ui';
import {
  ArrowRight, Banknote, Database, Globe2, Layers3, Scale, ShieldCheck, TrendingUp, Zap,
} from 'lucide-react';
import { ClearLedgerLogo, LedgyMascot } from './brand';

const CAPABILITIES = [
  {
    icon: Layers3,
    title: 'Immutable Multi-Currency Core GL',
    desc: 'Integer minor-unit accounting, tri-value currency legs, multi-line Tally vouchers, and running-balance ledger drill-down.',
  },
  {
    icon: Globe2,
    title: 'IAS 21 FX & Nostro Treasury',
    desc: 'Date-wise FX spot matrix, cross-currency Nostro contra conversions with Realized FX Gain/Loss, and period-end IAS 21 revaluation.',
  },
  {
    icon: Banknote,
    title: 'ISO 20022 / MT940 / BAI2 Remittance Hub',
    desc: 'Combinatorial subset-sum short-pay solver decodes lump-sum payments, discounts, credit memos, and blind wires into balanced GL entries.',
  },
  {
    icon: Scale,
    title: 'Cross-Border DTAA Tax Compliance',
    desc: 'Audits bilateral withholding rates across international tax corridors and generates Foreign Tax Credit documentation checklists.',
  },
  {
    icon: TrendingUp,
    title: 'Post-Trade Investment Tax-Lot Ledger',
    desc: 'Ingests settled broker contract notes to compute FIFO cost basis and statutory STCG vs. LTCG schedules synced directly to your Balance Sheet.',
  },
  {
    icon: Zap,
    title: 'GB-Scale Constant-Memory Streaming',
    desc: 'Streams multi-gigabyte XML and CSV statements via O(1) RAM iterparse and batched SQLite WAL transactions with sub-15ms paginated queries.',
  },
];

export default function MarketingPage({ onNavigate }) {
  const [liveStats, setLiveStats] = useState(null);

  useEffect(() => {
    let active = true;
    fetch('/api/core/overview')
      .then(r => (r.ok ? r.json() : null))
      .then(data => { if (active && data) setLiveStats(data); })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  const navItems = [
    { label: 'Capabilities', href: '#capabilities' },
    { label: 'Architecture', href: '#telemetry' },
    { label: 'Sign In', href: '/auth', onClick: e => { e.preventDefault(); onNavigate('/auth'); } },
  ];

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar
        brand={
          <a href="/" onClick={e => { e.preventDefault(); onNavigate('/'); }} style={{ textDecoration: 'none' }}>
            <ClearLedgerLogo size={34} />
          </a>
        }
        items={navItems}
        actions={
          <div className="actions">
            <ThemeToggle />
            <Button variant="ghost" onClick={() => onNavigate('/auth')}>Sign In</Button>
            <Button onClick={() => onNavigate('/app')} iconRight={<ArrowRight size={15} />}>
              Launch Workspace
            </Button>
          </div>
        }
      />

      <main className="main stack" style={{ maxWidth: 1240 }}>
        {/* Hero */}
        <section
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 32,
            alignItems: 'center',
            paddingBlock: 28,
          }}
        >
          <div className="stack" style={{ gap: 16 }}>
            <div>
              <Badge tone="ok">Multi-Currency Core GL • IAS 21 FX • ISO 20022 • Post-Trade Tax Lots</Badge>
            </div>
            <h1>Unified Financial Core for Accounting, FX, Remittance &amp; Tax.</h1>
            <p style={{ fontSize: '1.05rem', maxWidth: '58ch' }}>
              ClearLedger Prime brings together an immutable double-entry ledger, real-time financial statements,
              cross-border remittance reconciliation, and constant-memory multi-gigabyte ingestion in one modular OS.
            </p>
            <div className="actions" style={{ marginTop: 8 }}>
              <Button onClick={() => onNavigate('/app')} iconRight={<ArrowRight size={16} />}>
                Open Financial OS
              </Button>
              <Button variant="ghost" onClick={() => onNavigate('/auth')}>
                Sign In / Create Account
              </Button>
            </div>
          </div>

          <Card className="panel">
            <CardBody className="stack" style={{ alignItems: 'center', textAlign: 'center', padding: 28 }}>
              <LedgyMascot size={190} />
              <Badge tone="info">Ledgy — Zero-Variance Ledger Auditor</Badge>
              {liveStats ? (
                <div className="detail-metrics" style={{ width: '100%' }}>
                  <Stat label="GL Accounts" value={String(liveStats.accounts?.length ?? 0)} />
                  <Stat label="Vouchers" value={String(liveStats.total_vouchers_count ?? 0)} />
                  <Stat label="Query Latency" value={`${liveStats.query_latency_ms ?? 0} ms`} />
                </div>
              ) : (
                <div className="loading"><Spinner /> Connecting to live core engine…</div>
              )}
            </CardBody>
          </Card>
        </section>

        {/* Live Engine Telemetry Band */}
        <section id="telemetry">
          <Card className="panel">
            <CardHeader className="panel-heading">
              <div>
                <h2>Live Engine Invariant Status</h2>
                <p>Values below are queried directly from the active SQLite WAL core ledger.</p>
              </div>
              {liveStats?.statements?.balance_sheet?.is_balanced && (
                <Badge tone="ok"><ShieldCheck size={14} /> Balance Sheet Balanced</Badge>
              )}
            </CardHeader>
            <CardBody>
              {liveStats ? (
                <div className="metrics">
                  <Stat
                    label="Entity Base Currency"
                    value={liveStats.statements?.functional_currency || 'USD'}
                  />
                  <Stat
                    label="Total Assets"
                    value={`$${Number(liveStats.statements?.balance_sheet?.total_assets || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
                  />
                  <Stat
                    label="Active FX Rates"
                    value={String(liveStats.fx_rates?.length ?? 0)}
                  />
                  <Stat
                    label="Trial Balance"
                    value={liveStats.statements?.trial_balance?.is_balanced ? 'Zero Variance' : 'Review'}
                  />
                </div>
              ) : (
                <div className="loading"><Spinner /> Loading live telemetry…</div>
              )}
            </CardBody>
          </Card>
        </section>

        {/* Capabilities Grid */}
        <section id="capabilities" className="stack">
          <div>
            <div className="eyebrow">Modular Architecture</div>
            <h2>Built with @utkristi/ui and Deterministic Financial Invariants</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
            {CAPABILITIES.map(({ icon: Icon, title, desc }) => (
              <Card key={title} className="panel">
                <CardBody className="stack" style={{ gap: 10 }}>
                  <div className="process-icon"><Icon size={18} /></div>
                  <h3>{title}</h3>
                  <p style={{ fontSize: '0.9rem' }}>{desc}</p>
                </CardBody>
              </Card>
            ))}
          </div>
        </section>
      </main>

      <Footer
        brand={<ClearLedgerLogo size={26} showTagline={false} />}
        note="ClearLedger Prime Financial OS — Non-Custodial Statutory Accounting, FX & Remittance Infrastructure."
      />
    </div>
  );
}
