import React from 'react';
import { MapPin } from 'lucide-react';

interface WorldMapTelemetryProps {
  title?: string;
  subtitle?: string;
  orderId?: string;
}

export const WorldMapTelemetry: React.FC<WorldMapTelemetryProps> = () => (
  <section role="status" aria-label="Live shipment telemetry" className="flex min-h-32 items-center gap-3 border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-card-dark">
    <MapPin className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
    <div>
      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Live shipment telemetry unavailable</h3>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">The API does not provide carrier locations or route milestones for this view.</p>
    </div>
  </section>
);
