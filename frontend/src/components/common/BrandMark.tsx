import React from 'react';

interface BrandMarkProps {
  compact?: boolean;
}

export const BrandMark: React.FC<BrandMarkProps> = ({ compact = false }) => (
  <img
    src="/winged-tycoons-mark.svg"
    alt="Winged Tycoons"
    className={compact ? 'h-7 w-7' : 'h-11 w-11'}
  />
);
