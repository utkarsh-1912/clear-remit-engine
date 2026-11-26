import React from 'react';
import { Badge, Button, Card, CardBody, CardHeader, Stat, Table } from '@utkristi/ui';
import { ArrowDownToLine } from 'lucide-react';
import { fmtNum, fmtUsd } from './utils';

export default function FinancialStatements({ core, onDrillAccount }) {
  const st = core.statements;
  const pl = st.profit_and_loss;
  const bs = st.balance_sheet;
  const tb = st.trial_balance;
  const cfa = core.cashflow_and_aging || { cash_flow_statement: {}, ar_aging: { bills: [], total_open_ar_usd: 0 } };
  const cf = cfa.cash_flow_statement;
  const aging = cfa.ar_aging;

  const tbCols = [
    { key: 'code', header: 'Code', render: r => <Button variant="ghost" size="sm" onClick={() => onDrillAccount(r.code)}>{r.code}</Button> },
    { key: 'name', header: 'Account Name' },
    { key: 'parent_group', header: 'Group' },
    { key: 'currency_code', header: 'Ccy' },
    { key: 'native_balance', header: 'Native Bal', align: 'right', render: r => fmtNum(r.native_balance) },
    { key: 'functional_debit', header: 'Debit (USD)', align: 'right', render: r => (r.functional_debit > 0 ? fmtUsd(r.functional_debit) : '—') },
    { key: 'functional_credit', header: 'Credit (USD)', align: 'right', render: r => (r.functional_credit > 0 ? fmtUsd(r.functional_credit) : '—') },
  ];

  const agingCols = [
    { key: 'bill_ref', header: 'Bill Ref' },
    { key: 'party_name', header: 'Party' },
    { key: 'aging_bucket', header: 'Bucket', render: r => <Badge tone={r.age_days > 30 ? 'warn' : 'ok'}>{r.aging_bucket}</Badge> },
    { key: 'age_days', header: 'Age (d)', align: 'right' },
    { key: 'open_usd', header: 'Open USD', align: 'right', render: r => fmtUsd(r.open_usd) },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <div className="eyebrow">Statutory Reporting</div>
          <h1>Financial Statements, Cash Flow &amp; AR Aging</h1>
          <p>Real-time aggregation over immutable SQLite WAL postings. Click any GL code to inspect its running ledger.</p>
        </div>
        <div className="actions">
          <Button variant="ghost" size="sm" href="/api/export/tally" iconLeft={<ArrowDownToLine size={14} />}>Tally XML</Button>
          <Button variant="ghost" size="sm" href="/api/export/quickbooks" iconLeft={<ArrowDownToLine size={14} />}>QuickBooks CSV</Button>
          <Button variant="ghost" size="sm" href="/api/export/xero" iconLeft={<ArrowDownToLine size={14} />}>Xero CSV</Button>
          <Button variant="ghost" size="sm" href="/api/export/netsuite" iconLeft={<ArrowDownToLine size={14} />}>NetSuite CSV</Button>
        </div>
      </header>

      <div className="metrics">
        <Stat label="Total Revenue" value={fmtUsd(pl.total_revenue)} />
        <Stat label="Total Expense" value={fmtUsd(pl.total_expense)} />
        <Stat label="Net Profit" value={fmtUsd(pl.net_profit)} />
        <Stat label="Total Assets" value={fmtUsd(bs.total_assets)} />
      </div>

      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Direct-Method Cash Flow Statement</h2></div></CardHeader>
          <CardBody className="stack" style={{ gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Operating Activities</span><strong>{fmtUsd(cf.operating_activities)}</strong></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Investing Activities</span><strong>{fmtUsd(cf.investing_activities)}</strong></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Financing Activities</span><strong>{fmtUsd(cf.financing_activities)}</strong></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>IAS 21 FX Translation Effect</span><strong>{fmtUsd(cf.fx_translation_effect_on_cash)}</strong></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 8, borderTop: '1px solid var(--cr-line)' }}>
              <strong>Net Change in Cash</strong><strong>{fmtUsd(cf.net_change_in_cash)}</strong>
            </div>
          </CardBody>
        </Card>

        <Card className="panel">
          <CardHeader className="panel-heading">
            <div><h2>Bill-by-Bill AR Aging</h2></div>
            <Badge tone="info">Open AR: {fmtUsd(aging.total_open_ar_usd)}</Badge>
          </CardHeader>
          <Table columns={agingCols} rows={aging.bills} getRowKey={r => `${r.account_code}-${r.bill_ref}`} />
        </Card>
      </div>

      <Card className="panel">
        <CardHeader className="panel-heading">
          <div>
            <h2>Real-Time Trial Balance</h2>
            <p>Total Debits: {fmtUsd(tb.total_debits)} · Total Credits: {fmtUsd(tb.total_credits)}</p>
          </div>
          <Badge tone={tb.is_balanced ? 'ok' : 'bad'}>{tb.is_balanced ? 'Zero Variance' : 'Out of Balance'}</Badge>
        </CardHeader>
        <Table columns={tbCols} rows={tb.rows} getRowKey={r => r.code} />
      </Card>
    </div>
  );
}
