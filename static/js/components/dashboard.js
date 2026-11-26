/* Component 1: Executive Command Center */
import { store, fmtUsd, fmtNum, fmtInt } from '../api.js';

export function renderDashboard(container, { navigate, openLedgerDrawer, openCmdPalette }) {
  if (!store.core) return;
  const st = store.core.statements;
  const cf = store.core.cashflow_and_aging?.cash_flow_statement || {};
  const aging = store.core.cashflow_and_aging?.ar_aging || { total_open_ar_usd: 0 };
  const bs = st.balance_sheet;
  const pl = st.profit_and_loss;
  const totalCash = st.nostro_positions.reduce((s, n) => s + n.functional_usd_value, 0);

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Executive Command Center</h2>
        <div class="topbar-sub">Real-Time Multi-Currency Core GL • Constant-Memory Streaming Backend • Zero-Float Minor Units</div>
      </div>
      <div class="actions">
        <button id="dashCmdBtn">⌘ Command Palette (Ctrl+K)</button>
        <button class="primary" id="dashGoBulk">⚡ GB Data Streamer</button>
        <button class="emerald" id="dashGoVch">+ Multi-Line Voucher</button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Assets (Functional USD)</div>
        <div class="kpi-val" style="color:var(--cyan)">${fmtUsd(bs.total_assets)}</div>
        <div class="kpi-sub">${bs.is_balanced ? '✓ Assets == Liab + Equity' : '⚠ Check'}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Global Cash &amp; Nostro Liquidity</div>
        <div class="kpi-val" style="color:var(--emerald)">${fmtUsd(totalCash)}</div>
        <div class="kpi-sub">${st.nostro_positions.length} Multi-Currency Accounts</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Net Profit (Current Period)</div>
        <div class="kpi-val" style="color:${pl.net_profit >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${fmtUsd(pl.net_profit)}</div>
        <div class="kpi-sub">Rev ${fmtUsd(pl.total_revenue)} • Exp ${fmtUsd(pl.total_expense)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Open AR Receivables &amp; Speed</div>
        <div class="kpi-val" style="color:var(--violet)">${fmtUsd(aging.total_open_ar_usd)}</div>
        <div class="kpi-sub">${fmtInt(store.core.total_vouchers_count)} Vouchers • ${store.core.query_latency_ms} ms</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Multi-Currency Nostro &amp; Bank Liquidity (Click to Drill Down)</span>
          <span class="pill p-cyan">Finacle EGL Sub-Ledgers</span>
        </div>
        ${st.nostro_positions.map(n => {
          const pct = totalCash > 0 ? Math.max(2, Math.min(100, (n.functional_usd_value / totalCash) * 100)) : 0;
          return `
            <div style="margin-bottom:13px;">
              <div style="display:flex; justify-content:space-between; font-size:12.5px;">
                <span>
                  <b class="mono clickable" data-drill="${n.code}" style="color:var(--cyan)">${n.code}</b>
                  ${n.name} <span class="pill p-cyan">${n.currency_code}</span>
                </span>
                <span class="num"><b>${fmtUsd(n.functional_usd_value)}</b> <span style="color:var(--muted); font-size:11px;">(${fmtNum(n.native_balance)} ${n.currency_code})</span></span>
              </div>
              <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
            </div>
          `;
        }).join('')}
        <div style="margin-top:16px; padding-top:12px; border-top:1px solid var(--border); display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; font-size:11.5px;">
          <div><div style="color:var(--muted)">Operating Cash Flow</div><b class="mono" style="color:var(--cyan)">${fmtUsd(cf.operating_activities)}</b></div>
          <div><div style="color:var(--muted)">Investing Cash Flow</div><b class="mono" style="color:var(--amber)">${fmtUsd(cf.investing_activities)}</b></div>
          <div><div style="color:var(--muted)">Financing Cash Flow</div><b class="mono" style="color:var(--emerald)">${fmtUsd(cf.financing_activities)}</b></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">Recent Immutable Daybook Vouchers</span>
          <button class="sm" id="dashGoDaybook">Open Full Daybook →</button>
        </div>
        <table>
          <thead><tr><th>Voucher #</th><th>Type</th><th>Narration</th><th class="num">USD</th></tr></thead>
          <tbody>
            ${store.core.vouchers.slice(0, 7).map(v => `
              <tr>
                <td class="mono" style="color:var(--cyan)">${v.voucher_number}</td>
                <td><span class="pill p-violet">${v.voucher_type}</span></td>
                <td style="max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${v.narration}">${v.narration}</td>
                <td class="num">${fmtUsd(v.total_functional_amount)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.querySelector('#dashCmdBtn')?.addEventListener('click', openCmdPalette);
  container.querySelector('#dashGoBulk')?.addEventListener('click', () => navigate('bulk'));
  container.querySelector('#dashGoVch')?.addEventListener('click', () => navigate('vouchers'));
  container.querySelector('#dashGoDaybook')?.addEventListener('click', () => navigate('vouchers'));
  container.querySelectorAll('[data-drill]').forEach(el => {
    el.addEventListener('click', () => openLedgerDrawer(el.getAttribute('data-drill')));
  });
}
