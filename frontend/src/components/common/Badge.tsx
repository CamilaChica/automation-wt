import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'outline';
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({ children, variant = 'outline', className = '' }) => (
  <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 font-mono text-[9px] font-bold uppercase leading-tight ${
    variant === 'outline'
      ? 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200'
      : ''
  } ${className}`}>
    {children}
  </span>
);