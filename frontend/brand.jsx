import React from 'react';
import { Layers3 } from 'lucide-react';

export function ClearLedgerLogo({ size = 32 }) {
  return <span className="brand-lockup">
    <span className="brand-mark" style={{ width: size, height: size }}><Layers3 size={size * .59} aria-hidden="true" /></span>
    <strong>ClearLedger</strong>
  </span>;
}
