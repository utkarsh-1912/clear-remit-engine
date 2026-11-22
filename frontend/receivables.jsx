import React, { useEffect, useRef, useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, DataTable, Field, Input, Select, Table, Textarea } from '@utkristi/ui';
import { api, humanize, money, post } from './api';

function Panel({ title, children }) {
  return <Card className="panel">
    <CardHeader className="panel-heading"><h2>{title}</h2></CardHeader>
    <CardBody className="stack">{children}</CardBody>
  </Card>;
}

function Feedback({ error, notice }) {
  return error ? <div className="error" role="alert">{error.message}</div>
    : notice ? <p role="status">{notice}</p> : null;
}

function InvoiceLines({ invoice }) {
  return <Table rows={invoice.lines} getRowKey={(_, index) => index} columns={[
    { key: 'description', header: 'Description' },
    { key: 'quantity', header: 'Quantity' },
    { key: 'unit_price', header: 'Unit price', render: row => money(row.unit_price, invoice.currency) },
    { key: 'amount', header: 'Amount', render: row => money(row.amount, invoice.currency) },
  ]} />;
}

export function Receivables({ entity, session }) {
  const base = `/entities/${entity.id}`;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [share, setShare] = useState('');
  const [smtp, setSmtp] = useState(false);
  const deliveryAttempts = useRef(new Map());
  const [lineCount, setLineCount] = useState(1);
  const canWrite = ['admin', 'analyst'].includes(session.role);
  useEffect(() => {
    const controller = new AbortController();
    api(base + '/receivables', { signal: controller.signal }).then(setData)
      .catch(err => { if (!controller.signal.aborted) setError(err); });
    api(base + '/integrations', { signal: controller.signal }).then(result => setSmtp(result.smtp))
      .catch(() => {});
    return () => controller.abort();
  }, [base]);

  async function save(action, event) {
    event?.preventDefault();
    const form = event?.currentTarget;
    setBusy(true);
    setError(null);
    setNotice('');
    setShare('');
    try {
      const feedback = await action(form ? new FormData(form) : null);
      if (form) form.reset();
      setData(await api(base + '/receivables'));
      setNotice(typeof feedback === 'string' ? feedback : 'Saved.');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <header className="page-heading"><div><h1>Invoice register</h1><p>{entity.name}</p></div>
      {canWrite && <Button href="#new">Reconcile payments</Button>}
    </header>
    <Feedback error={error} notice={notice} />
    {share && <Panel title="Customer access link">
      <Field label="Share privately with the customer"><Input readOnly value={share} /></Field>
      <Button onClick={async () => {
        try { await navigator.clipboard.writeText(share); setNotice('Customer link copied.'); }
        catch (err) { setError(err); }
      }}>Copy link</Button>
    </Panel>}
    {!data && !error && <p role="status">Loading invoice register…</p>}
    {data && <>
      {canWrite && <div className="form-grid">
        <Panel title="Add customer">
          <form className="stack" onSubmit={event => save(form => post(base + '/customers', Object.fromEntries(form)), event)}>
            <Field label="Customer name"><Input name="name" required maxLength={120} /></Field>
            <Field label="Billing email"><Input name="email" type="email" maxLength={254} /></Field>
            <Button type="submit" disabled={busy}>Add customer</Button>
          </form>
        </Panel>
        <Panel title="Draft invoice">
          <form className="stack" onSubmit={event => save(async form => {
            const lines = Array.from({ length: lineCount }, (_, i) => ({
              description: form.get(`description${i}`), quantity: form.get(`quantity${i}`), unit_price: form.get(`price${i}`),
            }));
            await post(base + '/invoices', {
              customer_id: form.get('customer'), number: form.get('number'), currency: form.get('currency').toUpperCase(),
              issued_on: form.get('issued'), due_on: form.get('due'), lines,
            });
            setLineCount(1);
          }, event)}>
            <Field label="Customer"><Select name="customer" required>
              <option value="">Select customer</option>
              {data.customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select></Field>
            <div className="form-grid">
              <Field label="Invoice number"><Input name="number" required maxLength={120} /></Field>
              <Field label="Currency"><Input name="currency" required pattern="[A-Za-z]{3}" defaultValue={entity.currency} /></Field>
              <Field label="Issue date"><Input name="issued" type="date" required /></Field>
              <Field label="Due date"><Input name="due" type="date" required /></Field>
            </div>
            {Array.from({ length: lineCount }, (_, i) => <div className="form-grid" key={i}>
              <Field label={`Line ${i + 1} description`}><Input required maxLength={120} name={`description${i}`} /></Field>
              <Field label="Quantity"><Input required type="number" min=".001" step=".001" defaultValue="1" name={`quantity${i}`} /></Field>
              <Field label="Unit price"><Input required type="number" min=".01" step=".01" name={`price${i}`} /></Field>
            </div>)}
            <div className="actions">
              <Button type="button" variant="ghost" disabled={busy || lineCount >= 100} onClick={() => setLineCount(lineCount + 1)}>Add line</Button>
              {lineCount > 1 && <Button type="button" variant="quiet" onClick={() => setLineCount(lineCount - 1)}>Remove last line</Button>}
              <Button type="submit" disabled={busy || !data.customers.length}>Save draft</Button>
            </div>
          </form>
        </Panel>
      </div>}
      <Panel title="Invoices">
        <DataTable rows={data.invoices} getRowKey={row => row.id} emptyMessage="No invoices in this entity" columns={[
          { key: 'number', header: 'Invoice' }, { key: 'customer_name', header: 'Customer' },
          { key: 'due_on', header: 'Due', sortValue: row => row.due_on },
          { key: 'status', header: 'Status', render: row => <Badge>{row.status === 'issued' && Number(row.balance) === 0 ? 'paid' : row.status}</Badge> },
          { key: 'total', header: 'Total', render: row => money(row.total, row.currency) },
          { key: 'balance', header: 'Outstanding', render: row => money(row.balance, row.currency) },
          { key: 'actions', header: 'Actions', render: row => <div className="actions">
            <details><summary>Line items</summary><InvoiceLines invoice={row} /></details>
            {canWrite && row.status === 'draft' && ['issue', 'void'].map(action =>
              <Button key={action} disabled={busy} variant="ghost" size="sm" onClick={() => save(() => post(`${base}/invoices/${row.id}/${action}`, {}))}>
                {action === 'issue' ? 'Issue' : 'Void draft'}
              </Button>)}
            {canWrite && smtp && row.status === 'issued' && <Button variant="ghost" size="sm" disabled={busy}
              onClick={() => save(async () => {
                const attempt = deliveryAttempts.current.get(row.id) ?? crypto.randomUUID();
                deliveryAttempts.current.set(row.id, attempt);
                const delivery = await post(`${base}/invoices/${row.id}/deliveries/${attempt}`, {});
                if (delivery.status !== 'sending') deliveryAttempts.current.delete(row.id);
                return delivery.status === 'accepted' ? 'The mail provider accepted the invoice email.'
                  : 'Delivery is unverified. Check the provider before resending.';
              })}>Email invoice</Button>}
          </div> },
        ]} />
      </Panel>
      <Panel title="Customers">
        <DataTable rows={data.customers} getRowKey={row => row.id} emptyMessage="No customers in this entity" columns={[
          { key: 'name', header: 'Customer' }, { key: 'email', header: 'Billing email' },
          { key: 'portal', header: 'Portal access', render: row => row.portal_enabled ? 'Enabled' : 'Disabled' },
          { key: 'actions', header: 'Actions', render: row => session.role === 'admin' && <div className="actions">
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => save(async () => {
              const { path } = await post(`${base}/customers/${row.id}/portal/rotate`, {});
              setShare(new URL(path, location.origin).href);
            })}>{row.portal_enabled ? 'Replace link' : 'Create link'}</Button>
            {row.portal_enabled && <Button size="sm" variant="quiet" disabled={busy}
              onClick={() => save(() => post(`${base}/customers/${row.id}/portal/revoke`, {}))}>Revoke link</Button>}
          </div> },
        ]} />
      </Panel>
    </>}
  </>;
}

export function Integrations({ entity }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    api(`/entities/${entity.id}/integrations`, { signal: controller.signal }).then(setData)
      .catch(err => { if (!controller.signal.aborted) setError(err); });
    return () => controller.abort();
  }, [entity.id]);
  const connectors = data ? [
    ['Bank import bridge', data.connectors.bank], ['Remittance intake bridge', data.connectors.remittance],
    ['ERP export and receipt bridge', data.connectors.erp], ['Stripe payment notifications', data.connectors.stripe],
    ['SMTP invoice email', data.smtp], ['SSO identity proxy', data.sso_proxy],
  ] : [];
  return <>
    <header className="page-heading"><div><h1>Integrations</h1><p>{entity.name}</p></div></header>
    <Feedback error={error} />
    {!data && !error && <p role="status">Loading integrations…</p>}
    {data && <>
      <Panel title="Configured connectors">
        <Table rows={connectors} getRowKey={row => row[0]} columns={[
          { key: 'name', header: 'Integration', render: row => row[0] },
          { key: 'status', header: 'Status', render: row => <Badge tone={row[1] ? 'ok' : 'neutral'}>{row[1] ? 'Configured' : 'Setup required'}</Badge> },
        ]} />
      </Panel>
      <Panel title="Provider events">
        <DataTable rows={data.events} getRowKey={row => `${row.source}:${row.external_id}`} columns={[
          { key: 'source', header: 'Source' }, { key: 'external_id', header: 'Provider reference' },
          { key: 'result', header: 'Case ID' }, { key: 'created_at', header: 'Received' },
        ]} />
      </Panel>
      <Panel title="Invoice email history">
        <DataTable rows={data.deliveries} getRowKey={row => row.id} columns={[
          { key: 'recipient', header: 'Recipient' }, { key: 'status', header: 'Outcome' },
          { key: 'created_at', header: 'Requested' },
        ]} />
      </Panel>
    </>}
  </>;
}

export function CustomerPortal() {
  const [token] = useState(() => location.hash.slice(1));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api('/portal', { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal, credentials: 'omit' })
      .then(setData).catch(err => { if (!controller.signal.aborted) setError(err); });
    return () => controller.abort();
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true);
    setNotice('');
    setError(null);
    const headers = { Authorization: `Bearer ${token}` };
    try {
      await api('/portal/requests', { method: 'POST', credentials: 'omit',
        headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      form.reset();
      setData(await api('/portal', { headers, credentials: 'omit' }));
      setNotice('Your update was submitted.');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return <main className="main stack">
    <header className="page-heading"><div><h1>Customer portal</h1>{data && <p>{data.customer}</p>}</div></header>
    <Feedback error={error} notice={notice} />
    {!data && !error && <p role="status">Loading your account…</p>}
    {data && <>
      <Panel title="Issued invoices">
        <DataTable rows={data.invoices} getRowKey={row => row.id} emptyMessage="No issued invoices" columns={[
          { key: 'number', header: 'Invoice' }, { key: 'issued_on', header: 'Issued' }, { key: 'due_on', header: 'Due' },
          { key: 'total', header: 'Total', render: row => money(row.total, row.currency) },
          { key: 'balance', header: 'Outstanding', render: row => money(row.balance, row.currency) },
          { key: 'detail', header: 'Details', render: row => <details><summary>Line items</summary><InvoiceLines invoice={row} /></details> },
        ]} />
      </Panel>
      {!!data.invoices.length && <Panel title="Send an invoice update">
        <form onSubmit={submit} className="stack">
          <Field label="Invoice"><Select name="invoice_id" required>
            {data.invoices.map(row => <option key={row.id} value={row.id}>{row.number}</option>)}
          </Select></Field>
          <Field label="Update type"><Select name="kind">
            <option value="remittance">Remittance details</option><option value="dispute">Dispute</option><option value="promise_to_pay">Promise to pay</option>
          </Select></Field>
          <Field label="Details"><Textarea name="detail" required maxLength={2000} rows={4} /></Field>
          <Button type="submit" disabled={busy} loading={busy}>Submit update</Button>
        </form>
      </Panel>}
      <Panel title="Submitted updates">
        <DataTable rows={data.requests} getRowKey={row => row.id} emptyMessage="No updates submitted" columns={[
          { key: 'number', header: 'Invoice' }, { key: 'kind', header: 'Type', render: row => humanize(row.kind) },
          { key: 'detail', header: 'Your message' }, { key: 'status', header: 'Status', render: row => humanize(row.status) },
        ]} />
      </Panel>
    </>}
  </main>;
}
