import React, { useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Select, Spinner, Table } from '@utkristi/ui';
import { apiFetch, fmtUsd } from './utils';

export default function RemittanceHub({ onRefresh }) {
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const [posted, setPosted] = useState(() => new Set());
  const [data, setData] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [postedMsg, setPostedMsg] = useState('');
  const [error, setError] = useState('');

  // DTAA Tax Validator
  const [corridor, setCorridor] = useState('IN-US');
  const [category, setCategory] = useState('TECHNICAL_SERVICES_FTS');
  const [gross, setGross] = useState('');
  const [withheld, setWithheld] = useState('');
  const [taxAudit, setTaxAudit] = useState(null);

  async function reconcile(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError('');
    setLoading(true);
    setData(null);
    try {
      const [statement, invoices, credits, remittance] = await Promise.all(
        ['statement', 'invoices', 'credits', 'remittance'].map(key => form.get(key)?.text() ?? ''),
      );
      setData(await apiFetch('/api/reconcile', {
        method: 'POST',
        body: JSON.stringify({
          statement_format: form.get('format'),
          statement_content: statement,
          invoices_csv: invoices,
          credit_memos_csv: credits,
          remittance_emails_text: remittance,
        }),
      }));
      setSelectedIdx(0);
      setPostedMsg('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function downloadExport(key, filename, type) {
    const url = URL.createObjectURL(new Blob([data.exports[key]], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function postProposal(prop) {
    setError('');
    setPosting(true);
    try {
      const res = await apiFetch('/api/remittance/post-to-ledger', {
        method: 'POST',
        body: JSON.stringify({
          tx_id: prop.tx_id,
          effective_date: prop.booking_date,
          customer_name: prop.matched_customer_name,
          explanation_summary: prop.explanation_summary,
          journal_entries: prop.journal_entries,
        }),
      });
      setPosted(new Set([...posted, prop.tx_id]));
      setPostedMsg(`Posted ${prop.tx_id} as ${res.voucher_number} into Core GL.`);
      await onRefresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setPosting(false);
    }
  }

  async function runTaxAudit(e) {
    e.preventDefault();
    setError('');
    try {
      const res = await apiFetch('/api/tax-audit', {
        method: 'POST',
        body: JSON.stringify({
          corridor_code: corridor,
          service_category: category,
          gross_amount: Number(gross),
          withheld_amount: Number(withheld),
        }),
      });
      setTaxAudit(res);
    } catch (err) {
      setError(err.message);
    }
  }

  const prop = data?.proposals?.[selectedIdx];
  const jeCols = [
    { key: 'account_code', header: 'GL' },
    { key: 'account_name', header: 'Account' },
    { key: 'memo', header: 'Memo' },
    { key: 'debit', header: 'Debit', align: 'right', render: r => (r.debit > 0 ? fmtUsd(r.debit) : '—') },
    { key: 'credit', header: 'Credit', align: 'right', render: r => (r.credit > 0 ? fmtUsd(r.credit) : '—') },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div><h1>Remittance &amp; tax</h1>
          <p>Match incoming payments to invoices, review proposed journals, and check treaty withholding.</p>
        </div>
      </header>

      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>New reconciliation</h2>
          <p>Use your bank statement and open invoice register. Credit memos and remittance details are optional.</p>
        </div></CardHeader>
        <CardBody>
          <form onSubmit={reconcile} className="stack">
            <div className="form-grid">
              <Field label="Statement format"><Select name="format">
                <option value="AUTO">Detect automatically</option>
                <option value="ISO20022_XML">ISO 20022 XML (camt.053)</option>
                <option value="MT940">SWIFT MT940</option>
                <option value="BAI2">BAI2</option>
                <option value="BANK_CSV">Bank CSV</option>
              </Select></Field>
              <Field label="Bank statement"><Input type="file" name="statement" accept=".xml,.csv,.sta,.mt940,.bai,.bai2,.txt" required /></Field>
              <Field label="Open invoices (CSV)"><Input type="file" name="invoices" accept=".csv" required /></Field>
              <Field label="Credit memos (CSV)"><Input type="file" name="credits" accept=".csv" /></Field>
              <Field label="Remittance details (TXT)"><Input type="file" name="remittance" accept=".txt" /></Field>
            </div>
            <div className="actions"><Button type="submit" disabled={loading || posting} iconLeft={loading ? <Spinner /> : undefined}>Run reconciliation</Button>
              <Button href="/docs/connectors" variant="ghost">File requirements</Button></div>
          </form>
        </CardBody>
      </Card>
      {error && <div className="error" role="alert">{error}</div>}
      {postedMsg && <div role="status"><Badge tone="ok">{postedMsg}</Badge></div>}
      {data && data.proposals.length === 0 && <EmptyState title="No incoming payments found" />}
      {data?.proposals.length > 0 && <>
        <div className="results-bar">
          <h2>{data.proposals.length} payments to review</h2>
          <div className="actions">
            {[
              ['quickbooks_csv', 'QuickBooks', 'csv'], ['xero_csv', 'Xero', 'csv'],
              ['netsuite_csv', 'NetSuite', 'csv'], ['tally_xml', 'Tally', 'xml'],
            ].map(([key, label, ext]) => <Button key={key} size="sm" variant="ghost"
              onClick={() => downloadExport(key, `${label}-journal.${ext}`, ext === 'xml' ? 'application/xml' : 'text/csv')}>
              {label} export
            </Button>)}
          </div>
        </div>
        <div className="review-layout">
          <div className="tx-list">
            {data.proposals.map((p, idx) => (
              <button
                type="button"
                key={p.tx_id}
                className="tx"
                aria-pressed={idx === selectedIdx}
                onClick={() => setSelectedIdx(idx)}
              >
                <div className="tx-top">
                  <strong>{p.tx_id} · {p.matched_customer_name}</strong>
                  <strong>{p.currency} {Number(p.deposit_amount).toLocaleString()}</strong>
                </div>
                <div className="tx-bottom">
                  <Badge tone={p.status === 'AUTO_RECONCILED' ? 'ok' : 'warn'}>{p.status}</Badge>
                  <Badge tone="info">{p.match_method}</Badge>
                </div>
              </button>
            ))}
          </div>

          {prop && (
            <Card className="panel">
              <CardHeader className="panel-heading">
                <div>
                  <h2>{prop.tx_id} — {prop.matched_customer_name}</h2>
                  <p>{prop.explanation_summary}</p>
                </div>
                <Button disabled={posting || posted.has(prop.tx_id) || prop.currency !== 'USD' || !prop.journal_entries.length}
                  onClick={() => postProposal(prop)}>{posted.has(prop.tx_id) ? 'Posted' : 'Post receipt'}</Button>
              </CardHeader>
              {prop.currency !== 'USD' && <CardBody><p>Direct posting supports USD receipts. Review the export for this payment.</p></CardBody>}
              <Table columns={jeCols} rows={prop.journal_entries} getRowKey={r => `${prop.tx_id}-${r.line_number}`} />
              {prop.dispute_notice_draft && (
                <CardBody>
                  <h3>Unauthorized Short-Pay Dispute Notice</h3>
                  <pre>{prop.dispute_notice_draft}</pre>
                </CardBody>
              )}
            </Card>
          )}
        </div>
      </>}

      <Card className="panel">
        <CardHeader className="panel-heading">
          <div>
            <h2>Cross-Border DTAA Tax Withholding Auditor</h2>
            <p>Verify statutory withholding rates against bilateral tax treaties.</p>
          </div>
        </CardHeader>
        <CardBody>
          <form onSubmit={runTaxAudit} className="stack" style={{ gap: 12 }}>
            <div className="form-grid">
              <Field label="Tax Corridor">
                <Select value={corridor} onChange={e => setCorridor(e.target.value)}>
                  {['IN-US', 'US-IN', 'GB-US', 'DE-US', 'SG-US', 'CA-US'].map(c => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
              <Field label="Service Category">
                <Select value={category} onChange={e => setCategory(e.target.value)}>
                  <option value="TECHNICAL_SERVICES_FTS">Technical / Consulting (FTS)</option>
                  <option value="SAAS_CLOUD">Standard B2B SaaS / Cloud</option>
                  <option value="ROYALTY_IP">Software / IP Royalty</option>
                  <option value="PROFESSIONAL_SERVICES">Offshore Professional Services</option>
                </Select>
              </Field>
              <Field label="Gross Invoice (USD)"><Input type="number" step="0.01" required value={gross} onChange={e => setGross(e.target.value)} placeholder="Gross amount" /></Field>
              <Field label="Withheld by Buyer (USD)"><Input type="number" step="0.01" required value={withheld} onChange={e => setWithheld(e.target.value)} placeholder="Withheld amount" /></Field>
            </div>
            <div className="actions"><Button type="submit">Verify Treaty Compliance</Button></div>
          </form>

          {taxAudit && (
            <div style={{ marginTop: 14 }} className="stack">
              <Badge tone={taxAudit.status === 'COMPLIANT_TREATY_RATE' ? 'ok' : 'warn'}>
                {taxAudit.status} · Actual {taxAudit.actual_withheld_pct}% vs Treaty Cap {taxAudit.expected_treaty_pct}%
              </Badge>
              <p>{taxAudit.recommendation}</p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
