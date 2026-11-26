/* Main Modular Application Shell — ClearLedger Prime v5.0 */
import { store, apiJson, refreshCore, toast } from './api.js';
import { renderDashboard } from './components/dashboard.js';
import { renderVouchersShell } from './components/vouchers.js';
import { renderCoaManager, openAccountLedgerDrawer } from './components/coa_ledger.js';
import { renderFxDesk } from './components/fx_desk.js';
import { renderRemittanceHub } from './components/remittance.js';
import { renderInvestments } from './components/investments.js';
import { renderStatements } from './components/statements.js';
import { renderBulkStreamer } from './components/bulk_streamer.js';

const VIEWS = ['dashboard', 'vouchers', 'coa', 'fx', 'remit', 'invest', 'statements', 'bulk'];

const COMMANDS = [
  { label: 'Go to Executive Command Center', kbd: 'Alt+1', run: () => navigate('dashboard') },
  { label: 'Open Multi-Line Vouchers & Indexed Daybook', kbd: 'Alt+2', run: () => navigate('vouchers') },
  { label: 'Open Chart of Accounts & Ledger Drill-Down', kbd: 'Alt+3', run: () => navigate('coa') },
  { label: 'Open FX Treasury & IAS 21 Revaluation Desk', kbd: 'Alt+4', run: () => navigate('fx') },
  { label: 'Open Cross-Border Remittance Hub & DTAA Tax', kbd: 'Alt+5', run: () => navigate('remit') },
  { label: 'Open Post-Trade Investment Tax-Lots', kbd: 'Alt+6', run: () => navigate('invest') },
  { label: 'Open Live Financial Statements, Cash Flow & AR Aging', kbd: 'Alt+7', run: () => navigate('statements') },
  { label: 'Open ⚡ GB-Scale Data Streamer & Stress Benchmark', kbd: 'Alt+8', run: () => navigate('bulk') },
  { label: 'Inspect Operating Bank Cash (1010) Running Ledger', kbd: 'GL', run: () => openAccountLedgerDrawer('1010') },
  { label: 'Inspect EUR Nostro (1011) Running Ledger', kbd: 'GL', run: () => openAccountLedgerDrawer('1011') },
  { label: 'Download Tally Prime Voucher XML', kbd: 'XML', run: () => window.open('/api/export/tally', '_blank') },
  { label: 'Reset Demo Core Database', kbd: 'RESET', run: () => resetDemo() },
];

export function navigate(view) {
  store.activeView = view;
  VIEWS.forEach(v => {
    const cap = v.charAt(0).toUpperCase() + v.slice(1);
    document.getElementById('nav' + cap)?.classList.toggle('active', v === view);
  });
  renderActiveView();
}

function renderActiveView() {
  const stage = document.getElementById('appStage');
  if (!stage || !store.core) return;
  const ctx = { navigate, openLedgerDrawer: openAccountLedgerDrawer, openCmdPalette };

  switch (store.activeView) {
    case 'dashboard': renderDashboard(stage, ctx); break;
    case 'vouchers': renderVouchersShell(stage, ctx); break;
    case 'coa': renderCoaManager(stage, ctx); break;
    case 'fx': renderFxDesk(stage, ctx); break;
    case 'remit': renderRemittanceHub(stage, ctx); break;
    case 'invest': renderInvestments(stage, ctx); break;
    case 'statements': renderStatements(stage, ctx); break;
    case 'bulk': renderBulkStreamer(stage, ctx); break;
  }
}

export function openCmdPalette() {
  const modal = document.getElementById('cmdModal');
  const inp = document.getElementById('cmdSearch');
  modal.classList.remove('hidden');
  inp.value = '';
  drawCmdList('');
  inp.focus();
}

export function closeCmdPalette() {
  document.getElementById('cmdModal').classList.add('hidden');
}

function drawCmdList(query) {
  const q = query.toLowerCase();
  const list = document.getElementById('cmdList');
  const matches = COMMANDS.filter(c => c.label.toLowerCase().includes(q));
  list.innerHTML = matches.map((c, idx) => `
    <div class="cmd-item" data-cmd-idx="${COMMANDS.indexOf(c)}">
      <span>${c.label}</span><span class="kbd">${c.kbd}</span>
    </div>
  `).join('');
  list.querySelectorAll('[data-cmd-idx]').forEach(el => {
    el.addEventListener('click', () => {
      COMMANDS[Number(el.getAttribute('data-cmd-idx'))].run();
      closeCmdPalette();
    });
  });
}

async function resetDemo() {
  await apiJson('/api/core/reset-demo', { method: 'POST' });
  toast('Demo Core Ledger Reset!');
  await refreshCore();
}

// Wire Sidebar Navigation, Shortcuts, & Global Modals
document.addEventListener('DOMContentLoaded', async () => {
  VIEWS.forEach(v => {
    const cap = v.charAt(0).toUpperCase() + v.slice(1);
    document.getElementById('nav' + cap)?.addEventListener('click', () => navigate(v));
  });

  document.getElementById('cmdTriggerBtn')?.addEventListener('click', openCmdPalette);
  document.getElementById('resetDemoBtn')?.addEventListener('click', resetDemo);
  document.getElementById('cmdSearch')?.addEventListener('input', e => drawCmdList(e.target.value));
  document.getElementById('cmdModal')?.addEventListener('click', e => { if (e.target.id === 'cmdModal') closeCmdPalette(); });
  document.getElementById('ledgerDrawerBackdrop')?.addEventListener('click', e => {
    if (e.target.id === 'ledgerDrawerBackdrop') e.target.classList.add('hidden');
  });

  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openCmdPalette(); }
    if (e.key === 'Escape') {
      closeCmdPalette();
      document.getElementById('ledgerDrawerBackdrop')?.classList.add('hidden');
    }
    if (e.altKey) {
      const m = { '1': 'dashboard', '2': 'vouchers', '3': 'coa', '4': 'fx', '5': 'remit', '6': 'invest', '7': 'statements', '8': 'bulk' };
      if (m[e.key]) { e.preventDefault(); navigate(m[e.key]); }
    }
  });

  store.subscribe(() => renderActiveView());

  // Check current session user & update sidebar profile chip
  try {
    const me = await apiJson('/api/auth/me');
    if (me.authenticated && me.user) {
      document.getElementById('userDisplayName').textContent = me.user.full_name;
      const authLink = document.getElementById('authActionLink');
      authLink.textContent = 'Sign Out';
      authLink.href = '#';
      authLink.addEventListener('click', async e => {
        e.preventDefault();
        await apiJson('/api/auth/logout', { method: 'POST' });
        window.location.href = '/auth';
      });
    }
  } catch (_) {}

  await refreshCore();
});
