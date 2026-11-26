import React from 'react';
import mark from './assets/logo.svg';
import mascot from './assets/mascot.svg';

export function ClearRemitLogo({ size = 32 }) {
  return <span className="brand-lockup">
    <img className="brand-mark" src={mark} alt="" width={size} height={size} />
    <strong>ClearRemit</strong>
  </span>;
}

export function ClearRemitMascot() {
  return <img className="brand-mascot" src={mascot} alt="ClearRemit owl mascot" width="360" height="290" />;
}
