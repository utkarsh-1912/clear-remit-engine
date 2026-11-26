/* Component 3: Chart of Accounts Manager & Tally Running-Balance Ledger Drill-Down Drawer */
import { store, apiJson, refreshCore, fmtUsd, fmtNum, toast } from '../api.js';

export function renderCoaManager(container, { openLedgerDrawer }) {
  if (!store.core) return;

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Chart of Accounts &amp; Ledger Master (Tally Groups + Finacle EGL)</h2>
        <div class="topbar-sub">Create Multi-Currency GL Accounts • Configure IAS 21 Monetary Flags • Click Any Account for Running Balance Statement</div>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><span class="card-title">Create New General Ledger Account</span></div>
      <div class="form-row">
        <div class="field"><label>GL Code</label><input id="coaCode" placeholder="e.g. 1015" class="mono" style="width:100px" /></div>
        <div class="field" style="flex:1"><label>Account Name</label><input id="coaName" placeholder="e.g. Singapore DBS Nostro Account (SGD)" style="width:100%" /></div>
        <div class="field"><label>Type</label>
          <select id="coaType"><option>ASSET</option><option>LIABILITY</option><option>EQUITY</option><option>REVENUE</option><option>EXPENSE</option></select>
        </div>
        <div class="field"><label>Tally Parent Group</label><input id="coaGroup" value="Current Assets > Nostro / Foreign Banks" style="width:240px" /></div>
        <div class="field"><label>Currency</label><input id="coaCcy" value="SGD" class="mono" style="width:70px" /></div>
        <div class="field"><label>IAS 21 Monetary</label><select id="coaMon"><option value="1">Yes (Revalue)</option><option value="0">No (Hist. Cost)</option></select></div>
        <button class="primary" id="coaCreateBtn">+ Create Ledger</button>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">Active Chart of Accounts (${store.core.accounts.length} Ledgers)</span>
        <select id="coaFilterType">
          <option value="ALL">All Account Types</option>
          <option value="ASSET">ASSET</option>
          <option value="LIABILITY">LIABILITY</option>
          <option value="EQUITY">EQUITY</option>
          <option value="REVENUE">REVENUE</option>
          <option value="EXPENSE">EXPENSE</option>
        </select>
      </div>
      <table>
        <thead>
          <tr><th>Code</th><th>Account Name</th><th>Type</th><th>Tally Parent Group</th><th>Ccy</th><th>IAS 21</th><th>Bill-by-Bill</th><th>Statement</th></tr>
        </thead>
        <tbody id="coaTableBody"></tbody>
      </table>
    </div>
  `;

  function drawTable() {
    const filter = container.querySelector('#coaFilterType').value;
    const rows = store.core.accounts.filter(a => filter === 'ALL' || a.account_type === filter);
    const tbody = container.querySelector('#coaTableBody');
    tbody.innerHTML = rows.map(a => `
      <tr>
        <td class="mono clickable" data-drill="${a.code}" style="color:var(--cyan); font-weight:700;">${a.code}</td>
        <td><b>${a.name}</b></td>
        <td><span class="pill p-violet">${a.account_type}</span></td>
        <td style="font-size:11.5px; color:var(--muted)">${a.parent_group}</td>
        <td><span class="pill p-cyan">${a.currency_code}</span></td>
        <td>${a.is_monetary ? '<span class="pill p-green">Monetary</span>' : '<span style="color:var(--dim); font-size:11px;">Historical</span>'}</td>
        <td>${a.enable_bill_by_bill ? '✓ Enabled' : '—'}</td>
        <td><button class="sm" data-drill="${a.code}">View Ledger →</button></td>
      </tr>
    `).join('');

    tbody.querySelectorAll('[data-drill]').forEach(el => {
      el.addEventListener('click', () => openLedgerDrawer(el.getAttribute('data-drill')));
    });
  }

  container.querySelector('#coaFilterType').addEventListener('change', drawTable);
  container.querySelector('#coaCreateBtn').addEventListener('click', async () => {
    try {
      const acc = await apiJson('/api/core/accounts', {
        method: 'POST',
        body: JSON.stringify({
          code: container.querySelector('#coaCode').value,
          name: container.querySelector('#coaName').value,
          account_type: container.querySelector('#coaType').value,
          parent_group: container.querySelector('#coaGroup').value,
          currency_code: container.querySelector('#coaCcy').value,
          is_monetary: container.querySelector('#coaMon').value === '1',
        }),
      });
      toast(`Created GL Account ${acc.code} — ${acc.name}`);
      await refreshCore();
    } catch (e) { alert(e.message); }
  });

  drawTable();
}

export async function openAccountLedgerDrawer(accountCode) {
  const backdrop = document.getElementById('ledgerDrawerBackdrop');
  const body = document.getElementById('ledgerDrawerBody');
  backdrop.classList.remove('hidden');
  body.innerHTML = '<div style="color:var(--muted)">Loading Tally Running-Balance Ledger...</div>';

  try {
    const data = await apiJson(`/api/core/accounts/${encodeURIComponent(accountCode)}/ledger`);
    const acc = data.account;
    body.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px;">
        <div>
          <span class="pill p-cyan">${acc.code} • ${acc.account_type} • ${acc.currency_code}</span>
          <h2 style="font-size:19px; margin-top:6px;">${acc.name}</h2>
          <div style="font-size:12px; color:var(--muted);">${acc.parent_group}</div>
        </div>
        <button class="sm" onclick="document.getElementById('ledgerDrawerBackdrop').classList.add('hidden')">✕ Close</button>
      </div>

      <div class="kpi-grid" style="margin-bottom:16px;">
        <div class="kpi-card" style="padding:12px;">
          <div class="kpi-label">Total Debits (USD)</div>
          <div class="kpi-val" style="font-size:18px; color:var(--cyan)">${fmtUsd(data.total_debit_usd)}</div>
        </div>
        <div class="kpi-card" style="padding:12px;">
          <div class="kpi-label">Total Credits (USD)</div>
          <div class="kpi-val" style="font-size:18px; color:var(--emerald)">${fmtUsd(data.total_credit_usd)}</div>
        </div>
        <div class="kpi-card" style="padding:12px;">
          <div class="kpi-label">Closing Balance (USD)</div>
          <div class="kpi-val" style="font-size:18px; color:#fff">${fmtUsd(data.closing_functional_balance)}</div>
          <div class="kpi-sub">Native: ${fmtNum(data.closing_native_balance)} ${acc.currency_code}</div>
        </div>
      </div>

      <table>
        <thead>
          <tr><th>Date</th><th>Voucher</th><th>Narration</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Running Bal</th></tr>
        </thead>
        <tbody>
          ${data.entries.length ? data.entries.map(e => `
            <tr>
              <td class="mono">${e.effective_date}</td>
              <td class="mono" style="color:var(--cyan)">${e.voucher_number}</td>
              <td style="font-size:11.5px;">${e.narration}${e.bill_ref ? ` <span class="pill p-cyan">${e.bill_ref}</span>` : ''}</td>
              <td class="num" style="color:var(--cyan)">${e.functional_debit > 0 ? fmtUsd(e.functional_debit) : '—'}</td>
              <td class="num" style="color:var(--emerald)">${e.functional_credit > 0 ? fmtUsd(e.functional_credit) : '—'}</td>
              <td class="num" style="font-weight:700;">${fmtUsd(e.running_functional_balance)}</td>
            </tr>
          `).join('') : '<tr><td colspan="6" style="color:var(--muted)">No postings yet in this ledger.</td></tr>'}
        </tbody>
      </table>
    `;
  } catch (e) {
    body.innerHTML = `<div style="color:var(--rose)">Error: ${e.message}</div>`;
  }
}
