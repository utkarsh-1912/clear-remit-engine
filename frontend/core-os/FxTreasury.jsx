import React, { useEffect, useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, Spinner, Table } from '@utkristi/ui';
import { apiFetch, fmtNum, fmtUsd } from './utils';

export default function FxTreasury({ core, onRefresh }) {
  const foreignAccounts = core.accounts.filter(a => a.currency_code !== 'USD' && a.account_type === 'ASSET');
  const todayIso = new Date().toISOString().slice(0, 10);

  const [fromAcc, setFromAcc] = useState(foreignAccounts[0]?.code || '1011');
  const [fromAmt, setFromAmt] = useState('');
  const [execRate, setExecRate] = useState('');
  const [convResult, setConvResult] = useState(null);

  const [rateDate, setRateDate] = useState(todayIso);
  const [rateCcy, setRateCcy] = useState('');
  const [rateSpot, setRateSpot] = useState('');

  const [iasDate, setIasDate] = useState(todayIso);
  const [iasData, setIasData] = useState(null);
  const [error, setError] = useState('');

  async function runIas(commit = false, autoReverse = false) {
    setError('');
    try {
      const data = await apiFetch('/api/fx/revalue', {
        method: 'POST',
        body: JSON.stringify({ as_of_date: iasDate, commit_voucher: commit, auto_reverse_next_day: autoReverse }),
      });
      setIasData(data);
      if (commit) await onRefresh();
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { runIas(false, false); }, []);

  async function handleConvert(e) {
    e.preventDefault();
    setError('');
    try {
      const res = await apiFetch('/api/fx/convert', {
        method: 'POST',
        body: JSON.stringify({
          effective_date: todayIso,
          from_account_code: fromAcc,
          to_account_code: '1010',
          from_amount_native: Number(fromAmt),
          execution_rate_to_usd: Number(execRate),
        }),
      });
      setConvResult(res);
      setFromAmt('');
      await onRefresh();
      await runIas(false, false);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleUpsertRate(e) {
    e.preventDefault();
    setError('');
    try {
      await apiFetch('/api/fx/rate', {
        method: 'POST',
        body: JSON.stringify({ rate_date: rateDate, base_currency: rateCcy.toUpperCase(), spot_rate: Number(rateSpot) }),
      });
      setRateCcy('');
      setRateSpot('');
      await onRefresh();
      await runIas(false, false);
    } catch (err) {
      setError(err.message);
    }
  }

  const rateCols = [
    { key: 'rate_date', header: 'Date' },
    { key: 'pair', header: 'Pair', render: r => `${r.base_currency}/${r.quote_currency}` },
    { key: 'spot_rate', header: 'Spot', align: 'right' },
    { key: 'buy_rate', header: 'Buy', align: 'right' },
    { key: 'sell_rate', header: 'Sell', align: 'right' },
  ];

  const iasCols = [
    { key: 'account_code', header: 'Account', render: r => `${r.account_code} ${r.account_name}` },
    { key: 'native_balance', header: 'Native', align: 'right', render: r => `${r.currency_code} ${fmtNum(r.native_balance)}` },
    { key: 'carrying_functional_value', header: 'Book USD', align: 'right', render: r => fmtUsd(r.carrying_functional_value) },
    { key: 'closing_spot_rate', header: 'Close Rate', align: 'right', render: r => r.closing_spot_rate.toFixed(6) },
    { key: 'revalued_functional_value', header: 'Revalued USD', align: 'right', render: r => fmtUsd(r.revalued_functional_value) },
    {
      key: 'unrealized_fx_delta',
      header: 'Unrealized FX',
      align: 'right',
      render: r => <Badge tone={r.unrealized_fx_delta >= 0 ? 'ok' : 'bad'}>{fmtUsd(r.unrealized_fx_delta)}</Badge>,
    },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <div className="eyebrow">Treasury &amp; IAS 21</div>
          <h1>FX Rate Matrix &amp; Revaluation Desk</h1>
          <p>Convert foreign Nostro balances with realized FX tracking and run IAS 21 period-end monetary revaluation.</p>
        </div>
        <div className="actions">
          <Input type="date" value={iasDate} onChange={e => setIasDate(e.target.value)} />
          <Button variant="ghost" onClick={() => runIas(false, false)}>Preview IAS 21</Button>
          <Button onClick={() => runIas(true, false)}>Post Revaluation</Button>
          <Button variant="ghost" onClick={() => runIas(true, true)}>Post + Day-1 Reversal</Button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Cross-Currency Nostro Conversion</h2></div></CardHeader>
          <CardBody>
            <form onSubmit={handleConvert} className="stack" style={{ gap: 12 }}>
              <Field label="Source Foreign Account">
                <Select value={fromAcc} onChange={e => setFromAcc(e.target.value)}>
                  {foreignAccounts.map(a => <option key={a.code} value={a.code}>{a.code} — {a.name} ({a.currency_code})</option>)}
                </Select>
              </Field>
              <div className="form-grid">
                <Field label="Native Amount"><Input type="number" step="0.01" required value={fromAmt} onChange={e => setFromAmt(e.target.value)} placeholder="Amount to convert" /></Field>
                <Field label="Execution Rate (→ USD)"><Input type="number" step="0.000001" required value={execRate} onChange={e => setExecRate(e.target.value)} placeholder="Spot rate" /></Field>
              </div>
              <Button type="submit">Convert to USD Operating Bank</Button>
              {convResult && (
                <Badge tone="ok">
                  Posted {convResult.voucher.voucher_number} · USD {fmtUsd(convResult.realized_usd_value)} · Realized FX {fmtUsd(convResult.realized_fx_gain_loss)}
                </Badge>
              )}
            </form>
          </CardBody>
        </Card>

        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Upsert Exchange Rate</h2></div></CardHeader>
          <CardBody>
            <form onSubmit={handleUpsertRate} className="stack" style={{ gap: 12 }}>
              <div className="form-grid">
                <Field label="Rate Date"><Input type="date" required value={rateDate} onChange={e => setRateDate(e.target.value)} /></Field>
                <Field label="Base Currency"><Input required value={rateCcy} onChange={e => setRateCcy(e.target.value)} placeholder="EUR / INR / GBP" /></Field>
                <Field label="Spot Rate (→ USD)"><Input type="number" step="0.000001" required value={rateSpot} onChange={e => setRateSpot(e.target.value)} placeholder="Rate to USD" /></Field>
              </div>
              <Button type="submit" variant="ghost">Save Exchange Rate</Button>
            </form>
          </CardBody>
        </Card>
      </div>

      <Card className="panel">
        <CardHeader className="panel-heading">
          <div><h2>IAS 21 Period-End Monetary Revaluation</h2></div>
          {iasData && (
            <Badge tone={iasData.total_unrealized_fx_gain_loss >= 0 ? 'ok' : 'bad'}>
              Net Unrealized: {fmtUsd(iasData.total_unrealized_fx_gain_loss)}
            </Badge>
          )}
        </CardHeader>
        {!iasData ? <div className="loading"><Spinner /> Evaluating monetary accounts…</div> : (
          <Table columns={iasCols} rows={iasData.items} getRowKey={r => r.account_code} />
        )}
      </Card>

      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Stored Exchange Rate Matrix</h2></div></CardHeader>
        <Table columns={rateCols} rows={core.fx_rates} getRowKey={r => `${r.rate_date}-${r.base_currency}-${r.quote_currency}`} />
      </Card>
    </div>
  );
}
