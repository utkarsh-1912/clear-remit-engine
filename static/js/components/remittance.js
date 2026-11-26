/* Component 5: Cross-Border Remittance Hub (ISO 20022 / MT940 / BAI2) + DTAA Tax Validator */
import { store, apiJson, refreshCore, fmtUsd, toast } from '../api.js';

export async function renderRemittanceHub(container) {
  if (!store.remit) {
    store.remit = await apiJson('/api/sample?fmt=iso20022');
  }

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>Cross-Border Remittance Hub &amp; DTAA Tax Compliance</h2>
        <div class="topbar-sub">ISO 20022 XML • SWIFT MT940 • BAI2 • Combinatorial Subset-Sum Short-Pay Solver • 1-Click Core GL Posting</div>
      </div>
      <div class="actions">
        <button class="primary" data-fmt="iso20022">ISO 20022 XML</button>
        <button data-fmt="mt940">SWIFT MT940</button>
        <button data-fmt="bai2">BAI2 Cash File</button>
        <button class="emerald" id="postAllRemitBtn">✓ Post All Reconciled to Core GL</button>
      </div>
    </div>

    <div class="grid-split">
      <div id="remitListCol"></div>
      <div class="card" id="remitDetailCol"></div>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">Cross-Border DTAA &amp; W-8BEN-E / Form 10F Withholding Tax Calculator</span>
        <span class="pill p-cyan">6 Bilateral Tax Corridors</span>
      </div>
      <div class="form-row">
        <div class="field"><label>Corridor</label>
          <select id="dtaaCorr">
            <option value="IN-US">IN-US (India → US)</option>
            <option value="US-IN">US-IN (US → India)</option>
            <option value="GB-US">GB-US (UK → US)</option>
            <option value="DE-US">DE-US (Germany → US)</option>
            <option value="SG-US">SG-US (Singapore → US)</option>
            <option value="CA-US">CA-US (Canada → US)</option>
          </select>
        </div>
        <div class="field"><label>Service Type</label>
          <select id="dtaaCat">
            <option value="TECHNICAL_SERVICES_FTS">Technical / Consulting (FTS)</option>
            <option value="SAAS_CLOUD">Standard B2B SaaS / Cloud</option>
            <option value="ROYALTY_IP">Software / IP Royalty</option>
            <option value="PROFESSIONAL_SERVICES">Offshore Professional Services</option>
          </select>
        </div>
        <div class="field"><label>Gross Invoice (USD)</label><input type="number" id="dtaaGross" value="24000" class="mono" style="width:120px" /></div>
        <div class="field"><label>Withheld by Buyer (USD)</label><input type="number" id="dtaaWht" value="4800" class="mono" style="width:120px" /></div>
        <button class="primary" id="dtaaVerifyBtn">Audit Treaty Rate</button>
      </div>
      <div id="dtaaResultBox" style="font-size:12.5px;"></div>
    </div>
  `;

  function drawRemit() {
    const listCol = container.querySelector('#remitListCol');
    const detailCol = container.querySelector('#remitDetailCol');
    listCol.innerHTML = store.remit.proposals.map((p, idx) => `
      <div class="tx-item ${idx === store.selectedRemitIdx ? 'selected' : ''}" data-ridx="${idx}">
        <div style="display:flex; justify-content:space-between;" class="mono">
          <b style="color:var(--cyan); font-size:12px;">${p.tx_id}</b>
          <b style="font-size:13px;">${fmtUsd(p.deposit_amount)}</b>
        </div>
        <div style="font-weight:600; font-size:13px; margin:3px 0;">${p.matched_customer_name}</div>
        <span class="pill ${p.status === 'AUTO_RECONCILED' ? 'p-green' : 'p-amber'}">${p.status}</span>
        <span class="pill p-violet">${p.match_method}</span>
      </div>
    `).join('');

    listCol.querySelectorAll('[data-ridx]').forEach(el => {
      el.addEventListener('click', () => {
        store.selectedRemitIdx = Number(el.getAttribute('data-ridx'));
        drawRemit();
      });
    });

    const p = store.remit.proposals[store.selectedRemitIdx];
    if (!p) return;

    const wfDeds = p.deductions.map(d => `
      <span class="wf-op">−</span>
      <div class="wf-box" style="border-color:${d.is_authorized ? 'var(--border)' : 'var(--amber)'}">
        <div style="font-size:10px; color:var(--muted)">${d.deduction_type.replace(/_/g, ' ')}</div>
        <div class="mono" style="font-weight:700; color:${d.is_authorized ? '#fda4af' : 'var(--amber)'}">${fmtUsd(d.amount)}</div>
      </div>
    `).join('');

    const disputeHtml = p.dispute_notice_draft ? `
      <div style="margin-top:14px; padding:12px; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.4); border-radius:10px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <b style="color:var(--amber); font-size:12px;">⚠ Unauthorized Short-Pay Dispute Notice Draft</b>
          <button class="sm" id="copyDisputeBtn">Copy Email</button>
        </div>
        <pre class="mono" style="font-size:11px; white-space:pre-wrap; color:#cbd5e1;">${p.dispute_notice_draft}</pre>
      </div>
    ` : '';

    detailCol.innerHTML = `
      <div class="card-header">
        <div>
          <h3 style="font-size:16px;">${p.tx_id} — ${p.matched_customer_name}</h3>
          <div style="font-size:12px; color:var(--muted); margin-top:2px;">${p.explanation_summary}</div>
        </div>
        <button class="emerald" id="postSingleRemitBtn">✓ Post Split Receipt to Core GL</button>
      </div>

      <div class="waterfall">
        <div class="wf-box"><div style="font-size:10px; color:var(--muted)">Gross AR</div><div class="mono" style="font-weight:700; color:var(--emerald)">${fmtUsd(p.total_gross_invoices)}</div></div>
        ${wfDeds}
        <span class="wf-op">=</span>
        <div class="wf-box" style="border-color:var(--cyan)"><div style="font-size:10px; color:var(--muted)">Net Deposit</div><div class="mono" style="font-weight:700; color:var(--cyan)">${fmtUsd(p.deposit_amount)}</div></div>
      </div>

      <table>
        <thead><tr><th>GL</th><th>Account &amp; Narration</th><th class="num">Debit</th><th class="num">Credit</th></tr></thead>
        <tbody>
          ${p.journal_entries.map(j => `
            <tr>
              <td class="mono">${j.account_code}</td>
              <td><b>${j.account_name}</b><br/><span style="font-size:11px; color:var(--muted)">${j.memo}</span></td>
              <td class="num" style="color:var(--cyan)">${j.debit > 0 ? fmtUsd(j.debit) : '—'}</td>
              <td class="num" style="color:var(--emerald)">${j.credit > 0 ? fmtUsd(j.credit) : '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${disputeHtml}
    `;

    detailCol.querySelector('#postSingleRemitBtn')?.addEventListener('click', async () => {
      try {
        const res = await apiJson('/api/remittance/post-to-ledger', {
          method: 'POST',
          body: JSON.stringify({
            tx_id: p.tx_id, effective_date: '2026-11-10',
            customer_name: p.matched_customer_name,
            explanation_summary: p.explanation_summary,
            journal_entries: p.journal_entries,
          }),
        });
        toast(`Posted ${p.tx_id} as ${res.voucher_number} in Core GL!`);
        await refreshCore();
      } catch (e) { alert(e.message); }
    });

    detailCol.querySelector('#copyDisputeBtn')?.addEventListener('click', () => {
      navigator.clipboard.writeText(p.dispute_notice_draft);
      toast('Dispute Email Copied to Clipboard!');
    });
  }

  container.querySelectorAll('[data-fmt]').forEach(btn => {
    btn.addEventListener('click', async () => {
      store.remit = await apiJson('/api/sample?fmt=' + btn.getAttribute('data-fmt'));
      store.selectedRemitIdx = 0;
      drawRemit();
    });
  });

  container.querySelector('#postAllRemitBtn').addEventListener('click', async () => {
    let count = 0;
    for (const p of store.remit.proposals) {
      await apiJson('/api/remittance/post-to-ledger', {
        method: 'POST',
        body: JSON.stringify({
          tx_id: p.tx_id, effective_date: '2026-11-10',
          customer_name: p.matched_customer_name,
          explanation_summary: p.explanation_summary,
          journal_entries: p.journal_entries,
        }),
      });
      count++;
    }
    toast(`Atomically posted all ${count} remittance vouchers into Core GL!`);
    await refreshCore();
  });

  async function runDtaa() {
    const d = await apiJson('/api/tax-audit', {
      method: 'POST',
      body: JSON.stringify({
        corridor_code: container.querySelector('#dtaaCorr').value,
        service_category: container.querySelector('#dtaaCat').value,
        gross_amount: parseFloat(container.querySelector('#dtaaGross').value || '0'),
        withheld_amount: parseFloat(container.querySelector('#dtaaWht').value || '0'),
      }),
    });
    const ok = d.status === 'COMPLIANT_TREATY_RATE';
    container.querySelector('#dtaaResultBox').innerHTML = `
      <div style="padding:12px; border-radius:8px; background:${ok ? 'rgba(16,185,129,0.08)' : 'rgba(245,158,11,0.08)'}; border:1px solid ${ok ? 'var(--emerald)' : 'var(--amber)'}">
        <span class="pill ${ok ? 'p-green' : 'p-amber'}">${d.status.replace(/_/g, ' ')}</span>
        <b style="margin-left:8px;">Actual: ${d.actual_withheld_pct}% (${fmtUsd(d.actual_withheld_amount)}) vs. Treaty Cap: ${d.expected_treaty_pct}% (${fmtUsd(d.expected_treaty_amount)})</b>
        <p style="margin-top:6px;">${d.recommendation}</p>
        <div style="font-size:11px; color:var(--muted); margin-top:4px;"><b>Required Forms:</b> ${d.required_forms.join(' • ')} | <b>FTC:</b> ${d.ftc_claim_form}</div>
      </div>
    `;
  }

  container.querySelector('#dtaaVerifyBtn').addEventListener('click', runDtaa);
  drawRemit();
  runDtaa();
}
