import React, { useState } from 'react';
import {
  Badge, Button, Card, CardBody, CardHeader, Field, Input, Spinner, Tabs, ThemeToggle,
} from '@utkristi/ui';
import { ArrowLeft, ArrowRight, ShieldCheck } from 'lucide-react';
import { ClearLedgerLogo, LedgyMascot } from './brand';

export default function AuthPage({ onNavigate, onAuthenticated }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const payload = mode === 'login'
        ? { email, password }
        : { email, password, full_name: fullName, company_name: companyName };

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Authentication failed');
      if (onAuthenticated) onAuthenticated(data.user);
      onNavigate('/app');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))' }}>
      {/* Left Brand Showcase */}
      <section
        style={{
          padding: '44px 40px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          borderRight: '1px solid var(--cr-line)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <a href="/" onClick={e => { e.preventDefault(); onNavigate('/'); }} style={{ textDecoration: 'none' }}>
            <ClearLedgerLogo size={34} />
          </a>
          <ThemeToggle />
        </div>

        <div className="stack" style={{ alignItems: 'center', textAlign: 'center', paddingBlock: 32 }}>
          <LedgyMascot size={196} />
          <h2>Zero-Variance Financial Control</h2>
          <p style={{ maxWidth: '42ch' }}>
            Authenticate with salted PBKDF2-SHA256 sessions to manage your Multi-Currency General Ledger,
            IAS 21 FX Revaluation, and ISO 20022 Remittance streams.
          </p>
          <div className="actions" style={{ justifyContent: 'center' }}>
            <Badge tone="ok"><ShieldCheck size={13} /> HttpOnly Sessions</Badge>
            <Badge tone="info">Append-Only Audit Trail</Badge>
          </div>
        </div>

        <div>
          <Button variant="ghost" onClick={() => onNavigate('/')} iconLeft={<ArrowLeft size={15} />}>
            Back to overview
          </Button>
        </div>
      </section>

      {/* Right Auth Form */}
      <section style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 28 }}>
        <Card className="panel" style={{ width: '100%', maxWidth: 440 }}>
          <CardHeader className="panel-heading">
            <div>
              <h2>{mode === 'login' ? 'Sign In to Workspace' : 'Create Operator Account'}</h2>
              <p>{mode === 'login' ? 'Enter your work credentials to continue.' : 'Provision a new controller identity.'}</p>
            </div>
          </CardHeader>
          <CardBody className="stack" style={{ gap: 16 }}>
            <Tabs
              value={mode}
              onValueChange={val => { setMode(val); setError(''); }}
              items={[
                { value: 'login', label: 'Sign In' },
                { value: 'register', label: 'Create Account' },
              ]}
            />

            {error && <div className="error" role="alert">{error}</div>}

            <form onSubmit={handleSubmit} className="stack" style={{ gap: 14 }}>
              {mode === 'register' && (
                <>
                  <Field label="Full Name">
                    <Input
                      required
                      value={fullName}
                      onChange={e => setFullName(e.target.value)}
                      placeholder="Enter your full name"
                    />
                  </Field>
                  <Field label="Organization / Entity Name">
                    <Input
                      required
                      value={companyName}
                      onChange={e => setCompanyName(e.target.value)}
                      placeholder="Enter legal entity name"
                    />
                  </Field>
                </>
              )}

              <Field label="Work Email">
                <Input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="name@company.com"
                />
              </Field>

              <Field label="Password">
                <Input
                  type="password"
                  required
                  minLength={6}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="Enter password (min 6 chars)"
                />
              </Field>

              <Button type="submit" disabled={loading} iconRight={loading ? <Spinner /> : <ArrowRight size={15} />}>
                {mode === 'login' ? 'Sign In' : 'Create Account'}
              </Button>
            </form>

            <div style={{ textAlign: 'center', paddingTop: 8, borderTop: '1px solid var(--cr-line)' }}>
              <Button variant="ghost" onClick={() => onNavigate('/app')}>
                Continue directly to Financial OS
              </Button>
            </div>
          </CardBody>
        </Card>
      </section>
    </div>
  );
}
