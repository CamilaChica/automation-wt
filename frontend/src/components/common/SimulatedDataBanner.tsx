import React from 'react';

interface SimulatedDataBannerProps {
  label?: string;
}

export const SimulatedDataBanner: React.FC<SimulatedDataBannerProps> = ({ label = 'DEMO DATA' }) => (
  <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
    {label}
  </div>
);