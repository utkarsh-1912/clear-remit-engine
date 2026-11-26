import React, { useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Spinner, Stat, Table, Textarea } from '@utkristi/ui';
import { apiFetch, fmtUsd } from './utils';

export default function InvestmentTaxLots({ core, onRefresh }) {
  const [csvText, setCsvText] = useState('');
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState('');
  const [importing, setImporting] = useState(false);
  const inv = core.investments;
  const s = inv.summary;

  async function handleIngest(e) {
    e.preventDefault();
    setError('');
    setStatusMsg('');
    setImporting(true);
    try {
      const res = await apiFetch('/api/investments/ingest', {
        method: 'POST',
        body: JSON.stringify({ csv_content: csvText }),
      });
      setStatusMsg(`Processed ${res.ingestion.trades_processed} post-trade settlements into Core GL.`);
      await onRefresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  }

  const lotCols = [
    { key: 'symbol', header: 'Symbol' },
    { key: 'asset_class', header: 'Class', render: r => <Badge tone="info">{r.asset_class}</Badge> },
    { key: 'acquisition_date', header: 'Acq Date' },
    { key: 'qty', header: 'Rem / Init', align: 'right', render: r => `${r.quantity_remaining} / ${r.quantity_initial}` },
    { key: 'unit_cost', header: 'Unit Cost', align: 'right', render: r => fmtUsd(r.unit_cost) },
    { key: 'remaining_cost_basis', header: 'Cost Basis', align: 'right', render: r => fmtUsd(r.remaining_cost_basis) },
  ];

  const gainCols = [
    { key: 'sale_date', header: 'Sale Date' },
    { key: 'symbol', header: 'Symbol' },
    { key: 'term_type', header: 'Term', render: r => <Badge tone={r.term_type === 'LTCG' ? 'ok' : 'warn'}>{r.term_type}</Badge> },
    { key: 'holding_days', header: 'Days', align: 'right' },
    { key: 'proceeds', header: 'Proceeds', align: 'right', render: r => fmtUsd(r.proceeds) },
    { key: 'cost_basis', header: 'FIFO Cost', align: 'right', render: r => fmtUsd(r.cost_basis) },
    { key: 'realized_gain', header: 'Gain / Loss', align: 'right', render: r => fmtUsd(r.realized_gain) },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <h1>Investment tax lots</h1>
          <p>Import post-settlement broker contract notes to compute FIFO cost basis and statutory STCG/LTCG schedules.</p>
        </div>
      </header>

      <div className="metrics">
        <Stat label="Open FIFO Cost Basis" value={fmtUsd(s.total_open_cost_basis)} />
        <Stat label="Realized STCG (<=365d)" value={fmtUsd(s.total_realized_stcg)} />
        <Stat label="Realized LTCG (>365d)" value={fmtUsd(s.total_realized_ltcg)} />
        <Stat label="Total Realized Gains" value={fmtUsd(s.total_realized_capital_gains)} />
      </div>

      {error && <div className="error">{error}</div>}
      {statusMsg && <Badge tone="ok">{statusMsg}</Badge>}

      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Import Post-Trade Broker CSV</h2></div></CardHeader>
        <CardBody>
          <form onSubmit={handleIngest} className="stack" style={{ gap: 12 }}>
            <Field label="Broker CSV file">
              <Input type="file" accept=".csv" disabled={importing} onChange={async e => {
                try {
                  if (e.target.files[0]) setCsvText(await e.target.files[0].text());
                } catch (err) {
                  setError(err.message);
                }
              }} />
            </Field>
            <Field label="CSV contents" hint="trade_date, action, symbol, asset_class, quantity, unit_price, brokerage_charges, currency, broker_ref">
              <Textarea
                rows={6}
                required
                value={csvText}
                onChange={e => setCsvText(e.target.value)}
                placeholder="Paste CSV or select a file above"
              />
            </Field>
            <div className="actions"><Button type="submit" disabled={importing || !csvText.trim()} iconLeft={importing ? <Spinner /> : undefined}>Import &amp; Post to Core GL</Button></div>
          </form>
        </CardBody>
      </Card>

      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Open FIFO Tax-Lots</h2></div></CardHeader>
          {inv.open_lots.length > 0 ? <Table columns={lotCols} rows={inv.open_lots} getRowKey={r => r.lot_id} /> : (
            <CardBody><EmptyState title="No open tax lots" /></CardBody>
          )}
        </Card>
        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Realized Capital Gains Schedule</h2></div></CardHeader>
          {inv.realized_schedule.length > 0 ? <Table columns={gainCols} rows={inv.realized_schedule} getRowKey={r => r.gain_id} /> : (
            <CardBody><EmptyState title="No realized dispositions yet" /></CardBody>
          )}
        </Card>
      </div>
    </div>
  );
}
