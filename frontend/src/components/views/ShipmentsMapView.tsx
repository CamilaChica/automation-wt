import React from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';

export const ShipmentsMapView: React.FC = () => (
  <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
    <p className="text-sm text-slate-500 dark:text-slate-400">Map lines show predefined logistics lanes, not live package locations. Shipment records appear below the map; use Orders &amp; Tracking for carrier updates.</p>
    <WorldMapTelemetry title="Shipments map" subtitle="Logistics lanes and shipment records" />
  </div>
);
