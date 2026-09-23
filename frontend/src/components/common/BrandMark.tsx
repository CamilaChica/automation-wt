import React, { useState } from 'react';
import bundledMark from '../../assets/winged-tycoons-mark.svg';

interface BrandMarkProps {
  compact?: boolean;
}

export const BrandMark: React.FC<BrandMarkProps> = ({ compact = false }) => {
  const sources = ['/branding/WingedTycoons.png', '/branding/WingedTycoons.svg', bundledMark];
  const [sourceIndex, setSourceIndex] = useState(0);

  if (sourceIndex >= sources.length) {
    return (
      <span
        aria-label="Winged Tycoons"
        className={`${compact ? 'h-7 w-7 text-[9px]' : 'h-11 w-11 text-xs'} flex items-center justify-center rounded-xl bg-gradient-to-tr from-aero-blue to-cyan-400 font-display font-bold text-white`}
      >
        WT
      </span>
    );
  }

  const source = sources[sourceIndex];
  return (
    <img
      key={source}
      src={source}
      alt="Winged Tycoons Logo"
      width={compact ? 28 : 44}
      height={compact ? 28 : 44}
      className={compact ? 'h-7 w-7' : 'h-11 w-11'}
      onError={() => setSourceIndex(index => index + 1)}
    />
  );
};
