import React from 'react';
import wingedTycoonsLogo from '../../assets/branding/WingedTycoons.png';

interface BrandMarkProps {
  className?: string;
  imageClassName?: string;
}

export const BrandMark: React.FC<BrandMarkProps> = ({ className = '', imageClassName = '' }) => (
  <span className={`inline-flex items-center ${className}`.trim()}>
    <img
      src={wingedTycoonsLogo}
      alt="Winged Tycoons"
      className={`h-10 w-auto object-contain ${imageClassName}`.trim()}
    />
  </span>
);

