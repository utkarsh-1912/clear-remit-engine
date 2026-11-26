import React from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Stat, Table } from '@utkristi/ui';
import { Plus, Zap } from 'lucide-react';
import { fmtInt, fmtNum, fmtUsd } from './utils';

export default function CommandCenter({ core, onSelectTab, onDrillAccount }) {
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
          <div className="eyebrow">Core Financial OS</div>
          <h1>Executive Command Center</h1>
          <p>Live multi-currency balances, cash flows, and verified double-entry invariants.</p>
        </div>
        <div className="actions">
          <Button variant="ghost" onClick={() => onSelectTab('bulk')} iconLeft={<Zap size={15} />}>
            GB Data Streamer
          </Button>
          <Button onClick={() => onSelectTab('vouchers')} iconLeft={<Plus size={15} />}>
            New Voucher
          </Button>
        </div>
      </header>

      <div className="metrics">
        <Stat label="Total Assets (USD)" value={fmtUsd(bs.total_assets)} />
        <Stat label="Global Cash & Nostro" value={fmtUsd(totalCash)} />
        <Stat label="Net Profit (Period)" value={fmtUsd(pl.net_profit)} />
        <Stat label="Open AR / Vouchers" value={`${fmtUsd(aging.total_open_ar_usd)} · ${fmtInt(core.total_vouchers_count)}`} />
      </div>

      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading">
            <div>
              <h2>Multi-Currency Nostro &amp; Bank Cash</h2>
              <p>Click any GL code to open its running-balance ledger statement.</p>
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
              <h2>Recent Immutable Vouchers</h2>
              <p>Query latency: {core.query_latency_ms} ms over SQLite WAL.</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => onSelectTab('vouchers')}>
              Open Daybook
            </Button>
          </CardHeader>
          {core.vouchers.length > 0 ? (
            <Table columns={voucherCols} rows={core.vouchers.slice(0, 8)} getRowKey={r => r.voucher_id} />
          ) : (
            <CardBody><EmptyState title="No vouchers posted yet" /></CardBody>
          )}
        </Card>
      </div>
    </div>
  );
}
