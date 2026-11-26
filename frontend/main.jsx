import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Sidebar, SidebarLink, Spinner, ThemeProvider, ThemeToggle } from '@utkristi/ui';
import {
  ArrowLeftRight, BookOpen, CircleHelp, FileChartColumn, Globe2, LayoutGrid, ListTree,
  LogOut, ReceiptText, Upload, WalletCards,
} from 'lucide-react';
import '@utkristi/ui/css';
import './styles.css';

import { ClearRemitLogo } from './brand';
import MarketingPage from './marketing';
import publicRoutes from './public-routes.json';
import AuthPage from './auth';
import { ErrorBoundary, ErrorPage } from './errors';
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

const NAV_GROUPS = [
  ['Workspace', [
    ['dashboard', 'Overview', LayoutGrid, CommandCenter],
  ]],
  ['Accounting', [
    ['vouchers', 'Vouchers & daybook', ReceiptText, VouchersDaybook],
    ['coa', 'Chart of accounts', ListTree, ChartOfAccounts],
    ['statements', 'Statements & aging', FileChartColumn, FinancialStatements],
  ]],
  ['Treasury', [
    ['fx', 'FX & revaluation', Globe2, FxTreasury],
    ['remit', 'Remittance & tax', ArrowLeftRight, RemittanceHub],
    ['invest', 'Investment tax lots', WalletCards, InvestmentTaxLots],
  ]],
  ['Data', [
    ['bulk', 'Bank imports', Upload, BulkStreamer],
  ]],
];
const tabs = new Map(NAV_GROUPS.flatMap(([, items]) => items).map(([key, ...item]) => [key, item]));
const mobileQuery = '(max-width: 780px)';

function activeTab() {
  return location.hash.slice(1) || 'dashboard';
}

function FinancialOsWorkspace({ user, onSignedOut }) {
  const [tab, setTab] = useState(activeTab);
  const [mobile, setMobile] = useState(() => matchMedia(mobileQuery).matches);
  const [mobileCollapsed, setMobileCollapsed] = useState(true);
  const [core, setCore] = useState(null);
  const [error, setError] = useState('');
  const [signOutError, setSignOutError] = useState('');
  const [drillAccount, setDrillAccount] = useState(null);

  async function refreshCore() {
    setError('');
    try {
      setCore(await apiFetch('/api/core/overview'));
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    refreshCore();
    const media = matchMedia(mobileQuery);
    const onResize = () => setMobile(media.matches);
    function onHash() {
      setTab(activeTab());
      setMobileCollapsed(true);
    }
    media.addEventListener('change', onResize);
    window.addEventListener('hashchange', onHash);
    return () => {
      media.removeEventListener('change', onResize);
      window.removeEventListener('hashchange', onHash);
    };
  }, []);

  function selectTab(key) {
    location.hash = key;
    setMobileCollapsed(true);
    window.scrollTo(0, 0);
  }

  async function signOut() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
      onSignedOut();
    } catch (err) {
      setSignOutError(err.message);
    }
  }

  const [label, , Module] = tabs.get(tab) ?? [];
  return (
    <div className="workspace-shell">
      <a className="skip" href="#workspace-content" onClick={event => {
        event.preventDefault();
        document.getElementById('workspace-content').focus();
      }}>Skip to content</a>
      <Sidebar
        className="workspace-sidebar"
        collapsible={mobile}
        collapsed={mobile && mobileCollapsed}
        onCollapsedChange={setMobileCollapsed}
        heading={<a href="/" className="brand"><ClearRemitLogo size={30} /></a>}
      >
        <a href="#dashboard" className="workspace-entity" onClick={event => {
          event.preventDefault();
          selectTab('dashboard');
        }}>
          <span className="entity-avatar" aria-hidden="true">{user.company_name.slice(0, 2).toUpperCase()}</span>
          <span><strong>{user.company_name}</strong><small>Financial workspace</small></span>
        </a>
        <nav aria-label="Workspace">
          {NAV_GROUPS.map(([group, items]) => <div className="nav-group" key={group}>
            <p>{group}</p>
            {items.map(([key, name, Icon]) => <SidebarLink key={key} href={`#${key}`} label={name}
              icon={<Icon size={17} strokeWidth={1.65} />} aria-current={tab === key ? 'page' : undefined}
              onClick={event => { event.preventDefault(); selectTab(key); }} />)}
          </div>)}
        </nav>
        <div className="sidebar-foot">
          <SidebarLink href="/docs" label="Documentation" icon={<CircleHelp size={17} />} />
        </div>
      </Sidebar>
      <div className="workspace-body">
        <header className="workspace-bar">
          <div className="workspace-location"><BookOpen size={16} aria-hidden="true" /><span>{label || 'Page not found'}</span></div>
          <div className="workspace-tools">
            <span className="workspace-user">{user.full_name}</span>
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={signOut} iconLeft={<LogOut size={15} />}>Sign out</Button>
          </div>
        </header>
        <main className="main stack" id="workspace-content" tabIndex={-1}>
          {signOutError && <div className="error" role="alert">{signOutError}</div>}
          {error && <div className="error workspace-notice" role="alert">
            <span>{error}</span><Button variant="ghost" onClick={refreshCore}>Retry</Button>
          </div>}
          {!Module ? <ErrorPage notFound /> : core ? (
            <Module core={core} onRefresh={refreshCore} onSelectTab={selectTab} onDrillAccount={setDrillAccount} />
          ) : !error && <div className="loading" role="status"><Spinner /> Loading workspace</div>}
        </main>
      </div>
      <LedgerModal accountCode={drillAccount} onClose={() => setDrillAccount(null)} />
    </div>
  );
}

function RootRouter() {
  const path = location.pathname.replace(/\/+$/, '') || '/';
  const [session, setSession] = useState(null);
  const [sessionError, setSessionError] = useState('');
  const requiresSession = path === '/app' || path === '/auth';

  useEffect(() => {
    if (requiresSession) {
      apiFetch('/api/auth/me').then(setSession).catch(err => setSessionError(err.message));
    }
  }, [requiresSession]);

  if (requiresSession) {
    if (sessionError) return <ErrorPage description={sessionError} retry={() => location.reload()} />;
    if (!session) return <div className="loading" role="status"><Spinner /> Checking your session</div>;
    if (path === '/auth' || !session.user) {
      return <AuthPage registrationAvailable={session.registration_available} user={session.user} />;
    }
    return <FinancialOsWorkspace user={session.user} onSignedOut={() => location.assign('/auth')} />;
  }
  if (path === '/' || Object.hasOwn(publicRoutes, path)) return <MarketingPage path={path} />;
  return <ErrorPage notFound />;
}

createRoot(document.getElementById('root')).render(
  <ThemeProvider defaultTheme="light">
    <ErrorBoundary><RootRouter /></ErrorBoundary>
  </ThemeProvider>,
);
