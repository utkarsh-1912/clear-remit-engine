import React, { useEffect, useState } from 'react';
import { Badge, Button, Card, CardBody, DataTable, EmptyState, Select, Spinner, Stat, Table } from '@utkristi/ui';
import { ArrowDownToLine } from 'lucide-react';
import { api, humanize, money } from './api';
import { ErrorPage } from './errors';

const formats = {
  iso20022: ['ISO 20022', 'Structured remittance and bank statement XML'],
  mt940: ['MT940', 'SWIFT bank statement'],
  bai2: ['BAI2', 'Bank Administration Institute cash management file'],
};
const matchStatuses = {
  AUTO_RECONCILED: ['Matched', 'ok'],
  ACTION_REQUIRED_SHORT_PAY: ['Short pay', 'warn'],
  UNMATCHED_SUSPENSE: ['Unmatched', 'bad'],
};

function MatchStatus({ status }) {
  const [label, tone] = matchStatuses[status] ?? [humanize(status), 'neutral'];
  return <Badge tone={tone}>{label}</Badge>;
}

export function DemoPreview() {
  return <figure className="demo-preview">
    <div className="preview-heading"><div><small>Sample workspace</small><h2>Cash application</h2></div><Badge tone="ok">Review queue</Badge></div>
    <ul>
      <li><span>Matched receipts</span><Badge tone="ok">Ready for review</Badge></li>
      <li><span>Short payments</span><Badge tone="warn">Needs investigation</Badge></li>
      <li><span>Unmatched deposits</span><Badge tone="bad">Needs allocation</Badge></li>
    </ul>
    <a href="/demo/iso20022">Open the interactive sample →</a>
  </figure>;
}

function DemoRun({ format }) {
  const [state, setState] = useState({});
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api(`/public/demo/${format}`, { signal: controller.signal }).then(data => setState({ data }))
      .catch(error => { if (!controller.signal.aborted) setState({ error }); });
    return () => controller.abort();
  }, [format]);
  if (state.error) return <ErrorPage retry={() => location.reload()} />;
  if (!state.data) return <p className="loading" role="status"><Spinner /> Loading sample reconciliation…</p>;

  const { summary, proposals, statement, export_formats: exports } = state.data;
  const visible = proposals.filter(row => !filter || row.status === filter);
  const active = visible.find(row => row.tx_id === selected) ?? visible[0];
  return <>
    <div className="metrics public-metrics">
      <Stat label="Transactions" value={summary.total_transactions} />
      <Stat label="Matched" value={summary.auto_reconciled_count} />
      <Stat label="Short payments" value={summary.action_required_dispute_count} />
      <Stat label="Unmatched" value={summary.unmatched_count} />
    </div>
    <section className="stack">
      <h2>Review payments</h2>
      <DataTable rows={visible} getRowKey={row => row.tx_id} density="compact" pageSize={10}
        emptyMessage="No payments match this status"
        toolbar={<Select aria-label="Filter by match status" value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="">All match statuses</option>
          {Object.entries(matchStatuses).map(([value, [label]]) => <option key={value} value={value}>{label}</option>)}
        </Select>}
        columns={[
          { key: 'tx_id', header: 'Transaction', render: row => <Button size="sm" variant="quiet"
            aria-pressed={active?.tx_id === row.tx_id} onClick={() => setSelected(row.tx_id)}>{row.tx_id}</Button> },
          { key: 'matched_customer_name', header: 'Customer' },
          { key: 'deposit_amount', header: 'Cash received', align: 'right', render: row => money(row.deposit_amount, row.currency) },
          { key: 'status', header: 'Status', render: row => <MatchStatus status={row.status} /> },
        ]} />
    </section>
    {active && <Card className="panel demo-detail">
      <CardBody className="stack">
        <div className="preview-heading"><h2>Journal for {active.tx_id}</h2><MatchStatus status={active.status} /></div>
        <p>{active.explanation_summary}</p>
        <Table rows={active.journal_entries} getRowKey={row => row.line_number} density="compact" columns={[
          { key: 'account_name', header: 'Account' },
          { key: 'invoice_ref', header: 'Invoice' },
          { key: 'debit', header: 'Debit', align: 'right', render: row => money(row.debit, active.currency) },
          { key: 'credit', header: 'Credit', align: 'right', render: row => money(row.credit, active.currency) },
        ]} />
      </CardBody>
    </Card>}
    <section className="stack">
      <h2>Sample exports</h2>
      <p>These files contain sample proposals, including any exceptions. Use them to inspect the layout.</p>
      <div className="actions">{Object.entries(exports).map(([key, label]) => <Button variant="ghost" key={key}
        href={`/api/public/demo/${format}/exports/${key}`} iconLeft={<ArrowDownToLine size={16} />} download>{label}</Button>)}</div>
    </section>
    <details className="public-statement"><summary>View sample bank statement</summary><pre>{statement}</pre></details>
  </>;
}

export default function Demo({ path }) {
  const format = path.split('/')[2];
  if (format && !Object.hasOwn(formats, format)) return <ErrorPage notFound />;
  return <div className="public-container public-page stack">
    <div className="public-intro"><h1>{format ? `${formats[format][0]} reconciliation demo` : 'Try a reconciliation'}</h1>
      <p className="public-lead">Pick a sample statement to see payment matches, exceptions, proposed journals, and ERP files. The demo uses sample data and needs no account.</p></div>
    <nav className="public-format-nav" aria-label="Statement formats">
      {Object.entries(formats).map(([key, [label, description]]) => <a href={`/demo/${key}`} key={key}
        className="public-doc-link" aria-current={format === key ? 'page' : undefined}><strong>{label}</strong><p>{description}</p></a>)}
    </nav>
    {format ? <DemoRun format={format} /> : <EmptyState title="Choose a statement format" action={
      <Button href="/demo/iso20022">Start with ISO 20022</Button>
    }>Inspect how the engine matches invoice references and handles missing or short payments.</EmptyState>}
  </div>;
}
