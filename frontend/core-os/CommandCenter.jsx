import React from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Stat, Table } from '@utkristi/ui';
import { ArrowLeftRight, Plus, Upload } from 'lucide-react';
import { fmtNum, fmtUsd } from './utils';

export default function CommandCenter({ core, onSelectTab, onDrillAccount }) {
  const hasActivity = core.total_vouchers_count > 0;
  const st = core.statements;
  const bs = st.balance_sheet;
  const pl = st.profit_and_loss;
  const cf = core.cashflow_and_aging?.cash_flow_statement || {};
  const aging = core.cashflow_and_aging?.ar_aging || { total_open_ar_usd: 0 };
  const totalCash = st.nostro_positions.reduce((s, n) => s + n.functional_usd_value, 0);

  const nostroCols = [
    {
      key: 'code',
      header: 'GL Code',
      render: r => (
        <Button variant="ghost" size="sm" onClick={() => onDrillAccount(r.code)}>
          {r.code}
        </Button>
      ),
    },
    { key: 'name', header: 'Bank / Nostro Account' },
    { key: 'currency_code', header: 'Ccy', render: r => <Badge tone="info">{r.currency_code}</Badge> },
    { key: 'native_balance', header: 'Native Balance', align: 'right', render: r => fmtNum(r.native_balance) },
    { key: 'functional_usd_value', header: 'Functional (USD)', align: 'right', render: r => fmtUsd(r.functional_usd_value) },
  ];

  const voucherCols = [
    { key: 'voucher_number', header: 'Voucher #' },
    { key: 'voucher_type', header: 'Type', render: r => <Badge tone="info">{r.voucher_type}</Badge> },
    { key: 'effective_date', header: 'Date' },
    { key: 'narration', header: 'Narration' },
    { key: 'total_functional_amount', header: 'USD', align: 'right', render: r => fmtUsd(r.total_functional_amount) },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <h1>Financial overview</h1>
          <p>Review your balances, receivables, and recent postings.</p>
        </div>
        <div className="actions">
          <Button variant="ghost" onClick={() => onSelectTab('bulk')} iconLeft={<Upload size={15} />}>
            Import statement
          </Button>
          <Button onClick={() => onSelectTab('vouchers')} iconLeft={<Plus size={15} />}>
            New voucher
          </Button>
        </div>
      </header>

      <div className="metrics">
        <Stat label="Total assets (USD)" value={fmtUsd(bs.total_assets)} />
        <Stat label="Cash & Nostro" value={fmtUsd(totalCash)} />
        <Stat label="Net profit" value={fmtUsd(pl.net_profit)} />
        <Stat label="Open receivables" value={fmtUsd(aging.total_open_ar_usd)} />
      </div>

      {!hasActivity && <section className="stack" aria-labelledby="first-actions">
        <h2 id="first-actions">Start recording activity</h2>
        <div className="workflow-grid">
          {[
            ['vouchers', Plus, 'Post a voucher', 'Record opening balances or your first journal entry.'],
            ['remit', ArrowLeftRight, 'Reconcile a payment', 'Match a bank statement against your open invoices.'],
            ['bulk', Upload, 'Import bank receipts', 'Post receipts from a bank statement file.'],
          ].map(([key, Icon, title, description]) => <a className="workflow-tile" href={`#${key}`} key={key}>
            <div className="feature-icon"><Icon size={19} /></div>
            <div><strong>{title}</strong><p>{description}</p></div>
          </a>)}
        </div>
      </section>}
      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading">
            <div>
              <h2>Bank &amp; Nostro balances</h2>
              <p>Select an account code to view its ledger.</p>
            </div>
            <Badge tone={bs.is_balanced ? 'ok' : 'bad'}>
              {bs.is_balanced ? 'Balance Sheet Balanced' : 'Check Variance'}
            </Badge>
          </CardHeader>
          {st.nostro_positions.length > 0 ? (
            <Table columns={nostroCols} rows={st.nostro_positions} getRowKey={r => r.code} />
          ) : (
            <CardBody><EmptyState title="No cash balances recorded yet" /></CardBody>
          )}
          <CardBody>
            <div className="detail-metrics">
              <Stat label="Operating CF" value={fmtUsd(cf.operating_activities)} />
              <Stat label="Investing CF" value={fmtUsd(cf.investing_activities)} />
              <Stat label="Financing CF" value={fmtUsd(cf.financing_activities)} />
            </div>
          </CardBody>
        </Card>

        <Card className="panel">
          <CardHeader className="panel-heading">
            <div>
              <h2>Recent vouchers</h2>
            </div>
            <Button variant="ghost" size="sm" onClick={() => onSelectTab('vouchers')}>
              Open Daybook
            </Button>
          </CardHeader>
          {hasActivity ? (
            <Table columns={voucherCols} rows={core.vouchers.slice(0, 8)} getRowKey={r => r.voucher_id} />
          ) : (
            <CardBody><EmptyState title="No vouchers posted yet" /></CardBody>
          )}
        </Card>
      </div>
    </div>
  );
}
