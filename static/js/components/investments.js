/* Component 6: Post-Trade Investment & Capital Gains Tax-Lot Ledger */
import { store, apiJson, refreshCore, fmtUsd, toast } from '../api.js';

let cachedSampleCsv = '';

export async function renderInvestments(container) {
  if (!store.core) return;
  if (!cachedSampleCsv) {
    const res = await apiJson('/api/investments/sample-csv');
    cachedSampleCsv = res.csv_content;
  }

  const inv = store.core.investments;
  const s = inv.summary;

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Post-Trade Investment &amp; Capital Gains Tax-Lot Ledger</h2>
        <div class="topbar-sub">Strictly Post-Settlement Statutory Accounting • FIFO Cost Basis Capitalization • STCG vs. LTCG Schedule</div>
      </div>
      <div class="actions">
        <button class="primary" id="ingestBrokerBtn">▶ Import Broker CSV &amp; Post to Core GL</button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Open FIFO Cost Basis</div><div class="kpi-val" style="color:var(--cyan)">${fmtUsd(s.total_open_cost_basis)}</div><div class="kpi-sub">${s.open_lots_count} Active Tax Lots</div></div>
      <div class="kpi-card"><div class="kpi-label">Realized STCG (&le; 365d)</div><div class="kpi-val" style="color:var(--amber)">${fmtUsd(s.total_realized_stcg)}</div><div class="kpi-sub">Short-Term Capital Gains</div></div>
      <div class="kpi-card"><div class="kpi-label">Realized LTCG (&gt; 365d)</div><div class="kpi-val" style="color:var(--emerald)">${fmtUsd(s.total_realized_ltcg)}</div><div class="kpi-sub">Long-Term Capital Gains</div></div>
      <div class="kpi-card"><div class="kpi-label">Total Realized Gains</div><div class="kpi-val" style="color:var(--violet)">${fmtUsd(s.total_realized_capital_gains)}</div><div class="kpi-sub">Synced with Core GL 4300/4310</div></div>
    </div>

    <div class="card">
      <div class="card-header"><span class="card-title">Post-Settlement Broker Contract Notes CSV (BUY / SELL / DIVIDEND)</span></div>
      <textarea id="brokerCsvInput" style="height:135px; color:#6ee7b7;">${cachedSampleCsv}</textarea>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header"><span class="card-title">Open FIFO Tax-Lots Sub-Ledger</span></div>
        <table>
          <thead><tr><th>Symbol</th><th>Class</th><th>Acq Date</th><th class="num">Rem Qty</th><th class="num">Unit Cost</th><th class="num">Cost Basis</th></tr></thead>
          <tbody>
            ${inv.open_lots.length ? inv.open_lots.map(l => `
              <tr>
                <td class="mono" style="font-weight:700; color:var(--cyan)">${l.symbol}</td>
                <td><span class="pill p-violet">${l.asset_class}</span></td>
                <td class="mono">${l.acquisition_date}</td>
                <td class="num">${l.quantity_remaining}/${l.quantity_initial}</td>
                <td class="num">${fmtUsd(l.unit_cost)}</td>
                <td class="num" style="font-weight:700;">${fmtUsd(l.remaining_cost_basis)}</td>
              </tr>
            `).join('') : '<tr><td colspan="6" style="color:var(--muted)">No lots imported yet. Click "Import Broker CSV" above.</td></tr>'}
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Statutory Realized Capital Gains Schedule (STCG / LTCG)</span></div>
        <table>
          <thead><tr><th>Sale Date</th><th>Symbol</th><th>Term</th><th class="num">Days</th><th class="num">Proceeds</th><th class="num">FIFO Cost</th><th class="num">Gain/Loss</th></tr></thead>
          <tbody>
            ${inv.realized_schedule.length ? inv.realized_schedule.map(g => `
              <tr>
                <td class="mono">${g.sale_date}</td>
                <td class="mono" style="font-weight:700;">${g.symbol}</td>
                <td><span class="pill ${g.term_type === 'LTCG' ? 'p-green' : 'p-amber'}">${g.term_type}</span></td>
                <td class="num">${g.holding_days}d</td>
                <td class="num">${fmtUsd(g.proceeds)}</td>
                <td class="num">${fmtUsd(g.cost_basis)}</td>
                <td class="num" style="font-weight:700; color:${g.realized_gain >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${fmtUsd(g.realized_gain)}</td>
              </tr>
            `).join('') : '<tr><td colspan="7" style="color:var(--muted)">No realized sales recorded yet.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.querySelector('#ingestBrokerBtn').addEventListener('click', async () => {
    try {
      cachedSampleCsv = container.querySelector('#brokerCsvInput').value;
      const d = await apiJson('/api/investments/ingest', {
        method: 'POST',
        body: JSON.stringify({ csv_content: cachedSampleCsv }),
      });
      toast(`Posted ${d.ingestion.trades_processed} post-trade settlements into Core GL!`);
      await refreshCore();
    } catch (e) { alert(e.message); }
  });
}
