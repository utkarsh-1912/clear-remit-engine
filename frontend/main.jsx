import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Badge, Button, Sidebar, SidebarLink, Spinner, ThemeProvider, ThemeToggle,
} from '@utkristi/ui';
import {
  Banknote, BookOpen, FileSpreadsheet, Globe2, Layers3, LogOut, RotateCcw,
  TrendingUp, Zap,
} from 'lucide-react';
import '@utkristi/ui/css';
import './styles.css';

import { ClearLedgerLogo, LedgyMascot } from './brand';
import MarketingPage from './marketing';
import AuthPage from './auth';
import { ErrorBoundary } from './errors';
import { apiFetch } from './core-os/utils';
import CommandCenter from './core-os/CommandCenter';
import VouchersDaybook from './core-os/VouchersDaybook';
import ChartOfAccounts from './core-os/ChartOfAccounts';
import FxTreasury from './core-os/FxTreasury';
import RemittanceHub from './core-os/RemittanceHub';
import InvestmentTaxLots from './core-os/InvestmentTaxLots';
import FinancialStatements from './core-os/FinancialStatements';
import BulkStreamer from './core-os/BulkStreamer';
import LedgerModal from './core-os/LedgerModal';

const NAV_TABS = [
  ['dashboard', 'Command Center', Banknote],
  ['vouchers', 'Vouchers & Daybook', FileSpreadsheet],
  ['coa', 'Chart of Accounts', BookOpen],
  ['fx', 'FX & IAS 21 Reval', Globe2],
  ['remit', 'Remittance & DTAA', Layers3],
  ['invest', 'Investment Tax-Lots', TrendingUp],
  ['statements', 'Statements & Aging', FileSpreadsheet],
  ['bulk', 'GB Data Streamer', Zap],
];

function FinancialOsWorkspace({ onNavigate, user, onUserChange }) {
  const [tab, setTab] = useState(() => location.hash.slice(1) || 'dashboard');
  const [core, setCore] = useState(null);
  const [error, setError] = useState('');
  const [drillAccount, setDrillAccount] = useState(null);

  async function refreshCore() {
    try {
      const data = await apiFetch('/api/core/overview');
      setCore(data);
      setError('');
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    refreshCore();
    function onHash() { setTab(location.hash.slice(1) || 'dashboard'); }
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  function selectTab(key) {
    setTab(key);
    location.hash = key;
  }

  async function handleResetDemo() {
    await apiFetch('/api/core/reset-demo', { method: 'POST' });
    await refreshCore();
  }

  async function handleSignOut() {
    await apiFetch('/api/auth/logout', { method: 'POST' });
    onUserChange(null);
    onNavigate('/auth');
  }

  return (
    <div className="workspace-shell">
      <Sidebar
        className="workspace-sidebar"
        heading={
          <a href="/" onClick={e => { e.preventDefault(); onNavigate('/'); }} className="brand">
            <ClearLedgerLogo size={30} showTagline={false} />
          </a>
        }
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingInline: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <LedgyMascot size={28} />
            <span style={{ fontSize: '0.78rem', color: 'var(--ut-ink-2)' }}>
              {user ? user.full_name : 'Evaluator Mode'}
            </span>
          </div>
          <ThemeToggle />
        </div>

        <nav aria-label="Financial OS modules">
          {NAV_TABS.map(([key, label, Icon]) => (
            <SidebarLink
              key={key}
              href={`#${key}`}
              label={label}
              icon={<Icon size={17} />}
              aria-current={tab === key ? 'page' : undefined}
              onClick={e => { e.preventDefault(); selectTab(key); }}
            />
          ))}
        </nav>

        <div className="sidebar-foot" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
          {core && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
              <Badge tone={core.statements.balance_sheet.is_balanced ? 'ok' : 'bad'}>
                {core.statements.balance_sheet.is_balanced ? 'GL Balanced' : 'Check GL'}
              </Badge>
              <span>{core.query_latency_ms} ms</span>
            </div>
          )}
          <div className="actions">
            <Button variant="ghost" size="sm" onClick={handleResetDemo} iconLeft={<RotateCcw size={13} />}>
              Reset Ledger
            </Button>
            {user ? (
              <Button variant="ghost" size="sm" onClick={handleSignOut} iconLeft={<LogOut size={13} />}>
                Sign Out
              </Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => onNavigate('/auth')}>
                Sign In
              </Button>
            )}
          </div>
        </div>
      </Sidebar>

      <main className="main stack">
        {error && <div className="error">{error}</div>}
        {!core ? (
          <div className="loading"><Spinner /> Loading ClearLedger Prime Core Engine…</div>
        ) : tab === 'vouchers' ? (
          <VouchersDaybook core={core} onRefresh={refreshCore} onDrillAccount={setDrillAccount} />
        ) : tab === 'coa' ? (
          <ChartOfAccounts core={core} onRefresh={refreshCore} onDrillAccount={setDrillAccount} />
        ) : tab === 'fx' ? (
          <FxTreasury core={core} onRefresh={refreshCore} />
        ) : tab === 'remit' ? (
          <RemittanceHub onRefresh={refreshCore} />
        ) : tab === 'invest' ? (
          <InvestmentTaxLots core={core} onRefresh={refreshCore} />
        ) : tab === 'statements' ? (
          <FinancialStatements core={core} onDrillAccount={setDrillAccount} />
        ) : tab === 'bulk' ? (
          <BulkStreamer core={core} onRefresh={refreshCore} />
        ) : (
          <CommandCenter core={core} onSelectTab={selectTab} onDrillAccount={setDrillAccount} />
        )}
      </main>

      <LedgerModal accountCode={drillAccount} onClose={() => setDrillAccount(null)} />
    </div>
  );
}

function RootRouter() {
  const [pathname, setPathname] = useState(() => location.pathname);
  const [user, setUser] = useState(null);

  useEffect(() => {
    fetch('/api/auth/me')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d?.authenticated) setUser(d.user); })
      .catch(() => {});

    function onPop() { setPathname(location.pathname); }
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  function navigate(path) {
    if (path !== pathname) {
      window.history.pushState({}, '', path);
      setPathname(path);
      window.scrollTo(0, 0);
    }
  }

  if (pathname.startsWith('/auth')) {
    return <AuthPage onNavigate={navigate} onAuthenticated={setUser} />;
  }
  if (pathname.startsWith('/app')) {
    return <FinancialOsWorkspace onNavigate={navigate} user={user} onUserChange={setUser} />;
  }
  return <MarketingPage onNavigate={navigate} />;
}

createRoot(document.getElementById('root')).render(
  <ThemeProvider defaultTheme="light">
    <ErrorBoundary>
      <RootRouter />
    </ErrorBoundary>
  </ThemeProvider>,
);
