/* Shared API Client, Formatters, & Reactive State Store */
export const store = {
  core: null,
  remit: null,
  selectedRemitIdx: 0,
  dbPage: 1,
  dbTotalPages: 1,
  activeView: 'dashboard',
  listeners: [],
  subscribe(fn) { this.listeners.push(fn); },
  notify() { this.listeners.forEach(fn => fn(this)); },
};

export function fmtUsd(n) {
  const v = Number(n || 0);
  return (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
export function fmtNum(n) {
  return Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
export function fmtInt(n) {
  return Number(n || 0).toLocaleString('en-US');
}
export function toast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 3200);
}

export async function apiJson(url, opts = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'API request failed');
  return data;
}

export async function refreshCore() {
  store.core = await apiJson('/api/core/overview');
  const telLat = document.getElementById('telLatency');
  const telVch = document.getElementById('telVouchers');
  const telBal = document.getElementById('telBalance');
  if (telLat) telLat.textContent = (store.core.query_latency_ms || 0) + ' ms';
  if (telVch) telVch.textContent = fmtInt(store.core.total_vouchers_count || 0);
  if (telBal) telBal.textContent = store.core.statements.balance_sheet.is_balanced ? '✓ 0.00 Var' : '⚠ Check';
  store.notify();
  return store.core;
}
