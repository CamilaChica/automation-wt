import React from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';

export const ShipmentsMapView: React.FC = () => (
  <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
    <WorldMapTelemetry title="Shipments map" subtitle="Live shipments from the Miami hub" />
  </div>
);
