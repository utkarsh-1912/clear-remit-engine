import React, { useEffect, useRef, useState } from 'react';
import {
  Badge, Button, Card, CardBody, CardHeader, DataTable, Dialog, EmptyState, Field,
  Input, Select, Stat, Textarea,
} from '@utkristi/ui';
import { api, humanize, money, post, timestamp } from './api';

export function useOperations(entityId) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const requestNumber = useRef(0);
  const refresh = async () => {
    const current = ++requestNumber.current;
    setError(null);
    try {
      const result = await api(`/entities/${encodeURIComponent(entityId)}/operations`);
      if (current === requestNumber.current) setData(result);
    } catch (err) {
      if (current === requestNumber.current) setError(err);
    }
  };
  useEffect(() => {
    setData(null);
    refresh();
    return () => { requestNumber.current += 1; };
  }, [entityId]);
  return { data, error, refresh };
}

export function Message({ error }) {
  return error ? <div role="alert" className="error">{error.message}</div> : null;
}

function Panel({ title, action, children }) {
  return <Card className="panel">
    <CardHeader className="panel-heading"><h2>{title}</h2>{action}</CardHeader>
    <CardBody>{children}</CardBody>
  </Card>;
}

function Header({ title, description, action }) {
  return <header className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{action}</header>;
}

function Grid({ rows, columns, emptyMessage = 'No records yet', ...props }) {
  return <DataTable rows={rows} columns={columns} getRowKey={row => row.id ?? `${row.invoice_id ?? row.tx_id}:${row.currency}`}
    density="compact" pageSize={10} pageSizeOptions={[10, 25, 50]} columnVisibility={{}}
    emptyMessage={emptyMessage} noResultsMessage="No records match your search" {...props} />;
}

export function Overview({ entity, session }) {
  const state = useOperations(entity.id);
  if (!state.data) return <><Message error={state.error} /><p role="status">Loading operations…</p></>;
  const { payments, invoices, cases, batches } = state.data;
  const openCases = cases.filter(item => item.status !== 'resolved');
  const active = batches.filter(batch => batch.status !== 'rejected');
  const posted = new Set(active.filter(b => b.status === 'confirmed').flatMap(b => b.tx_ids.map(tx => b.run_id + tx)));
  const cash = {};
  for (const payment of payments) {
    const bucket = cash[payment.currency] ??= { id: payment.currency, currency: payment.currency, received: 0, applied: 0 };
    bucket.received += payment.deposit_amount;
    if (posted.has(payment.run_id + payment.tx_id)) bucket.applied += payment.deposit_amount;
  }
  const aging = {};
  const now = new Date();
  const today = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-');
  for (const invoice of invoices) {
    const bucket = aging[invoice.currency] ??= { id: invoice.currency, currency: invoice.currency, current: 0, late30: 0, late60: 0, late90: 0, older: 0, undated: 0 };
    const days = invoice.due_date ? Math.floor((Date.parse(today) - Date.parse(invoice.due_date)) / 86400000) : null;
    const key = days === null || Number.isNaN(days) ? 'undated' : days <= 0 ? 'current' : days <= 30 ? 'late30' : days <= 60 ? 'late60' : days <= 90 ? 'late90' : 'older';
    bucket[key] += invoice.outstanding_amount;
  }
  return <>
    <Header title="Operations overview" description={entity.organization_name + ' · ' + entity.name}
      action={['admin', 'analyst'].includes(session.role) && <Button href="#new">Import and reconcile</Button>} />
    <Message error={state.error} />
    <div className="metrics">
      <Stat label="Reconciliation runs" value={state.data.runs_count} />
      <Stat label="Payments" value={payments.length} />
      <Stat label="Open cases" value={openCases.length} />
      <Stat label="Awaiting ERP receipt" value={batches.filter(b => b.status === 'prepared').length} />
    </div>
    {!payments.length && <EmptyState title="Start with your bank and receivables data"
      action={<Button href="#new" variant="ghost">Create first reconciliation</Button>}>
      Set matching and approval policies in Administration, then import a statement and an opening invoice ledger.
    </EmptyState>}
    <Panel title="Cash application by currency"><Grid rows={Object.values(cash)} columns={[
      { key: 'currency', header: 'Currency' },
      ...['received', 'applied'].map(key => ({ key, header: key === 'received' ? 'Imported cash' : 'ERP confirmed cash',
        render: row => money(row[key], row.currency), align: 'right', sortValue: row => row[key] })),
    ]} /></Panel>
    <Panel title="Receivables aging"><Grid rows={Object.values(aging)} columns={[
      { key: 'currency', header: 'Currency' },
      ...[['current', 'Current'], ['late30', '1–30 days'], ['late60', '31–60 days'], ['late90', '61–90 days'], ['older', '90+ days'], ['undated', 'No due date']]
        .map(([key, header]) => ({ key, header, align: 'right', render: row => money(row[key], row.currency) })),
    ]} /></Panel>
    <Panel title="Open work"><Grid rows={openCases} columns={[
      { key: 'title', header: 'Case' }, { key: 'kind', header: 'Type', render: row => humanize(row.kind) },
      { key: 'assignee', header: 'Owner' }, { key: 'due_date', header: 'Due' },
      { key: 'action', header: 'Open', render: () => <Button href="#cases" variant="quiet" size="sm">Open queue</Button> },
    ]} /></Panel>
  </>;
}

export function Ledger({ entity, session }) {
  const state = useOperations(entity.id);
  const [customer, setCustomer] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function create(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await post(`/entities/${entity.id}/collections`, {
        customer_id: customer.customer_id, title: form.get('title'), due_date: form.get('due') || null, note: form.get('note'),
      });
      setCustomer(null);
      await state.refresh();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <>
    <Header title="Customers and invoices" description="Opening invoice balances with reserved and confirmed journal allocations." />
    <Message error={state.error} />
    <Panel title="Invoice ledger"><Grid rows={state.data?.invoices ?? []} columns={[
      { key: 'invoice_id', header: 'Invoice', sortValue: row => row.invoice_id },
      { key: 'customer_name', header: 'Customer', sortValue: row => row.customer_name },
      { key: 'due_date', header: 'Due', sortValue: row => row.due_date },
      { key: 'open_amount', header: 'Opening balance', render: row => money(row.open_amount, row.currency), align: 'right' },
      { keyPunch: '', key: 'reserved_amount', header: 'Reserved / posted', render: row => money(row.reserved_amount, row.currency), align: 'right' },
      { key: 'remaining_amount', header: 'Available balance', render: row => money(row.remaining_amount, row.currency), align: 'right' },
      { key: 'actions', header: 'Actions', render: row => <div className="actions">
        {row.run_id && <Button href={`#run/${row.run_id}`} size="sm" variant="quiet">Source run</Button>}
        {row.registered && <Button href="#invoices" size="sm" variant="quiet">Invoice register</Button>}
        {session.role !== 'auditor' && <Button size="sm" variant="ghost" onClick={() => { setError(null); setCustomer(row); }}>Follow up</Button>}
      </div> },
    ]} /></Panel>
    <Dialog open={!!customer} onClose={() => setCustomer(null)} title="Create collection follow-up">
      {customer && <form onSubmit={create} className="stack">
        <p>{customer.customer_name} · {customer.invoice_id}</p>
        <Field label="Task title"><Input name="title" required maxLength={120} defaultValue={`Follow up on ${customer.invoice_id}`} /></Field>
        <Field label="Next action date"><Input name="due" type="date" /></Field>
        <Field label="Contact or promise-to-pay note"><Textarea name="note" required maxLength={2000} rows={3} /></Field>
        <Message error={error} /><Button type="submit" disabled={busy} loading={busy}>Create follow-up</Button>
      </form>}
    </Dialog>
  </>;
}

export function CaseQueue({ entity, session }) {
  const state = useOperations(entity.id);
  const [selected, setSelected] = useState(null);
  const [status, setStatus] = useState('active');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError(null);
    try {
      await post(`/entities/${entity.id}/cases/${selected.id}`, {
        version: selected.version, status: form.get('status'), assignee: form.get('assignee'),
        due_date: form.get('due') || null, note: form.get('note'),
      });
      setSelected(null); await state.refresh();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const rows = (state.data?.cases ?? []).filter(row => status === 'all' || row.status !== 'resolved');
  return <>
    <Header title="Exceptions and collections" description="Assign owners, collect supporting information, and record the resolution." />
    <Message error={state.error} />
    <Panel title="Work queue"><Grid rows={rows} toolbar={
      <Select aria-label="Case filter" value={status} onChange={event => setStatus(event.target.value)}>
        <option value="active">Active cases</option><option value="all">All cases</option>
      </Select>
    } columns={[
      { key: 'title', header: 'Case' }, { key: 'kind', header: 'Type', render: row => humanize(row.kind) },
      { key: 'status', header: 'Status', render: row => <Badge tone={row.status === 'resolved' ? 'ok' : 'warn'}>{humanize(row.status)}</Badge> },
      { key: 'assignee', header: 'Owner' }, { key: 'due_date', header: 'Due', sortValue: row => row.due_date },
      { key: 'actions', header: 'Actions', render: row => <div className="actions">
        {session.role !== 'auditor' && <Button size="sm" variant="ghost" onClick={() => { setError(null); setSelected(row); }}>Update case</Button>}
        {row.run_id && <Button href={`#run/${row.run_id}`} size="sm" variant="quiet">Review payment</Button>}
      </div> },
    ]} /></Panel>
    <Dialog open={!!selected} onClose={() => setSelected(null)} title={selected?.title ?? 'Case'}>
      {selected && <form className="stack" onSubmit={save}>
        <Field label="Status"><Select name="status" defaultValue={selected.status}>
          {['open', 'investigating', 'waiting_customer', 'resolved'].map(value => <option key={value} value={value}>{humanize(value)}</option>)}
        </Select></Field>
        <Field label="Owner"><Input name="assignee" maxLength={120} defaultValue={selected.assignee} /></Field>
        <Field label="Next action date"><Input name="due" type="date" defaultValue={selected.due_date} /></Field>
        <Field label="Evidence or resolution note"><Textarea name="note" maxLength={2000} rows={4} defaultValue={selected.note} /></Field>
        <Message error={error} />
        <Button type="submit" disabled={busy} loading={busy}>Save case</Button>
        {error?.status === 409 && <Button variant="quiet" onClick={() => { setSelected(null); state.refresh(); }}>Reload queue</Button>}
      </form>}
    </Dialog>
  </>;
}

export function ManualAllocation({ proposal, run, update, session }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState([{ invoice_id: '', amount: '' }]);
  const invoices = run.result.invoices.filter(invoice => invoice.currency === proposal.currency);
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      update(await post(`/runs/${run.id}/resolve`, {
        tx_id: proposal.tx_id, revision: run.revision, note: new FormData(event.currentTarget).get('note'), allocations: rows,
      }));
      setOpen(false);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  if (!['admin', 'analyst'].includes(session.role)) return null;
  return <>
    <Button variant="ghost" onClick={() => { setError(null); setRows([{ invoice_id: '', amount: '' }]); setOpen(true); }}>Allocate received cash</Button>
    <Dialog open={open} onClose={() => setOpen(false)} title="Allocate payment to invoices" wide>
      <form className="stack" onSubmit={save}>
        <p>Received {money(proposal.deposit_amount, proposal.currency)}. Enter cash amounts to apply. The resulting journal requires approval.</p>
        {rows.map((row, index) => <div className="allocation-row" key={index}>
          <Field label={`Invoice ${index + 1}`}><Select required value={row.invoice_id} onChange={event => setRows(rows.map((item, i) => i === index ? { ...item, invoice_id: event.target.value } : item))}>
            <option value="">Select invoice</option>
            {invoices.map(invoice => <option key={invoice.invoice_id} value={invoice.invoice_id}>{invoice.invoice_id} · {invoice.customer_name} · {money(invoice.open_amount, invoice.currency)}</option>)}
          </Select></Field>
          <Field label={`Cash amount ${index + 1}`}><Input required type="number" min=".01" step=".01" value={row.amount} onChange={event => setRows(rows.map((item, i) => i === index ? { ...item, amount: event.target.value } : item))} /></Field>
          {rows.length > 1 && <Button variant="quiet" onClick={() => setRows(rows.filter((_, i) => i !== index))}>Remove</Button>}
        </div>)}
        <div><Button variant="quiet" disabled={rows.length >= 100} onClick={() => setRows([...rows, { invoice_id: '', amount: '' }])}>Add invoice</Button></div>
        <Field label="Reason and evidence"><Textarea name="note" required maxLength={2000} rows={3} /></Field>
        <Message error={error} /><Button disabled={busy} loading={busy} type="submit">Save allocation for review</Button>
      </form>
    </Dialog>
  </>;
}

export function ExportCenter({ entity, session }) {
  const state = useOperations(entity.id);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function receipt(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await post(`/export-batches/${selected.id}/receipt`, {
        status: form.get('status'), receipt: form.get('receipt'), version: selected.version,
      });
      setSelected(null); await state.refresh();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <>
    <Header title="ERP handoff" description="Prepare a batch from an approved run, download the journal, then record the ERP import receipt." />
    <Message error={state.error} />
    <Panel title="Export batches"><Grid rows={state.data?.batches ?? []} columns={[
      { key: 'created_at', header: 'Prepared', render: row => timestamp(row.created_at), sortValue: row => row.created_at },
      { key: 'format', header: 'ERP' }, { key: 'currency', header: 'Currency' },
      { key: 'status', header: 'Status', render: row => <Badge tone={row.status === 'confirmed' ? 'ok' : row.status === 'rejected' ? 'bad' : 'warn'}>{row.status}</Badge> },
      { key: 'receipt', header: 'Receipt or error' },
      { key: 'actions', header: 'Actions', render: row => <div className="actions">
        {row.status !== 'rejected' && session.role !== 'analyst' && <Button href={`/api/export-batches/${row.id}/download`} download size="sm" variant="ghost">Download</Button>}
        {row.status === 'prepared' && ['admin', 'approver'].includes(session.role) && <Button size="sm" variant="ghost" onClick={() => { setError(null); setSelected(row); }}>Record receipt</Button>}
        <Button href={`#run/${row.run_id}`} size="sm" variant="quiet">Source run</Button>
      </div> },
    ]} /></Panel>
    <Dialog open={!!selected} onClose={() => setSelected(null)} title="ERP import result">
      {selected && <form className="stack" onSubmit={receipt}>
        <Field label="Outcome"><Select name="status"><option value="confirmed">Imported successfully</option><option value="rejected">Import rejected</option></Select></Field>
        <Field label="ERP receipt reference or rejection detail"><Textarea name="receipt" required maxLength={2000} rows={3} /></Field>
        <Message error={error} /><Button type="submit" disabled={busy} loading={busy}>Record outcome</Button>
      </form>}
    </Dialog>
  </>;
}

export function PrepareExport({ run, formats, update, session }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const submission = useRef(null);
  const currencies = [...new Set(run.result.proposals.filter(p => run.reviews[p.tx_id]?.decision === 'approved').map(p => p.currency))];
  async function prepare(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const form = new FormData(event.currentTarget);
    const payload = { format: form.get('format'), currency: form.get('currency') };
    const key = JSON.stringify(payload);
    if (submission.current?.key !== key) submission.current = { key, id: crypto.randomUUID() };
    try {
      await post(`/runs/${run.id}/export-batches`, { ...payload, submission_id: submission.current.id });
      submission.current = null;
      update(await api(`/runs/${run.id}`));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <div className="stack">
    {currencies.length > 0 && ['admin', 'approver'].includes(session.role) && <form className="actions" onSubmit={prepare}>
      <Select name="format" aria-label="ERP format">{Object.entries(formats).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Select>
      <Select name="currency" aria-label="Export currency">{currencies.map(currency => <option key={currency}>{currency}</option>)}</Select>
      <Button type="submit" disabled={busy} loading={busy}>Prepare export batch</Button>
    </form>}
    <Message error={error} />
    {run.batches.length > 0 && <p>{run.batches.length} export batches recorded. <a href="#exports">Open ERP handoff</a> to download journals and record receipts.</p>}
    {!currencies.length && <p>Approve a journal to prepare an export.</p>}
  </div>;
}

export function AuditLog({ entity }) {
  const state = useOperations(entity.id);
  return <>
    <Header title="Audit trail" description="Recorded imports, allocation revisions, decisions, case updates, and ERP acknowledgments."
      action={<Button href={`/api/entities/${entity.id}/audit.csv`} download variant="ghost">Download audit CSV</Button>} />
    <Message error={state.error} />
    <Panel title="Activity"><Grid rows={state.data?.events ?? []} columns={[
      { key: 'created_at', header: 'Recorded', render: row => timestamp(row.created_at), sortValue: row => row.created_at },
      { key: 'actor', header: 'Operator' }, { key: 'action', header: 'Action' },
      { key: 'detail', header: 'Detail', filterValue: row => JSON.stringify(row.detail),
        render: row => <details><summary>View event</summary><pre>{JSON.stringify(row.detail, null, 2)}</pre></details> },
    ]} /></Panel>
  </>;
}

export function Administration({ entity, organizations, session, refreshEntities }) {
  const state = useOperations(entity.id);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event, action) {
    event.preventDefault(); setError(null); setNotice(''); setBusy(true);
    try { await action(new FormData(event.currentTarget)); setNotice('Saved successfully.'); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const admin = session.role === 'admin';
  const policy = entity.settings.policy ?? {};
  return <>
    <Header title="Administration" description={entity.organization_name + ' · ' + entity.name} />
    <Message error={error ?? state.error} />
    {notice && <p role="status">{notice}</p>}
    <Panel title="Workspace access"><p>Signed in as {session.username} with the {session.role} role.</p>
      <p>Organization access and named operator credentials are configured by the deployment administrator.</p></Panel>
    {admin && <Panel title="Matching and approval policy">
      <form className="stack" onSubmit={event => submit(event, async form => {
        const list = key => form.get(key).split(',').map(value => value.trim()).filter(Boolean);
        await post(`/entities/${entity.id}/settings`, {
          version: entity.version, separate_approval: form.get('separate') === 'yes',
          policy: {
            statement_content: '', invoices_csv: '',
            allowed_discount_pcts: list('discount'), allowed_tds_pcts: list('tax'), common_wire_fees: list('fee'),
            netsuite_subsidiary: form.get('subsidiary'), netsuite_department: form.get('department'),
            xero_tax_rate: form.get('xero'), accounts: policy.accounts ?? {},
          },
        });
        await refreshEntities();
      })}>
        <div className="form-grid">
          <Field label="Additional discount rates (%)"><Input name="discount" defaultValue={(policy.allowed_discount_pcts ?? []).join(', ')} /></Field>
          <Field label="Additional withholding rates (%)"><Input name="tax" defaultValue={(policy.allowed_tds_pcts ?? []).join(', ')} /></Field>
          <Field label="Additional wire fee amounts"><Input name="fee" defaultValue={(policy.common_wire_fees ?? []).join(', ')} /></Field>
          <Field label="Approval separation"><Select name="separate" defaultValue={entity.settings.separate_approval ? 'yes' : 'no'}>
            <option value="no">An authorized importer may approve</option><option value="yes">Require a different approver</option>
          </Select></Field>
          <Field label="NetSuite subsidiary"><Input name="subsidiary" defaultValue={policy.netsuite_subsidiary ?? ''} maxLength={120} /></Field>
          <Field label="NetSuite department"><Input name="department" defaultValue={policy.netsuite_department ?? ''} maxLength={120} /></Field>
          <Field label="Xero tax label"><Input name="xero" defaultValue={policy.xero_tax_rate ?? ''} maxLength={120} /></Field>
        </div>
        <Button type="submit" disabled={busy}>Save entity policy</Button>
      </form>
    </Panel>}
    {admin && <div className="form-grid">
      <Panel title="Add organization">
        <form className="stack" onSubmit={event => submit(event, async form => {
          await post('/organizations', { name: form.get('name'), mode: form.get('mode') }); await refreshEntities();
        })}>
          <Field label="Organization name"><Input name="name" required maxLength={120} /></Field>
          <Field label="Operating model"><Select name="mode">
            <option value="finance">Finance team</option><option value="accounting_firm">Accounting firm</option><option value="enterprise">Enterprise group</option>
          </Select></Field>
          <Button type="submit" disabled={busy}>Create organization</Button>
        </form>
      </Panel>
      <Panel title="Add client or legal entity">
        <form className="stack" onSubmit={event => submit(event, async form => {
          await post('/entities', { name: form.get('name'), organization_id: form.get('organization'), currency: form.get('currency').toUpperCase() });
          await refreshEntities();
        })}>
          <Field label="Organization"><Select name="organization" defaultValue={entity.organization_id}>
            {organizations.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}
          </Select></Field>
          <Field label="Client or legal entity name"><Input name="name" required maxLength={120} /></Field>
          <Field label="Default currency"><Input name="currency" required pattern="[A-Za-z]{3}" defaultValue={entity.currency} /></Field>
          <Button type="submit" disabled={busy}>Create entity</Button>
        </form>
      </Panel>
    </div>}
    {['admin', 'approver'].includes(session.role) && <Panel title="Accounting period close">
      <form className="stack" onSubmit={event => submit(event, async form => {
        await post(`/entities/${entity.id}/close`, { period: form.get('period'), note: form.get('note') });
        await state.refresh();
      })}>
        <p>Confirm ERP receipts for all payments in the period before closing it.</p>
        <div className="form-grid">
          <Field label="Period"><Input type="month" name="period" required /></Field>
          <Field label="Close note"><Input name="note" required maxLength={2000} /></Field>
        </div>
        <Button type="submit" variant="ghost" disabled={busy}>Close period</Button>
      </form>
      {(state.data?.periods ?? []).map(period => <p key={period.period}>{period.period} · closed by {period.actor} · {period.note}</p>)}
    </Panel>}
  </>;
}
