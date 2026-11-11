import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Select,
  Sidebar, Spinner, Stat, Table, Textarea, ThemeProvider,
} from '@utkristi/ui';
import {
  ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight, Banknote, ClipboardCheck,
  FileSpreadsheet, FlaskConical, Layers3, Plus, Scale, Upload,
} from 'lucide-react';
import '@utkristi/ui/css';
import { api, humanize, money, post, timestamp } from './api';
import './styles.css';

const statuses = {
  AUTO_RECONCILED: ['Matched', 'ok'],
  ACTION_REQUIRED_SHORT_PAY: ['Exception', 'warn'],
  UNMATCHED_SUSPENSE: ['Unmatched', 'bad'],
};

function getReview(run, txId) {
  return Object.hasOwn(run.reviews, txId) ? run.reviews[txId] : null;
}

function Status({ value }) {
  const [label, tone] = statuses[value];
  return <Badge tone={tone}>{label}</Badge>;
}

function ErrorBanner({ error }) {
  return error ? <div className="error" role="alert">{error.message}</div> : null;
}

function useResource(path) {
  const [state, setState] = useState({});
  useEffect(() => {
    const controller = new AbortController();
    if (path) {
      api(path, { signal: controller.signal })
        .then(data => setState({ path, data }))
        .catch(error => { if (!controller.signal.aborted) setState({ path, error }); });
    }
    return () => controller.abort();
  }, [path]);
  const current = state.path === path ? state : {};
  return { ...current, update: data => setState({ path, data }) };
}

function Loading() {
  return <div className="loading" role="status"><Spinner /> Loading workspace data…</div>;
}

function PageHeading({ eyebrow, title, children, action }) {
  return <header className="page-heading">
    <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{children && <p>{children}</p>}</div>
    {action && <div className="actions">{action}</div>}
  </header>;
}

function Dashboard({ metadata }) {
  const [offset, setOffset] = useState(0);
  const runs = useResource(`/runs?limit=25&offset=${offset}`);
  const [demoFormat, setDemoFormat] = useState(Object.keys(metadata.demo_formats)[0]);
  const columns = [
    { key: 'name', header: 'Run', render: run => <a className="table-link" href={`#run/${run.id}`}>{run.name}</a> },
    { key: 'created_at', header: 'Created', render: run => timestamp(run.created_at) },
    { key: 'created_by', header: 'Operator' },
    { key: 'total', header: 'Transactions', align: 'right', render: run => run.summary.total_transactions },
    { key: 'matched', header: 'Matched', align: 'right', render: run => run.summary.auto_reconciled_count },
    { key: 'exceptions', header: 'Needs attention', align: 'right',
      render: run => run.summary.action_required_dispute_count + run.summary.unmatched_count },
  ];
  return <>
    <PageHeading eyebrow="Receivables operations" title="Reconciliation workspace"
      action={<Button href="#new" iconLeft={<Plus size={16} />}>New reconciliation</Button>}>
      Match incoming payments to open invoices and review journal entries before exporting them.
    </PageHeading>
    <div className="process-band">
      <div><span className="process-icon"><Upload size={18} /></span><div><small>01 / INGEST</small><strong>Import bank and AR files</strong></div></div>
      <div><span className="process-icon"><ClipboardCheck size={18} /></span><div><small>02 / REVIEW</small><strong>Verify proposed matches</strong></div></div>
      <div><span className="process-icon"><ArrowDownToLine size={18} /></span><div><small>03 / EXPORT</small><strong>Download approved journals</strong></div></div>
    </div>
    <Card className="panel">
      <CardHeader className="panel-heading"><div><h2>Reconciliation runs</h2><p>Open a saved run to review transactions and see its decision history.</p></div></CardHeader>
      <ErrorBanner error={runs.error} />
      {!runs.data && !runs.error && <Loading />}
      {runs.data?.length > 0 && <div className="table-wrap"><Table columns={columns} rows={runs.data} getRowKey={run => run.id} /></div>}
      {runs.data?.length === 0 && offset === 0 && <CardBody>
        <EmptyState title="No reconciliation runs yet" action={<Button href="#new" variant="ghost" iconRight={<ArrowRight size={15} />}>Create your first run</Button>}>
          Import a bank statement and an open invoice ledger to get started.
        </EmptyState>
      </CardBody>}
      {(offset > 0 || runs.data?.length === 25) && <CardBody className="actions">
        <Button variant="ghost" disabled={offset === 0} onClick={() => setOffset(offset - 25)}>Previous</Button>
        <Button variant="ghost" disabled={runs.data?.length !== 25} onClick={() => setOffset(offset + 25)}>Next</Button>
      </CardBody>}
    </Card>
    <Card className="demo-card">
      <span className="process-icon"><FlaskConical size={18} /></span>
      <div><h2>Explore a sample run</h2><p>See a worked example with sample bank and invoice data.</p></div>
      <div className="actions">
        <Select aria-label="Sample statement format" value={demoFormat} onChange={event => setDemoFormat(event.target.value)}>
          {Object.entries(metadata.demo_formats).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </Select>
        <Button variant="ghost" href={`#demo/${demoFormat}`} iconRight={<ArrowUpRight size={16} />}>Open sample</Button>
      </div>
    </Card>
  </>;
}

function TreatySelect({ rules, required = false }) {
  return <Field label="Treaty rule" controlId="treaty" required={required}
    hint="Uses the configured reference table for the selected corridor and service.">
    <Select id="treaty" name="treaty" required={required}>
      <option value="">{required ? 'Select a treaty rule' : 'Skip treaty screening'}</option>
      {rules.map(rule => <option key={`${rule.corridor_code}|${rule.service_category}`}
        value={`${rule.corridor_code}|${rule.service_category}`}>
        {rule.corridor_code} · {humanize(rule.service_category)}
      </option>)}
    </Select>
  </Field>;
}

function taxContext(value) {
  if (!value) return null;
  const [corridor_code, service_category] = value.split('|');
  return { corridor_code, service_category };
}

function UploadField({ name, label, hint, accept, required }) {
  return <Field label={label} hint={hint} controlId={name} required={required}>
    <Input className="file" type="file" id={name} name={name} accept={accept} required={required} />
  </Field>;
}

async function fileText(form, field) {
  const file = form.get(field);
  if (file.size > 2_000_000) throw new Error(`${file.name} exceeds the 2 MB file limit.`);
  return file.size ? file.text() : '';
}

function NewRun({ metadata }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const submission = useRef(null);
  async function submit(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const fields = ['statement_content', 'invoices_csv', 'credit_memos_csv', 'remittance_emails_text'];
    const list = key => data.get(key).split(',').map(value => value.trim()).filter(Boolean);
    setError(null);
    setBusy(true);
    try {
      const files = await Promise.all(fields.map(field => fileText(data, field)));
      const accounts = Object.fromEntries(Object.entries(metadata.accounts).flatMap(([code, name]) => {
        const account = { code: data.get(`code_${code}`).trim(), name: data.get(`name_${code}`).trim() };
        return account.code === code && account.name === name ? [] : [[code, account]];
      }));
      const payload = {
        ...Object.fromEntries(fields.map((field, index) => [field, files[index]])),
        name: data.get('name'),
        statement_format: data.get('statement_format'),
        fallback_currency: data.get('fallback_currency').trim().toUpperCase() || null,
        fallback_booking_date: data.get('fallback_booking_date') || null,
        allowed_discount_pcts: list('allowed_discount_pcts'),
        allowed_tds_pcts: list('allowed_tds_pcts'),
        common_wire_fees: list('common_wire_fees'),
        tax_context: taxContext(data.get('treaty')),
        accounts,
        netsuite_subsidiary: data.get('netsuite_subsidiary'),
        netsuite_department: data.get('netsuite_department'),
        xero_tax_rate: data.get('xero_tax_rate'),
      };
      const serialized = JSON.stringify(payload);
      if (submission.current?.serialized !== serialized) {
        submission.current = { serialized, id: crypto.randomUUID() };
      }
      const run = await post('/runs', { ...payload, submission_id: submission.current.id });
      location.hash = `run/${run.id}`;
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return <>
    <Button href="#runs" variant="quiet" size="sm" iconLeft={<ArrowLeft size={15} />}>All runs</Button>
    <PageHeading eyebrow="Import / new run" title="New reconciliation">
      Upload UTF-8 files and choose the policies for this batch. Review proposals after the engine finishes.
    </PageHeading>
    <form className="stack" onSubmit={submit}>
      <Card className="panel">
        <CardHeader className="panel-heading"><h2>Batch and input files</h2></CardHeader>
        <CardBody className="form-grid">
          <Field label="Run name" controlId="name" required><Input id="name" name="name" maxLength={120} required autoFocus /></Field>
          <Field label="Statement format" controlId="statement_format"><Select id="statement_format" name="statement_format">
            {Object.entries(metadata.statement_formats).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </Select></Field>
          <UploadField name="statement_content" label="Bank statement" hint="ISO 20022 XML, MT940, BAI2 or bank CSV" accept=".xml,.txt,.csv,.mt940,.bai,.bai2,.sta,.940,.dat" required />
          <UploadField name="invoices_csv" label="Open invoice ledger" hint="CSV with invoice IDs, customer information, balances and currency" accept=".csv" required />
          <UploadField name="credit_memos_csv" label="Credit memos" hint="Optional approved credit memo CSV" accept=".csv" />
          <UploadField name="remittance_emails_text" label="Remittance advice" hint="Optional plain text" accept=".txt,.eml" />
          <Field label="Fallback currency" controlId="fallback_currency" hint="Three-letter code used where currency is missing.">
            <Input name="fallback_currency" id="fallback_currency" pattern="[A-Za-z]{3}" placeholder="e.g. EUR" />
          </Field>
          <Field label="Fallback booking date" controlId="fallback_booking_date" hint="Used for statement entries without a date.">
            <Input type="date" id="fallback_booking_date" name="fallback_booking_date" />
          </Field>
        </CardBody>
      </Card>
      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Matching policy</h2><p>Enter comma-separated values for additional solver candidates.</p></div></CardHeader>
        <CardBody className="form-grid">
          <Field label="Discount rates (%)" controlId="discount"><Input id="discount" name="allowed_discount_pcts" /></Field>
          <Field label="Withholding rates (%)" controlId="withholding"><Input id="withholding" name="allowed_tds_pcts" /></Field>
          <Field label="Wire fees (currency units)" controlId="fees"><Input id="fees" name="common_wire_fees" /></Field>
          <TreatySelect rules={metadata.treaty_rules} />
        </CardBody>
      </Card>
      <Card className="panel">
        <details className="settings">
          <summary>Chart of accounts and ERP settings</summary>
          <div className="form-grid">
            <Field label="NetSuite subsidiary" controlId="subsidiary"><Input id="subsidiary" name="netsuite_subsidiary" maxLength={120} /></Field>
            <Field label="NetSuite department" controlId="department"><Input id="department" name="netsuite_department" maxLength={120} /></Field>
            <Field label="Xero tax rate label" controlId="xero_tax_rate"><Input id="xero_tax_rate" name="xero_tax_rate" maxLength={120} /></Field>
          </div>
          <div className="account-grid">
            {Object.entries(metadata.accounts).map(([code, name]) => <div className="account-row" key={code}>
              <span>{name}</span>
              <Input aria-label={`${name} account code`} name={`code_${code}`} defaultValue={code} maxLength={120} />
              <Input aria-label={`${name} account name`} name={`name_${code}`} defaultValue={name} maxLength={120} />
            </div>)}
          </div>
        </details>
      </Card>
      <ErrorBanner error={error} />
      <div className="actions"><Button type="submit" loading={busy} disabled={busy} iconRight={<ArrowRight size={16} />}>Run reconciliation</Button>
        <Button href="#runs" variant="quiet">Cancel</Button></div>
    </form>
  </>;
}

function AuditResult({ audit, currency }) {
  const labels = {
    COMPLIANT_TREATY_RATE: ['Within reference tolerance', 'ok'],
    OVERWITHHELD_MISSING_DOCS: ['Above reference rate', 'warn'],
    UNDERWITHHELD_AUDIT_RISK: ['Below reference rate', 'warn'],
  };
  const [label, tone] = labels[audit.status];
  return <div className="audit-result">
    <div className="actions"><Badge tone={tone}>{label}</Badge><span>{audit.corridor_code} · {humanize(audit.service_category)}</span></div>
    <p>{audit.actual_withheld_pct}% withheld against a {audit.expected_treaty_pct}% reference rate.</p>
    {audit.excess_overwithheld_amount > 0 && <p>Above reference by {currency
      ? money(audit.excess_overwithheld_amount, currency) : audit.excess_overwithheld_amount.toLocaleString()}.</p>}
    <p><strong>Reference documents</strong> {audit.required_forms.join(', ')}.</p>
  </div>;
}

function TaxScreen({ metadata }) {
  const [error, setError] = useState(null);
  const [audit, setAudit] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setError(null);
    setAudit(null);
    setBusy(true);
    try {
      setAudit(await post('/tax-audit', {
        ...taxContext(data.get('treaty')),
        gross_amount: data.get('gross'),
        withheld_amount: data.get('withheld'),
      }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return <>
    <PageHeading eyebrow="Withholding review" title="Treaty screening">
      Compare a withholding amount against the configured reference rate for a selected corridor and service.
    </PageHeading>
    <Card className="panel">
      <CardBody><form className="stack" onSubmit={submit}>
        <div className="form-grid">
          <TreatySelect rules={metadata.treaty_rules} required />
          <Field label="Gross amount" controlId="gross" required><Input id="gross" name="gross" type="number" min="0.01" step="0.01" required /></Field>
          <Field label="Withheld amount" controlId="withheld" required><Input id="withheld" name="withheld" type="number" min="0" step="0.01" required /></Field>
        </div>
        <div><Button type="submit" loading={busy} disabled={busy}>Compare rates</Button></div>
        <ErrorBanner error={error} />
        {audit && <AuditResult audit={audit} />}
      </form></CardBody>
    </Card>
    <Card className="panel">
      <CardHeader className="panel-heading"><h2>Configured treaty references</h2></CardHeader>
      <div className="table-wrap"><Table rows={metadata.treaty_rules} getRowKey={rule => rule.corridor_code + rule.service_category}
        columns={[
          { key: 'corridor_code', header: 'Corridor' },
          { key: 'service_category', header: 'Service', render: rule => humanize(rule.service_category) },
          { key: 'treaty_article', header: 'Reference' },
          { key: 'treaty_wht_pct', header: 'Rate', render: rule => `${rule.treaty_wht_pct}%`, align: 'right' },
        ]} /></div>
    </Card>
  </>;
}

function ReviewDecision({ proposal, run, update, reload }) {
  const review = getReview(run, proposal.tx_id);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function decide(decision) {
    setError(null);
    setBusy(true);
    try {
      update(await post(`/runs/${run.id}/reviews`, {
        tx_id: proposal.tx_id, decision, note, version: review?.version ?? 0,
      }));
      setNote('');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const unmatched = proposal.status === 'UNMATCHED_SUSPENSE';
  const noteRequired = proposal.status !== 'AUTO_RECONCILED';
  return <section className="review-box stack">
    <h3>Review decision</h3>
    {review && <p><strong>{review.decision === 'approved' ? 'Approved' : 'Rejected'}</strong> by {review.actor} · {timestamp(review.created_at)}</p>}
    {unmatched && <p>Resolve the missing match in a new run before exporting this payment.</p>}
    <Field label="Review note" controlId="review-note" hint="Required for exceptions and rejections.">
      <Textarea id="review-note" rows={2} value={note} onChange={event => setNote(event.target.value)} maxLength={1000} />
    </Field>
    <div className="actions">
      {!unmatched && <Button disabled={busy || review?.decision === 'approved' || (noteRequired && !note.trim())} onClick={() => decide('approved')}>Approve journal</Button>}
      <Button variant="ghost" disabled={busy || review?.decision === 'rejected' || !note.trim()} onClick={() => decide('rejected')}>Reject journal</Button>
      {error?.status === 409 && <Button variant="quiet" onClick={reload}>Reload reviews</Button>}
    </div>
    <ErrorBanner error={error} />
  </section>;
}

function TransactionDetail({ proposal, run, demo, update, reload }) {
  const tx = run.result.transactions.find(row => row.tx_id === proposal.tx_id);
  const currency = proposal.currency;
  const amount = (key, header) => ({ key, header, align: 'right', render: row => money(row[key], currency) });
  return <Card className="panel detail">
    <CardHeader className="panel-heading">
      <div><div className="eyebrow">Transaction detail</div><h2>{tx.payer_name}</h2><p>{tx.tx_id} · {tx.booking_date} · {tx.payment_rail}</p></div>
      <Status value={proposal.status} />
    </CardHeader>
    <CardBody className="stack">
      <div className="detail-metrics">
        <Stat label="Deposit" value={money(proposal.deposit_amount, currency)} />
        <Stat label="Proposed AR clearing" value={money(proposal.total_gross_invoices, currency)} />
        <Stat label="Unexplained amount" value={money(proposal.residual_unexplained, currency)} />
      </div>
      <p className="explanation">{proposal.explanation_summary}</p>
      {tx.raw_remittance_unstructured && <details><summary>Source remittance</summary><pre>{tx.raw_remittance_unstructured}</pre></details>}
      {proposal.allocations.length > 0 && <section><h3>Invoice allocations</h3>
        <div className="table-wrap"><Table rows={proposal.allocations} getRowKey={row => row.invoice_id}
          columns={[{ key: 'invoice_id', header: 'Invoice' }, amount('gross_amount', 'Open balance'), amount('net_settled', 'Applied cash')]} /></div>
      </section>}
      {proposal.deductions.length > 0 && <section><h3>Deductions</h3>
        <div className="table-wrap"><Table rows={proposal.deductions} getRowKey={(_, index) => index}
          columns={[{ key: 'description', header: 'Description' }, amount('amount', 'Amount'),
            { key: 'authorization', header: 'Classification', render: row => row.is_authorized ? 'Allowed' : 'Exception' }]} /></div>
      </section>}
      <section><h3>Proposed journal</h3>
        <div className="table-wrap"><Table rows={proposal.journal_entries} getRowKey={row => row.line_number}
          columns={[
            { key: 'account_name', header: 'Account', render: row => `${row.account_code} · ${row.account_name}` },
            amount('debit', 'Debit'), amount('credit', 'Credit'),
          ]} /></div>
      </section>
      {Object.hasOwn(run.result.tax_audits, tx.tx_id) && <AuditResult audit={run.result.tax_audits[tx.tx_id]} currency={currency} />}
      {proposal.dispute_notice_draft && <details><summary>Draft dispute notice</summary><pre>{proposal.dispute_notice_draft}</pre></details>}
      {!demo && <ReviewDecision proposal={proposal} run={run} update={update} reload={reload} />}
    </CardBody>
  </Card>;
}

function RunView({ id, demo, metadata }) {
  const path = demo ? `/sample?fmt=${encodeURIComponent(id)}` : `/runs/${encodeURIComponent(id)}`;
  const { data, error, update } = useResource(path);
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);
  const [refreshError, setRefreshError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  async function reload() {
    setRefreshError(null);
    setRefreshing(true);
    try {
      update(await api(path));
    } catch (err) {
      setRefreshError(err);
    } finally {
      setRefreshing(false);
    }
  }
  if (error) return <ErrorBanner error={error} />;
  if (!data) return <Loading />;
  const run = demo ? { result: data, name: metadata.demo_formats[id], reviews: {} } : data;
  const { proposals, summary } = run.result;
  const visible = proposals.filter(p => (!filter || p.status === filter)
    && `${p.tx_id} ${p.matched_customer_name}`.toLowerCase().includes(search.trim().toLowerCase()));
  const proposal = visible.find(p => p.tx_id === selected) ?? visible[0];
  const approved = proposals.filter(p => getReview(run, p.tx_id)?.decision === 'approved');
  const currencies = [...new Set(approved.map(p => p.currency))].sort();
  const balances = Object.entries(summary.totals_by_currency).map(([currency, amounts]) => ({ currency, ...amounts }));
  return <>
    <Button href="#runs" variant="quiet" size="sm" iconLeft={<ArrowLeft size={15} />}>All runs</Button>
    <PageHeading eyebrow={demo ? 'Sample / read only' : 'Reconciliation run'} title={run.name}
      action={!demo && <Button variant="ghost" onClick={reload} loading={refreshing} disabled={refreshing}>Refresh reviews</Button>}>
      {demo ? 'Sample transactions and journal proposals' : `Created by ${run.created_by} · ${timestamp(run.created_at)}`}
    </PageHeading>
    <ErrorBanner error={refreshError} />
    <div className="metrics">
      <Stat label="Transactions" value={summary.total_transactions} />
      <Stat label="Matched" value={summary.auto_reconciled_count} />
      <Stat label="Exceptions" value={summary.action_required_dispute_count} />
      <Stat label={demo ? 'Unmatched' : 'Approved for export'} value={demo ? summary.unmatched_count : approved.length} />
    </div>
    <Card className="panel">
      <CardHeader className="panel-heading"><h2>Batch totals by currency</h2></CardHeader>
      <div className="table-wrap"><Table rows={balances} getRowKey={row => row.currency}
        columns={[
          { key: 'currency', header: 'Currency' },
          { key: 'total_deposit_cash', header: 'Incoming cash', align: 'right', render: row => money(row.total_deposit_cash, row.currency) },
          { key: 'total_gross_ar_cleared', header: 'Proposed AR clearing', align: 'right', render: row => money(row.total_gross_ar_cleared, row.currency) },
          { key: 'total_deductions_resolved', header: 'Deductions', align: 'right', render: row => money(row.total_deductions_resolved, row.currency) },
        ]} /></div>
    </Card>
    <div className="review-layout">
      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Transactions</h2><p>{visible.length} of {proposals.length} shown</p></div></CardHeader>
        <CardBody className="stack">
          <Input type="search" aria-label="Search transactions" placeholder="Search transaction or customer" value={search} onChange={event => setSearch(event.target.value)} />
          <Select aria-label="Match status" value={filter} onChange={event => setFilter(event.target.value)}>
            <option value="">All match statuses</option>
            {Object.entries(statuses).map(([key, [label]]) => <option key={key} value={key}>{label}</option>)}
          </Select>
          <div className="tx-list">
            {visible.map(p => {
              const review = getReview(run, p.tx_id);
              return <button className="tx" type="button" key={p.tx_id} aria-pressed={p.tx_id === proposal?.tx_id} onClick={() => setSelected(p.tx_id)}>
                <span className="tx-top"><strong>{p.matched_customer_name}</strong><span>{money(p.deposit_amount, p.currency)}</span></span>
                <span className="tx-bottom"><span>{p.tx_id}</span><Status value={p.status} />{review && <Badge>{review.decision}</Badge>}</span>
              </button>;
            })}
          </div>
          {!visible.length && <EmptyState title="No transactions match these filters" />}
        </CardBody>
      </Card>
      {proposal && <TransactionDetail key={proposal.tx_id} proposal={proposal} run={run} demo={demo} update={update} reload={reload} />}
    </div>
    {!demo && <>
      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Journal exports</h2><p>Download approved journals by currency.</p></div></CardHeader>
        <CardBody className="stack">
          {!approved.length && <p>Approve a journal to enable exports.</p>}
          {currencies.map(currency => <div key={currency} className="actions">
            <Badge>{currency}</Badge>
            {Object.entries(metadata.export_formats).map(([fmt, label]) => <Button key={fmt} variant="ghost" size="sm"
              href={`/api/runs/${run.id}/exports/${fmt}?currency=${currency}`} download iconLeft={<ArrowDownToLine size={15} />}>{label}</Button>)}
          </div>)}
        </CardBody>
      </Card>
      <Card className="panel">
        <CardHeader className="panel-heading"><h2>Review history</h2></CardHeader>
        {run.review_history.length > 0 ? <div className="table-wrap"><Table rows={[...run.review_history].reverse()}
          getRowKey={row => `${row.tx_id}:${row.version}`}
          columns={[
            { key: 'tx_id', header: 'Transaction' }, { key: 'decision', header: 'Decision' },
            { key: 'actor', header: 'Operator' }, { key: 'note', header: 'Note' },
            { key: 'created_at', header: 'Recorded', render: row => timestamp(row.created_at) },
          ]} /></div> : <CardBody><p>No decisions have been recorded.</p></CardBody>}
      </Card>
    </>}
  </>;
}

function App() {
  const metadata = useResource('/workspace');
  const [route, setRoute] = useState(location.hash.slice(1) || 'runs');
  useEffect(() => {
    function navigate() {
      setRoute(location.hash.slice(1) || 'runs');
      window.scrollTo(0, 0);
    }
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  const [page, id] = route.split('/');
  return <div className="shell">
    <a className="skip" href="#main-content" onClick={event => {
      event.preventDefault();
      document.getElementById('main-content').focus();
    }}>Skip to content</a>
    <Sidebar className="workspace-sidebar" heading={
      <a href="#runs" className="brand"><Layers3 size={22} aria-hidden="true" /><span>ClearRemit<small>Receivables workspace</small></span></a>
    }>
      <nav aria-label="Workspace">
        <a href="#runs" aria-current={page !== 'tax' ? 'page' : undefined}><span><FileSpreadsheet size={17} aria-hidden="true" /> Reconciliation</span></a>
        <a href="#tax" aria-current={page === 'tax' ? 'page' : undefined}><span><Scale size={17} aria-hidden="true" /> Treaty screening</span></a>
      </nav>
      <div className="sidebar-foot muted"><Banknote size={17} aria-hidden="true" /> Finance operations</div>
    </Sidebar>
    <main id="main-content" className="main stack" tabIndex={-1}>
      <ErrorBanner error={metadata.error} />
      {!metadata.data && !metadata.error && <Loading />}
      {metadata.data && (page === 'new' ? <NewRun metadata={metadata.data} />
        : page === 'tax' ? <TaxScreen metadata={metadata.data} />
        : (page === 'run' || page === 'demo') && id ? <RunView key={route} id={id} demo={page === 'demo'} metadata={metadata.data} />
        : <Dashboard metadata={metadata.data} />)}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<ThemeProvider defaultTheme="light" forcedTheme="light"><App /></ThemeProvider>);
