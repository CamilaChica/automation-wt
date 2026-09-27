import React from 'react';
import { Badge } from './Badge';

interface FallbackDataBannerProps {
  message?: string;
}

export const FallbackDataBanner: React.FC<FallbackDataBannerProps> = ({ message }) => (
  <div
    role="status"
    aria-live="polite"
    className="flex min-w-0 max-w-full flex-wrap items-center gap-2 border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-400"
  >
    <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
    <span className="min-w-0 break-words">{message || 'Live data unavailable. Displaying local sample RFQ data.'}</span>
  </div>
);