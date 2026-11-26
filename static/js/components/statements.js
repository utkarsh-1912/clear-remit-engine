/* Component 7: Live Financial Statements, Cash Flow, Bill-by-Bill AR Aging, & ERP Exports */
import { store, fmtUsd, fmtNum } from '../api.js';

export function renderStatements(container, { openLedgerDrawer }) {
  if (!store.core) return;
  const st = store.core.statements;
  const pl = st.profit_and_loss;
  const bs = st.balance_sheet;
  const tb = st.trial_balance;
  const cfa = store.core.cashflow_and_aging || { cash_flow_statement: {}, ar_aging: { buckets: {}, bills: [] } };
  const cf = cfa.cash_flow_statement;
  const aging = cfa.ar_aging;

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Live Statutory Financial Statements, Cash Flow &amp; AR Aging</h2>
        <div class="topbar-sub">Click Any GL Code to Open Its Running-Balance Ledger Statement • Export to Tally, QuickBooks, Xero, NetSuite</div>
      </div>
      <div class="actions">
        <button onclick="window.open('/api/export/tally','_blank')">⬇ Tally Prime XML</button>
        <button onclick="window.open('/api/export/quickbooks','_blank')">⬇ QuickBooks CSV</button>
        <button onclick="window.open('/api/export/xero','_blank')">⬇ Xero CSV</button>
        <button onclick="window.open('/api/export/netsuite','_blank')">⬇ NetSuite CSV</button>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header"><span class="card-title">Profit &amp; Loss Statement (Income Statement)</span></div>
        <table>
          <thead><tr><th>Code</th><th>Account</th><th>Type</th><th class="num">USD</th></tr></thead>
          <tbody>
            ${pl.revenues.map(r => `<tr><td class="mono clickable" data-drill="${r.code}" style="color:var(--cyan)">${r.code}</td><td>${r.name}</td><td><span class="pill p-green">REV</span></td><td class="num" style="color:var(--emerald)">${fmtUsd(r.display_amount)}</td></tr>`).join('')}
            ${pl.expenses.map(e => `<tr><td class="mono clickable" data-drill="${e.code}" style="color:var(--cyan)">${e.code}</td><td>${e.name}</td><td><span class="pill p-amber">EXP</span></td><td class="num" style="color:var(--amber)">(${fmtUsd(e.display_amount)})</td></tr>`).join('')}
            <tr style="background:rgba(16,185,129,0.08); font-weight:700;"><td colspan="3">NET PROFIT / (LOSS)</td><td class="num" style="color:var(--cyan)">${fmtUsd(pl.net_profit)}</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Balance Sheet (${bs.is_balanced ? '✓ BALANCED' : '⚠ CHECK'})</span></div>
        <table>
          <thead><tr><th>Code</th><th>Account</th><th>Category</th><th class="num">USD</th></tr></thead>
          <tbody>
            ${bs.assets.map(a => `<tr><td class="mono clickable" data-drill="${a.code}" style="color:var(--cyan)">${a.code}</td><td>${a.name}</td><td><span class="pill p-cyan">ASSET</span></td><td class="num">${fmtUsd(a.display_amount)}</td></tr>`).join('')}
            <tr style="background:rgba(56,189,248,0.08); font-weight:700;"><td colspan="3">TOTAL ASSETS</td><td class="num" style="color:var(--cyan)">${fmtUsd(bs.total_assets)}</td></tr>
            ${bs.liabilities.map(l => `<tr><td class="mono clickable" data-drill="${l.code}" style="color:var(--cyan)">${l.code}</td><td>${l.name}</td><td><span class="pill p-amber">LIAB</span></td><td class="num">${fmtUsd(l.display_amount)}</td></tr>`).join('')}
            ${bs.equity.map(e => `<tr><td class="mono clickable" data-drill="${e.code}" style="color:var(--cyan)">${e.code}</td><td>${e.name}</td><td><span class="pill p-violet">EQUITY</span></td><td class="num">${fmtUsd(e.display_amount)}</td></tr>`).join('')}
            <tr><td class="mono">—</td><td><i>Current Period Net Profit</i></td><td><span class="pill p-green">P&amp;L</span></td><td class="num">${fmtUsd(bs.current_period_net_profit)}</td></tr>
            <tr style="background:rgba(16,185,129,0.08); font-weight:700;"><td colspan="3">TOTAL LIABILITIES &amp; EQUITY</td><td class="num" style="color:var(--emerald)">${fmtUsd(bs.total_liabilities_and_equity)}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header"><span class="card-title">Direct-Method Cash Flow Statement</span></div>
        <table>
          <tbody>
            <tr><td>Cash Flows from Operating Activities (AR/AP/FX Receipts)</td><td class="num" style="color:var(--cyan)">${fmtUsd(cf.operating_activities)}</td></tr>
            <tr><td>Cash Flows from Investing Activities (Post-Trade Settlements)</td><td class="num" style="color:var(--amber)">${fmtUsd(cf.investing_activities)}</td></tr>
            <tr><td>Cash Flows from Financing Activities (Owner Capital)</td><td class="num" style="color:var(--emerald)">${fmtUsd(cf.financing_activities)}</td></tr>
            <tr><td>IAS 21 FX Translation Effect on Foreign Cash</td><td class="num" style="color:var(--violet)">${fmtUsd(cf.fx_translation_effect_on_cash)}</td></tr>
            <tr style="background:rgba(56,189,248,0.08); font-weight:700;"><td>NET CHANGE IN GLOBAL CASH &amp; NOSTRO</td><td class="num" style="color:#fff">${fmtUsd(cf.net_change_in_cash)}</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Bill-by-Bill AR Aging Schedule</span><span class="pill p-cyan">Total: ${fmtUsd(aging.total_open_ar_usd)}</span></div>
        <table>
          <thead><tr><th>Bill Ref</th><th>Party</th><th>Bucket</th><th class="num">Age</th><th class="num">Open USD</th></tr></thead>
          <tbody>
            ${aging.bills.length ? aging.bills.map(b => `
              <tr>
                <td class="mono" style="color:var(--cyan)">${b.bill_ref}</td>
                <td>${b.party_name}</td>
                <td><span class="pill ${b.age_days > 30 ? 'p-amber' : 'p-green'}">${b.aging_bucket}</span></td>
                <td class="num">${b.age_days}d</td>
                <td class="num" style="font-weight:700;">${fmtUsd(b.open_usd)}</td>
              </tr>
            `).join('') : '<tr><td colspan="5" style="color:var(--muted)">No open AR bills.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><span class="card-title">Real-Time Trial Balance (Click Code to Drill Down)</span><span class="pill ${tb.is_balanced ? 'p-green' : 'p-rose'}">${tb.is_balanced ? '✓ Exact Zero Variance' : '⚠ Check'}</span></div>
      <table>
        <thead><tr><th>Code</th><th>Account Name</th><th>Group</th><th>Ccy</th><th class="num">Native Bal</th><th class="num">Debit (USD)</th><th class="num">Credit (USD)</th></tr></thead>
        <tbody>
          ${tb.rows.map(r => `
            <tr>
              <td class="mono clickable" data-drill="${r.code}" style="color:var(--cyan); font-weight:700;">${r.code}</td>
              <td><b>${r.name}</b></td>
              <td style="font-size:11px; color:var(--muted)">${r.parent_group}</td>
              <td>${r.currency_code}</td>
              <td class="num">${fmtNum(r.native_balance)}</td>
              <td class="num" style="color:var(--cyan)">${r.functional_debit > 0 ? fmtUsd(r.functional_debit) : '—'}</td>
              <td class="num" style="color:var(--emerald)">${r.functional_credit > 0 ? fmtUsd(r.functional_credit) : '—'}</td>
            </tr>
          `).join('')}
          <tr style="background:rgba(56,189,248,0.1); font-weight:700;">
            <td colspan="5">TRIAL BALANCE TOTAL</td>
            <td class="num" style="color:var(--cyan)">${fmtUsd(tb.total_debits)}</td>
            <td class="num" style="color:var(--emerald)">${fmtUsd(tb.total_credits)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;

  container.querySelectorAll('[data-drill]').forEach(el => {
    el.addEventListener('click', () => openLedgerDrawer(el.getAttribute('data-drill')));
  });
}
