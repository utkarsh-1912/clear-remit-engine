/* Component 4: Multi-Currency FX Treasury, Rate Matrix Editor, & IAS 21 Revaluation Desk */
import { store, apiJson, refreshCore, fmtUsd, fmtNum, toast } from '../api.js';

export function renderFxDesk(container) {
  if (!store.core) return;
  const nostroOpts = store.core.accounts
    .filter(a => a.currency_code !== 'USD' && a.account_type === 'ASSET')
    .map(a => `<option value="${a.code}">${a.code} — ${a.name} (${a.currency_code})</option>`).join('');

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Multi-Currency FX Treasury &amp; IAS 21 Revaluation Desk</h2>
        <div class="topbar-sub">Live FX Spot Rate Matrix • Nostro Contra Conversions (Realized FX) • Period-End IAS 21 Revaluation + Day-1 Auto-Reversal</div>
      </div>
      <div class="actions">
        <button id="fxPrevIas">Preview IAS 21</button>
        <button class="primary" id="fxCommitIas">Post Reval Voucher</button>
        <button class="emerald" id="fxCommitRevIas">Post + Day-1 Reversal</button>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header"><span class="card-title">Cross-Currency Nostro Conversion (Contra FX)</span></div>
        <div class="form-row">
          <div class="field"><label>From Foreign Account</label><select id="fxFromAcc">${nostroOpts}</select></div>
          <div class="field"><label>Native Amount</label><input type="number" id="fxAmt" value="10000" class="mono" style="width:120px" /></div>
          <div class="field"><label>Exec Rate (→USD)</label><input type="number" step="0.0001" id="fxExecRate" value="1.1050" class="mono" style="width:110px" /></div>
          <button class="primary" id="fxExecBtn">Convert to USD Bank</button>
        </div>
        <div id="fxConvertResult" style="font-size:12px; color:var(--emerald); margin-bottom:12px;"></div>

        <div class="card-header" style="margin-top:16px;"><span class="card-title">Upsert Date-Wise FX Spot Rate</span></div>
        <div class="form-row">
          <div class="field"><label>Date</label><input id="fxRateDate" value="2026-11-10" class="mono" style="width:115px" /></div>
          <div class="field"><label>Currency</label><input id="fxRateCcy" value="EUR" class="mono" style="width:70px" /></div>
          <div class="field"><label>Spot → USD</label><input type="number" step="0.0001" id="fxRateSpot" value="1.1120" class="mono" style="width:105px" /></div>
          <button id="fxSaveRateBtn">Update Rate</button>
        </div>

        <table>
          <thead><tr><th>Date</th><th>Pair</th><th class="num">Spot</th><th class="num">Buy</th><th class="num">Sell</th></tr></thead>
          <tbody>
            ${store.core.fx_rates.map(r => `
              <tr>
                <td class="mono">${r.rate_date}</td>
                <td class="mono" style="color:var(--cyan); font-weight:700;">${r.base_currency}/${r.quote_currency}</td>
                <td class="num">${r.spot_rate}</td>
                <td class="num">${r.buy_rate}</td>
                <td class="num">${r.sell_rate}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">IAS 21 Period-End Monetary Revaluation (As of 2026-11-10)</span>
          <span id="ias21Badge"></span>
        </div>
        <table>
          <thead><tr><th>Account</th><th class="num">Native Bal</th><th class="num">Book USD</th><th class="num">Close Rate</th><th class="num">Reval USD</th><th class="num">Unrealized FX</th></tr></thead>
          <tbody id="ias21Body"></tbody>
        </table>
      </div>
    </div>
  `;

  async function runIas(commit = false, autoRev = false) {
    try {
      const d = await apiJson('/api/fx/revalue', {
        method: 'POST',
        body: JSON.stringify({ as_of_date: '2026-11-10', commit_voucher: commit, auto_reverse_next_day: autoRev }),
      });
      container.querySelector('#ias21Badge').innerHTML =
        `<span class="pill ${d.total_unrealized_fx_gain_loss >= 0 ? 'p-green' : 'p-rose'}">Net Unrealized: ${fmtUsd(d.total_unrealized_fx_gain_loss)}</span>`;
      container.querySelector('#ias21Body').innerHTML = d.items.map(i => `
        <tr>
          <td><b>${i.account_code}</b> ${i.account_name}</td>
          <td class="num">${i.currency_code} ${fmtNum(i.native_balance)}</td>
          <td class="num">${fmtUsd(i.carrying_functional_value)}</td>
          <td class="num">${i.closing_spot_rate.toFixed(6)}</td>
          <td class="num">${fmtUsd(i.revalued_functional_value)}</td>
          <td class="num" style="font-weight:700; color:${i.unrealized_fx_delta >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${fmtUsd(i.unrealized_fx_delta)}</td>
        </tr>
      `).join('');
      if (commit) {
        toast('IAS 21 Revaluation Committed!');
        await refreshCore();
      }
    } catch (e) { alert(e.message); }
  }

  container.querySelector('#fxPrevIas').addEventListener('click', () => runIas(false, false));
  container.querySelector('#fxCommitIas').addEventListener('click', () => runIas(true, false));
  container.querySelector('#fxCommitRevIas').addEventListener('click', () => runIas(true, true));

  container.querySelector('#fxExecBtn').addEventListener('click', async () => {
    try {
      const d = await apiJson('/api/fx/convert', {
        method: 'POST',
        body: JSON.stringify({
          effective_date: '2026-11-10',
          from_account_code: container.querySelector('#fxFromAcc').value,
          to_account_code: '1010',
          from_amount_native: parseFloat(container.querySelector('#fxAmt').value),
          execution_rate_to_usd: parseFloat(container.querySelector('#fxExecRate').value),
        }),
      });
      container.querySelector('#fxConvertResult').textContent =
        `✓ ${d.voucher.voucher_number} | USD Received: ${fmtUsd(d.realized_usd_value)} | Realized FX: ${fmtUsd(d.realized_fx_gain_loss)}`;
      toast('FX Conversion Posted to Core GL!');
      await refreshCore();
    } catch (e) { alert(e.message); }
  });

  container.querySelector('#fxSaveRateBtn').addEventListener('click', async () => {
    try {
      const r = await apiJson('/api/fx/rate', {
        method: 'POST',
        body: JSON.stringify({
          rate_date: container.querySelector('#fxRateDate').value,
          base_currency: container.querySelector('#fxRateCcy').value,
          spot_rate: parseFloat(container.querySelector('#fxRateSpot').value),
        }),
      });
      toast(`Updated ${r.base_currency}/USD Spot Rate to ${r.spot_rate}`);
      await refreshCore();
    } catch (e) { alert(e.message); }
  });

  runIas(false, false);
}
