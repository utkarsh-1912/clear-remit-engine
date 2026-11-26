/* Component 2: Multi-Line Tally Voucher Composer & Server-Side Paginated Daybook */
import { store, apiJson, refreshCore, fmtUsd, fmtInt, toast } from '../api.js';

let draftLines = [
  { account_code: '6120', side: 'DR', amount: 1500, currency: 'USD', bill_ref: '', party_name: '' },
  { account_code: '1010', side: 'CR', amount: 1500, currency: 'USD', bill_ref: '', party_name: '' },
];

export function renderVouchersShell(container, { openLedgerDrawer }) {
  if (!store.core) return;
  const accOpts = store.core.accounts.map(a => `<option value="${a.code}">${a.code} — ${a.name} (${a.currency_code})</option>`).join('');

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Tally-Style Multi-Line Voucher Composer &amp; Indexed Daybook</h2>
        <div class="topbar-sub">Unlimited Split Debit/Credit Rows • Live Dr == Cr Balance Guard • Sub-15ms Paginated Search</div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">Multi-Line Double-Entry Voucher Composer</span>
        <div class="actions">
          <span id="vchLiveBalancePill" class="pill p-green">✓ Balanced ($0.00 Variance)</span>
          <button class="sm" id="addSplitLineBtn">+ Add Split Line</button>
          <button class="primary" id="commitVoucherBtn">Commit Immutable Voucher</button>
        </div>
      </div>

      <div class="form-row">
        <div class="field"><label>Voucher Type</label>
          <select id="vType"><option>JOURNAL</option><option>RECEIPT</option><option>PAYMENT</option><option>SALES</option><option>PURCHASE</option><option>CONTRA_FX</option></select>
        </div>
        <div class="field"><label>Effective Date</label><input id="vDate" value="2026-11-10" class="mono" style="width:120px" /></div>
        <div class="field" style="flex:1"><label>Narration / Audit Memo</label><input id="vNarration" value="Multi-line commercial settlement" style="width:100%" /></div>
        <div class="field"><label>Source Ref</label><input id="vRef" placeholder="INV / Wire Ref" style="width:140px" /></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>GL Account</th><th>Dr / Cr</th><th class="num">Amount</th><th>Ccy</th><th>Bill-by-Bill Ref</th><th>Party Name</th><th></th>
          </tr>
        </thead>
        <tbody id="draftLinesBody"></tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">Indexed Daybook (<span id="daybookTotalLabel">0</span> Vouchers • <span id="daybookLatency">—</span>)</span>
        <div class="actions">
          <input id="dbSearch" placeholder="Search voucher #, narration, ref..." style="width:220px;" />
          <select id="dbTypeFilter">
            <option value="ALL">All Types</option>
            <option value="RECEIPT">RECEIPT</option>
            <option value="PAYMENT">PAYMENT</option>
            <option value="JOURNAL">JOURNAL</option>
            <option value="CONTRA_FX">CONTRA_FX</option>
            <option value="TRADE_SETTLEMENT">TRADE_SETTLEMENT</option>
            <option value="REVALUATION">REVALUATION</option>
            <option value="REVERSAL">REVERSAL</option>
          </select>
          <button class="sm" id="dbPrev">← Prev</button>
          <span id="dbPageInfo" class="mono" style="font-size:11px; color:var(--muted);">1 / 1</span>
          <button class="sm" id="dbNext">Next →</button>
        </div>
      </div>
      <table>
        <thead><tr><th>Voucher #</th><th>Type</th><th>Date</th><th>Narration &amp; Lines (Click GL to Drill Down)</th><th>Status</th><th class="num">USD</th><th>Action</th></tr></thead>
        <tbody id="fullDaybookBody"></tbody>
      </table>
    </div>
  `;

  function renderDraftRows() {
    const tbody = container.querySelector('#draftLinesBody');
    tbody.innerHTML = draftLines.map((l, idx) => `
      <tr>
        <td><select data-idx="${idx}" data-field="account_code" style="width:260px">${accOpts}</select></td>
        <td>
          <select data-idx="${idx}" data-field="side" style="width:70px">
            <option value="DR" ${l.side === 'DR' ? 'selected' : ''}>Dr</option>
            <option value="CR" ${l.side === 'CR' ? 'selected' : ''}>Cr</option>
          </select>
        </td>
        <td class="num"><input type="number" step="0.01" data-idx="${idx}" data-field="amount" value="${l.amount}" class="mono" style="width:120px; text-align:right" /></td>
        <td><input data-idx="${idx}" data-field="currency" value="${l.currency}" class="mono" style="width:65px" /></td>
        <td><input data-idx="${idx}" data-field="bill_ref" value="${l.bill_ref}" placeholder="INV-..." style="width:110px" /></td>
        <td><input data-idx="${idx}" data-field="party_name" value="${l.party_name}" placeholder="Party..." style="width:130px" /></td>
        <td>${draftLines.length > 2 ? `<button class="rose sm" data-remove="${idx}">✕</button>` : ''}</td>
      </tr>
    `).join('');

    draftLines.forEach((l, idx) => {
      const sel = tbody.querySelector(`select[data-idx="${idx}"][data-field="account_code"]`);
      if (sel) sel.value = l.account_code;
    });

    tbody.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('change', () => {
        const idx = Number(el.getAttribute('data-idx'));
        const f = el.getAttribute('data-field');
        draftLines[idx][f] = f === 'amount' ? parseFloat(el.value || '0') : el.value;
        updateBalanceBadge();
      });
    });
    tbody.querySelectorAll('[data-remove]').forEach(btn => {
      btn.addEventListener('click', () => {
        draftLines.splice(Number(btn.getAttribute('data-remove')), 1);
        renderDraftRows();
        updateBalanceBadge();
      });
    });
    updateBalanceBadge();
  }

  function updateBalanceBadge() {
    const dr = draftLines.filter(l => l.side === 'DR').reduce((s, l) => s + Number(l.amount || 0), 0);
    const cr = draftLines.filter(l => l.side === 'CR').reduce((s, l) => s + Number(l.amount || 0), 0);
    const diff = Math.abs(dr - cr);
    const pill = container.querySelector('#vchLiveBalancePill');
    if (diff < 0.005) {
      pill.className = 'pill p-green';
      pill.textContent = `✓ Balanced (${fmtUsd(dr)} Dr == ${fmtUsd(cr)} Cr)`;
    } else {
      pill.className = 'pill p-rose';
      pill.textContent = `⚠ Imbalance: ${fmtUsd(diff)} (Dr ${fmtUsd(dr)} vs Cr ${fmtUsd(cr)})`;
    }
  }

  container.querySelector('#addSplitLineBtn').addEventListener('click', () => {
    draftLines.push({ account_code: '4090', side: 'DR', amount: 0, currency: 'USD', bill_ref: '', party_name: '' });
    renderDraftRows();
  });

  container.querySelector('#commitVoucherBtn').addEventListener('click', async () => {
    try {
      const lines = draftLines.map(l => ({
        account_code: l.account_code,
        debit: l.side === 'DR' ? Number(l.amount) : 0,
        credit: l.side === 'CR' ? Number(l.amount) : 0,
        native_currency: l.currency || 'USD',
        bill_ref: l.bill_ref || null,
        party_name: l.party_name || null,
      }));
      const res = await apiJson('/api/core/vouchers', {
        method: 'POST',
        body: JSON.stringify({
          voucher_type: container.querySelector('#vType').value,
          effective_date: container.querySelector('#vDate').value,
          narration: container.querySelector('#vNarration').value,
          source_ref: container.querySelector('#vRef').value || null,
          lines,
        }),
      });
      toast('Committed ' + res.voucher_number);
      await refreshCore();
      await loadPaginatedDaybook(container, openLedgerDrawer);
    } catch (e) { alert(e.message); }
  });

  container.querySelector('#dbSearch').addEventListener('input', () => { store.dbPage = 1; loadPaginatedDaybook(container, openLedgerDrawer); });
  container.querySelector('#dbTypeFilter').addEventListener('change', () => { store.dbPage = 1; loadPaginatedDaybook(container, openLedgerDrawer); });
  container.querySelector('#dbPrev').addEventListener('click', () => { if (store.dbPage > 1) { store.dbPage--; loadPaginatedDaybook(container, openLedgerDrawer); } });
  container.querySelector('#dbNext').addEventListener('click', () => { if (store.dbPage < store.dbTotalPages) { store.dbPage++; loadPaginatedDaybook(container, openLedgerDrawer); } });

  renderDraftRows();
  loadPaginatedDaybook(container, openLedgerDrawer);
}

export async function loadPaginatedDaybook(container, openLedgerDrawer) {
  const q = encodeURIComponent(container.querySelector('#dbSearch')?.value || '');
  const t = encodeURIComponent(container.querySelector('#dbTypeFilter')?.value || 'ALL');
  const data = await apiJson(`/api/core/vouchers?page=${store.dbPage}&page_size=25&search=${q}&voucher_type=${t}`);
  store.dbTotalPages = data.total_pages || 1;

  container.querySelector('#daybookTotalLabel').textContent = fmtInt(data.total_count);
  container.querySelector('#daybookLatency').textContent = data.query_latency_ms + ' ms';
  container.querySelector('#dbPageInfo').textContent = `${data.page} / ${data.total_pages}`;

  const tbody = container.querySelector('#fullDaybookBody');
  tbody.innerHTML = data.items.map(v => {
    const linesHtml = v.lines.map(l => `
      <div style="font-size:10.5px; color:var(--muted);" class="mono">
        ${l.functional_debit > 0 ? 'Dr' : 'Cr'}
        <span class="clickable" data-drill="${l.account_code}" style="color:var(--cyan)">${l.account_code}</span>
        ${l.account_name}: ${fmtUsd(l.functional_debit || l.functional_credit)}
        ${l.bill_ref ? `<span class="pill p-cyan" style="font-size:9px; padding:0 5px;">${l.bill_ref}</span>` : ''}
      </div>
    `).join('');
    const revBtn = v.status === 'POSTED'
      ? `<button class="rose sm" data-rev="${v.voucher_id}">Reverse</button>`
      : `<span style="color:var(--dim); font-size:11px;">Reversed</span>`;
    return `
      <tr>
        <td class="mono" style="color:var(--cyan); font-weight:700;">${v.voucher_number}</td>
        <td><span class="pill p-violet">${v.voucher_type}</span></td>
        <td class="mono">${v.effective_date}</td>
        <td><b>${v.narration}</b>${linesHtml}</td>
        <td><span class="pill ${v.status === 'POSTED' ? 'p-green' : 'p-amber'}">${v.status}</span></td>
        <td class="num" style="font-weight:700;">${fmtUsd(v.total_functional_amount)}</td>
        <td>${revBtn}</td>
      </tr>
    `;
  }).join('');

  tbody.querySelectorAll('[data-drill]').forEach(el => {
    el.addEventListener('click', () => openLedgerDrawer(el.getAttribute('data-drill')));
  });
  tbody.querySelectorAll('[data-rev]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        const res = await apiJson(`/api/core/vouchers/${btn.getAttribute('data-rev')}/reverse`, {
          method: 'POST',
          body: JSON.stringify({ reversal_date: '2026-11-10', reason: 'Audit Reversal' }),
        });
        toast('Reversed via ' + res.voucher_number);
        await refreshCore();
        await loadPaginatedDaybook(container, openLedgerDrawer);
      } catch (e) { alert(e.message); }
    });
  });
}
