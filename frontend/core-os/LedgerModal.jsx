import React, { useEffect, useState } from 'react';
import { Badge, Modal, Spinner, Stat, Table } from '@utkristi/ui';
import { apiFetch, fmtNum, fmtUsd } from './utils';

export default function LedgerModal({ accountCode, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!accountCode) return;
    let active = true;
    setData(null);
    setError('');
    apiFetch(`/api/core/accounts/${encodeURIComponent(accountCode)}/ledger`)
      .then(res => { if (active) setData(res); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [accountCode]);

  const cols = [
    { key: 'effective_date', header: 'Date' },
    { key: 'voucher_number', header: 'Voucher' },
    { key: 'narration', header: 'Narration' },
    { key: 'functional_debit', header: 'Debit', align: 'right', render: r => (r.functional_debit > 0 ? fmtUsd(r.functional_debit) : '—') },
    { key: 'functional_credit', header: 'Credit', align: 'right', render: r => (r.functional_credit > 0 ? fmtUsd(r.functional_credit) : '—') },
    { key: 'running_functional_balance', header: 'Running USD', align: 'right', render: r => fmtUsd(r.running_functional_balance) },
  ];

  return (
    <Modal
      open={!!accountCode}
      onClose={onClose}
      title={data ? `${data.account.code} — ${data.account.name}` : `Account Ledger ${accountCode || ''}`}
      size="lg"
    >
      {error && <div className="error">{error}</div>}
      {!data && !error && <div className="loading"><Spinner /> Loading running-balance statement…</div>}
      {data && (
        <div className="stack" style={{ gap: 14 }}>
          <div className="actions">
            <Badge tone="info">{data.account.account_type}</Badge>
            <Badge tone="ok">{data.account.currency_code}</Badge>
            <span style={{ fontSize: '0.85rem', color: 'var(--ut-ink-2)' }}>{data.account.parent_group}</span>
          </div>
          <div className="detail-metrics">
            <Stat label="Total Debits (USD)" value={fmtUsd(data.total_debit_usd)} />
            <Stat label="Total Credits (USD)" value={fmtUsd(data.total_credit_usd)} />
            <Stat label="Closing Balance" value={`${fmtUsd(data.closing_functional_balance)} (${fmtNum(data.closing_native_balance)} ${data.account.currency_code})`} />
          </div>
          <Table columns={cols} rows={data.entries} getRowKey={(r, i) => `${r.voucher_number}-${i}`} />
        </div>
      )}
    </Modal>
  );
}
