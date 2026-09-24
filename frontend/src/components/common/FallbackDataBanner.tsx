import React from 'react';

interface FallbackDataBannerProps {
  message?: string;
}

export const FallbackDataBanner: React.FC<FallbackDataBannerProps> = ({ message }) => (
  <div
    role="status"
    aria-live="polite"
    className="flex min-w-0 max-w-full items-center gap-2 border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-400"
  >
    <span className="min-w-0 break-words">{message || '⚠️ Live Data Unavailable — Displaying Cached Sample Data'}</span>
  </div>
);