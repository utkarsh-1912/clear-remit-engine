import React, { useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, Table } from '@utkristi/ui';
import { Plus } from 'lucide-react';
import { apiFetch } from './utils';

export default function ChartOfAccounts({ core, onRefresh, onDrillAccount }) {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [accountType, setAccountType] = useState('ASSET');
  const [parentGroup, setParentGroup] = useState('');
  const [currencyCode, setCurrencyCode] = useState('USD');
  const [isMonetary, setIsMonetary] = useState('1');
  const [filterType, setFilterType] = useState('ALL');
  const [error, setError] = useState('');

  async function handleCreate(e) {
    e.preventDefault();
    setError('');
    try {
      await apiFetch('/api/core/accounts', {
        method: 'POST',
        body: JSON.stringify({
          code,
          name,
          account_type: accountType,
          parent_group: parentGroup,
          currency_code: currencyCode.toUpperCase(),
          is_monetary: isMonetary === '1',
        }),
      });
      setCode('');
      setName('');
      setParentGroup('');
      await onRefresh();
    } catch (err) {
      setError(err.message);
    }
  }

  const rows = core.accounts.filter(a => filterType === 'ALL' || a.account_type === filterType);
  const columns = [
    { key: 'code', header: 'Code', render: r => <Button variant="ghost" size="sm" onClick={() => onDrillAccount(r.code)}>{r.code}</Button> },
    { key: 'name', header: 'Account Name' },
    { key: 'account_type', header: 'Type', render: r => <Badge tone="info">{r.account_type}</Badge> },
    { key: 'parent_group', header: 'Parent Group' },
    { key: 'currency_code', header: 'Ccy', render: r => <Badge tone="ok">{r.currency_code}</Badge> },
    { key: 'is_monetary', header: 'IAS 21', render: r => (r.is_monetary ? 'Monetary' : 'Historical') },
    { key: 'drill', header: 'Statement', render: r => <Button variant="ghost" size="sm" onClick={() => onDrillAccount(r.code)}>View Ledger</Button> },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <h1>Chart of accounts</h1>
          <p>Define hierarchical accounts, native currencies, and IAS 21 monetary revaluation flags.</p>
        </div>
      </header>

      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Create General Ledger Account</h2></div></CardHeader>
        <CardBody>
          {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}
          <form onSubmit={handleCreate} className="stack" style={{ gap: 14 }}>
            <div className="form-grid">
              <Field label="GL Code"><Input required value={code} onChange={e => setCode(e.target.value)} placeholder="Account code" /></Field>
              <Field label="Account Name"><Input required value={name} onChange={e => setName(e.target.value)} placeholder="Ledger name" /></Field>
              <Field label="Account Type">
                <Select value={accountType} onChange={e => setAccountType(e.target.value)}>
                  {['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE'].map(t => <option key={t} value={t}>{t}</option>)}
                </Select>
              </Field>
              <Field label="Parent Group"><Input required value={parentGroup} onChange={e => setParentGroup(e.target.value)} placeholder="Group hierarchy" /></Field>
              <Field label="ISO 4217 Currency"><Input required value={currencyCode} onChange={e => setCurrencyCode(e.target.value)} placeholder="USD" /></Field>
              <Field label="IAS 21 Revaluation">
                <Select value={isMonetary} onChange={e => setIsMonetary(e.target.value)}>
                  <option value="1">Monetary (Revalue at Close)</option>
                  <option value="0">Non-Monetary (Historical Cost)</option>
                </Select>
              </Field>
            </div>
            <div className="actions">
              <Button type="submit" iconLeft={<Plus size={15} />}>Create Ledger Account</Button>
            </div>
          </form>
        </CardBody>
      </Card>

      <Card className="panel">
        <CardHeader className="panel-heading">
          <div><h2>Active Ledgers ({rows.length})</h2></div>
          <Select value={filterType} onChange={e => setFilterType(e.target.value)}>
            {['ALL', 'ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE'].map(t => <option key={t} value={t}>{t}</option>)}
          </Select>
        </CardHeader>
        <Table columns={columns} rows={rows} getRowKey={r => r.account_id} />
      </Card>
    </div>
  );
}
