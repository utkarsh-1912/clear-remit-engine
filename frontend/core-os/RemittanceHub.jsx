import React, { useEffect, useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, Spinner, Table } from '@utkristi/ui';
import { apiFetch, fmtUsd } from './utils';

export default function RemittanceHub({ onRefresh }) {
  const [fmt, setFmt] = useState('iso20022');
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

  useEffect(() => {
    let active = true;
    setData(null);
    apiFetch(`/api/sample?fmt=${encodeURIComponent(fmt)}`)
      .then(res => { if (active) { setData(res); setSelectedIdx(0); } })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [fmt]);

  async function postProposal(prop) {
    setError('');
    try {
      const res = await apiFetch('/api/remittance/post-to-ledger', {
        method: 'POST',
        body: JSON.stringify({
          tx_id: prop.tx_id,
          effective_date: new Date().toISOString().slice(0, 10),
          customer_name: prop.matched_customer_name,
          explanation_summary: prop.explanation_summary,
          journal_entries: prop.journal_entries,
        }),
      });
      setPostedMsg(`Posted ${prop.tx_id} as ${res.voucher_number} into Core GL.`);
      await onRefresh();
    } catch (err) {
      setError(err.message);
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
        <div>
          <div className="eyebrow">Multi-Rail Reconciliation</div>
          <h1>Remittance Hub &amp; DTAA Tax Compliance</h1>
          <p>Parse ISO 20022 XML, SWIFT MT940, and BAI2 feeds, solve short-pays, and commit split receipts directly to the Core GL.</p>
        </div>
        <div className="actions">
          <Select value={fmt} onChange={e => setFmt(e.target.value)}>
            <option value="iso20022">ISO 20022 XML (camt.053)</option>
            <option value="mt940">SWIFT MT940</option>
            <option value="bai2">BAI2 Cash Management</option>
          </Select>
        </div>
      </header>

      {error && <div className="error">{error}</div>}
      {postedMsg && <Badge tone="ok">{postedMsg}</Badge>}

      {!data ? (
        <div className="loading"><Spinner /> Running combinatorial reconciliation engine…</div>
      ) : (
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
                  <strong>{fmtUsd(p.deposit_amount)}</strong>
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
                <Button onClick={() => postProposal(prop)}>Post Split Receipt to Core GL</Button>
              </CardHeader>
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
      )}

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
