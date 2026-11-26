import React, { useEffect, useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Select, Spinner, Table } from '@utkristi/ui';
import { Plus, RotateCcw, Trash2 } from 'lucide-react';
import { apiFetch, fmtInt, fmtUsd } from './utils';

export default function VouchersDaybook({ core, onRefresh, onDrillAccount }) {
  const defaultDr = core.accounts[0]?.code || '1010';
  const defaultCr = core.accounts[1]?.code || '1200';
  const todayIso = new Date().toISOString().slice(0, 10);

  const [vType, setVType] = useState('JOURNAL');
  const [vDate, setVDate] = useState(todayIso);
  const [narration, setNarration] = useState('');
  const [sourceRef, setSourceRef] = useState('');
  const [lines, setLines] = useState([
    { account_code: defaultDr, side: 'DR', amount: '', currency: 'USD', bill_ref: '', party_name: '' },
    { account_code: defaultCr, side: 'CR', amount: '', currency: 'USD', bill_ref: '', party_name: '' },
  ]);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [daybook, setDaybook] = useState(null);

  async function loadDaybook(p = page, q = search, t = typeFilter) {
    const data = await apiFetch(
      `/api/core/vouchers?page=${p}&page_size=25&search=${encodeURIComponent(q)}&voucher_type=${encodeURIComponent(t)}`,
    );
    setDaybook(data);
  }

  useEffect(() => { loadDaybook(page, search, typeFilter); }, [page, search, typeFilter, core.total_vouchers_count]);

  const drTotal = lines.filter(l => l.side === 'DR').reduce((s, l) => s + Number(l.amount || 0), 0);
  const crTotal = lines.filter(l => l.side === 'CR').reduce((s, l) => s + Number(l.amount || 0), 0);
  const variance = Math.abs(drTotal - crTotal);

  function updateLine(idx, key, val) {
    setLines(prev => prev.map((l, i) => (i === idx ? { ...l, [key]: val } : l)));
  }

  async function handleCommit(e) {
    e.preventDefault();
    setFormError('');
    setSaving(true);
    try {
      await apiFetch('/api/core/vouchers', {
        method: 'POST',
        body: JSON.stringify({
          voucher_type: vType,
          effective_date: vDate,
          narration,
          source_ref: sourceRef || null,
          lines: lines.map(l => ({
            account_code: l.account_code,
            debit: l.side === 'DR' ? Number(l.amount || 0) : 0,
            credit: l.side === 'CR' ? Number(l.amount || 0) : 0,
            native_currency: l.currency || 'USD',
            bill_ref: l.bill_ref || null,
            party_name: l.party_name || null,
          })),
        }),
      });
      setNarration('');
      setSourceRef('');
      setLines([
        { account_code: defaultDr, side: 'DR', amount: '', currency: 'USD', bill_ref: '', party_name: '' },
        { account_code: defaultCr, side: 'CR', amount: '', currency: 'USD', bill_ref: '', party_name: '' },
      ]);
      await onRefresh();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleReverse(voucherId) {
    try {
      await apiFetch(`/api/core/vouchers/${voucherId}/reverse`, {
        method: 'POST',
        body: JSON.stringify({ reversal_date: todayIso, reason: 'Operator Audit Reversal' }),
      });
      await onRefresh();
    } catch (err) {
      setFormError(err.message);
    }
  }

  const columns = [
    { key: 'voucher_number', header: 'Voucher #' },
    { key: 'voucher_type', header: 'Type', render: r => <Badge tone="info">{r.voucher_type}</Badge> },
    { key: 'effective_date', header: 'Date' },
    {
      key: 'narration',
      header: 'Narration & Split Lines',
      render: r => (
        <div>
          <strong>{r.narration}</strong>
          <div style={{ fontSize: '0.78rem', color: 'var(--ut-ink-2)', marginTop: 4 }}>
            {r.lines.map((l, idx) => (
              <div key={idx}>
                {l.functional_debit > 0 ? 'Dr' : 'Cr'}{' '}
                <a href="#coa" onClick={e => { e.preventDefault(); onDrillAccount(l.account_code); }}>
                  {l.account_code}
                </a>{' '}
                {l.account_name}: {fmtUsd(l.functional_debit || l.functional_credit)}
              </div>
            ))}
          </div>
        </div>
      ),
    },
    { key: 'status', header: 'Status', render: r => <Badge tone={r.status === 'POSTED' ? 'ok' : 'warn'}>{r.status}</Badge> },
    { key: 'total_functional_amount', header: 'USD', align: 'right', render: r => fmtUsd(r.total_functional_amount) },
    {
      key: 'action',
      header: 'Audit',
      render: r => (r.status === 'POSTED' ? (
        <Button variant="ghost" size="sm" onClick={() => handleReverse(r.voucher_id)} iconLeft={<RotateCcw size={13} />}>
          Reverse
        </Button>
      ) : 'Reversed'),
    },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <h1>Vouchers &amp; daybook</h1>
          <p>Compose multi-line multi-currency vouchers with strict Dr == Cr enforcement and compensating reversals.</p>
        </div>
      </header>

      <Card className="panel">
        <CardHeader className="panel-heading">
          <div>
            <h2>Multi-Line Voucher Composer</h2>
            <p>Add unlimited Debit/Credit split lines across accounts and currencies.</p>
          </div>
          <div className="actions">
            <Badge tone={variance < 0.005 && drTotal > 0 ? 'ok' : 'warn'}>
              {variance < 0.005 ? `Balanced (${fmtUsd(drTotal)})` : `Variance: ${fmtUsd(variance)}`}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLines(prev => [...prev, { account_code: defaultDr, side: 'DR', amount: '', currency: 'USD', bill_ref: '', party_name: '' }])}
              iconLeft={<Plus size={14} />}
            >
              Add Split Line
            </Button>
          </div>
        </CardHeader>
        <CardBody>
          {formError && <div className="error" style={{ marginBottom: 12 }}>{formError}</div>}
          <form onSubmit={handleCommit} className="stack" style={{ gap: 14 }}>
            <div className="form-grid">
              <Field label="Voucher Type">
                <Select value={vType} onChange={e => setVType(e.target.value)}>
                  {['JOURNAL', 'RECEIPT', 'PAYMENT', 'SALES', 'PURCHASE', 'CONTRA_FX'].map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Effective Date">
                <Input type="date" required value={vDate} onChange={e => setVDate(e.target.value)} />
              </Field>
              <Field label="Narration">
                <Input required value={narration} onChange={e => setNarration(e.target.value)} placeholder="Describe the accounting event" />
              </Field>
              <Field label="Source Reference (Optional)">
                <Input value={sourceRef} onChange={e => setSourceRef(e.target.value)} placeholder="Invoice / Wire / Contract Ref" />
              </Field>
            </div>

            <div className="stack" style={{ gap: 8 }}>
              {lines.map((l, idx) => (
                <div key={idx} style={{ display: 'grid', gridTemplateColumns: '2fr 0.7fr 1fr 0.7fr 1fr auto', gap: 8, alignItems: 'center' }}>
                  <Select value={l.account_code} onChange={e => updateLine(idx, 'account_code', e.target.value)}>
                    {core.accounts.map(a => (
                      <option key={a.code} value={a.code}>{a.code} — {a.name} ({a.currency_code})</option>
                    ))}
                  </Select>
                  <Select value={l.side} onChange={e => updateLine(idx, 'side', e.target.value)}>
                    <option value="DR">Dr</option>
                    <option value="CR">Cr</option>
                  </Select>
                  <Input type="number" step="0.01" required placeholder="0.00" value={l.amount} onChange={e => updateLine(idx, 'amount', e.target.value)} />
                  <Input value={l.currency} onChange={e => updateLine(idx, 'currency', e.target.value.toUpperCase())} placeholder="USD" />
                  <Input value={l.bill_ref} onChange={e => updateLine(idx, 'bill_ref', e.target.value)} placeholder="Bill Ref" />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={lines.length <= 2}
                    onClick={() => setLines(prev => prev.filter((_, i) => i !== idx))}
                    iconLeft={<Trash2 size={14} />}
                  />
                </div>
              ))}
            </div>

            <div className="actions">
              <Button type="submit" disabled={saving || variance >= 0.005 || drTotal <= 0}>
                {saving ? 'Committing…' : 'Commit Immutable Voucher'}
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      <Card className="panel">
        <CardHeader className="panel-heading">
          <div>
            <h2>Indexed Daybook ({daybook ? fmtInt(daybook.total_count) : '…'} Vouchers)</h2>
            <p>{daybook ? `Query latency: ${daybook.query_latency_ms} ms` : 'Loading indexed rows…'}</p>
          </div>
          <div className="actions">
            <Input
              value={search}
              onChange={e => { setPage(1); setSearch(e.target.value); }}
              placeholder="Search voucher #, narration, ref…"
            />
            <Select value={typeFilter} onChange={e => { setPage(1); setTypeFilter(e.target.value); }}>
              {['ALL', 'RECEIPT', 'PAYMENT', 'JOURNAL', 'CONTRA_FX', 'TRADE_SETTLEMENT', 'REVALUATION', 'REVERSAL'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </Select>
          </div>
        </CardHeader>
        {!daybook ? (
          <div className="loading"><Spinner /> Loading daybook…</div>
        ) : daybook.items.length === 0 ? (
          <CardBody><EmptyState title="No matching vouchers found" /></CardBody>
        ) : (
          <>
            <Table columns={columns} rows={daybook.items} getRowKey={r => r.voucher_id} />
            <CardBody className="actions">
              <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
              <span style={{ fontSize: '0.85rem', color: 'var(--ut-ink-2)' }}>
                Page {daybook.page} of {daybook.total_pages}
              </span>
              <Button variant="ghost" size="sm" disabled={page >= daybook.total_pages} onClick={() => setPage(p => p + 1)}>Next</Button>
            </CardBody>
          </>
        )}
      </Card>
    </div>
  );
}
