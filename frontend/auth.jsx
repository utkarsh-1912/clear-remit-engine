import React, { useState } from 'react';
import { Button, Field, Input, Spinner, ThemeToggle } from '@utkristi/ui';
import { BookOpen } from 'lucide-react';
import { ClearRemitLogo, ClearRemitMascot } from './brand';
import { apiFetch } from './core-os/utils';

export default function AuthPage({ registrationAvailable, user }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(event) {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    setError('');
    setLoading(true);
    try {
      await apiFetch(registrationAvailable ? '/api/auth/register' : '/api/auth/login', {
        method: 'POST', body: JSON.stringify(payload),
      });
      location.replace(`/app${location.hash}`);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  return <div className="auth-layout">
    <section className="auth-context">
      <a className="brand" href="/"><ClearRemitLogo /></a>
      <div className="stack">
        <h2>Accounting and treasury in one workspace.</h2>
        <p>Post to the general ledger, reconcile incoming payments, and review your financial statements.</p>
        <ClearRemitMascot />
      </div>
      <a href="/docs" className="auth-docs"><BookOpen size={17} /> Read the documentation</a>
    </section>
    <main className="auth-content">
      <div className="auth-toolbar"><a href="/">Back to home</a><ThemeToggle /></div>
      <div className="auth-form stack">
        <header>
          <h1>{user ? 'You’re signed in' : registrationAvailable ? 'Set up your workspace' : 'Sign in'}</h1>
          <p>{user ? user.email : registrationAvailable ? 'Create the first account for this ledger.' : 'Enter your workspace credentials.'}</p>
        </header>
        {user ? <div><Button href="/app">Open workspace</Button></div> : (
          <form onSubmit={handleSubmit} className="stack">
            {error && <div className="error" role="alert">{error}</div>}
            {registrationAvailable && <>
              <Field label="Full name"><Input name="full_name" autoComplete="name" required /></Field>
              <Field label="Organization"><Input name="company_name" autoComplete="organization" required /></Field>
            </>}
            <Field label="Work email"><Input name="email" type="email" autoComplete="username" required /></Field>
            <Field label="Password">
              <Input name="password" type="password" autoComplete={registrationAvailable ? 'new-password' : 'current-password'} required minLength={6} />
            </Field>
            <Button type="submit" disabled={loading} iconLeft={loading ? <Spinner /> : undefined}>
              {registrationAvailable ? 'Create workspace account' : 'Sign in'}
            </Button>
          </form>
        )}
      </div>
    </main>
  </div>;
}
