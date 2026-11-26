import React from 'react';

export function ClearLedgerLogo({ size = 34, showTagline = true }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        role="img"
        aria-label="ClearLedger Prime emblem"
      >
        <defs>
          <linearGradient id="clpLogoGrad" x1="4" y1="6" x2="58" y2="58" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--ut-accent, #126453)" />
            <stop offset="100%" stopColor="#0ea5e9" />
          </linearGradient>
        </defs>
        <rect x="4" y="4" width="56" height="56" rx="15" fill="var(--ut-surface, #0f172a)" stroke="url(#clpLogoGrad)" strokeWidth="3" />
        <path d="M18 21H37C39.8 21 42 23.2 42 26C42 28.8 39.8 31 37 31H18V21Z" fill="#0ea5e9" />
        <path d="M25 35H46V45H25C22.2 45 20 42.8 20 40C20 37.2 22.2 35 25 35Z" fill="var(--ut-accent, #126453)" />
        <circle cx="32" cy="33" r="3.2" fill="#ffffff" />
      </svg>
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.15 }}>
        <strong style={{ fontSize: '1.08rem', letterSpacing: '-0.03em', color: 'var(--ut-ink)' }}>
          ClearLedger Prime
        </strong>
        {showTagline && (
          <small style={{ fontSize: '0.68rem', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ut-ink-2)' }}>
            Multi-Currency Financial OS
          </small>
        )}
      </span>
    </span>
  );
}

export function LedgyMascot({ size = 180 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 240 240"
      fill="none"
      role="img"
      aria-label="Ledgy — ClearLedger Prime Auditor Owl Mascot"
    >
      <defs>
        <linearGradient id="ledgyAccent" x1="30" y1="20" x2="210" y2="210" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0ea5e9" />
          <stop offset="100%" stopColor="var(--ut-accent, #126453)" />
        </linearGradient>
        <radialGradient id="ledgyHalo" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="120" cy="120" r="108" fill="url(#ledgyHalo)" />
      <path d="M58 68L44 34L84 52Z" fill="#1e293b" stroke="url(#ledgyAccent)" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M182 68L196 34L156 52Z" fill="#1e293b" stroke="url(#ledgyAccent)" strokeWidth="2.5" strokeLinejoin="round" />
      <rect x="48" y="48" width="144" height="150" rx="68" fill="#132235" stroke="url(#ledgyAccent)" strokeWidth="3" />
      <path d="M84 146C84 134 98 128 120 128C142 128 156 134 156 146V168C156 184 138 194 120 194C102 194 84 184 84 168V146Z" fill="#0b1424" stroke="#334155" strokeWidth="2" />
      <rect x="98" y="148" width="26" height="6" rx="3" fill="#38bdf8" />
      <rect x="116" y="160" width="26" height="6" rx="3" fill="#10b981" />
      <rect x="104" y="172" width="32" height="4" rx="2" fill="#64748b" />
      <circle cx="92" cy="96" r="24" fill="#060b16" stroke="#38bdf8" strokeWidth="3.5" />
      <circle cx="148" cy="96" r="24" fill="#060b16" stroke="#10b981" strokeWidth="3.5" />
      <line x1="116" y1="96" x2="124" y2="96" stroke="#94a3b8" strokeWidth="3.5" strokeLinecap="round" />
      <circle cx="92" cy="96" r="10" fill="#38bdf8" />
      <circle cx="95" cy="92" r="3.5" fill="#f8fafc" />
      <circle cx="148" cy="96" r="10" fill="#10b981" />
      <circle cx="151" cy="92" r="3.5" fill="#f8fafc" />
      <path d="M112 110L128 110L120 124Z" fill="#f59e0b" />
      <path d="M48 116C30 124 26 154 46 172C52 162 54 146 54 130Z" fill="#16223a" stroke="#38bdf8" strokeWidth="2" />
      <path d="M192 116C210 124 214 154 194 172C188 162 186 146 186 130Z" fill="#16223a" stroke="#10b981" strokeWidth="2" />
      <circle cx="188" cy="64" r="16" fill="#064e3b" stroke="#10b981" strokeWidth="2.5" />
      <path d="M181 64L186 69L196 58" stroke="#34d399" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
