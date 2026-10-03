import React from 'react';
import { FulfillmentHubView } from './FulfillmentHubView';
import { ShipmentsMapView } from './ShipmentsMapView';

export const ShipmentsWorkspace: React.FC<{
  showMap: boolean;
  onSelectMap: (showMap: boolean) => void;
}> = ({ showMap, onSelectMap }) => (
  <div>
    <header className="mx-auto max-w-7xl space-y-3 px-4 pt-6 md:px-6">
      <h1 className="text-xl font-bold">Shipments &amp; Tracking</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">Manage shipment records and carrier tracking, or view the shipment map.</p>
      <nav aria-label="Shipment sections" className="flex flex-wrap gap-2">
        {[{ label: 'Orders & Tracking', map: false }, { label: 'Map', map: true }].map(section => (
          <button key={section.label} type="button" aria-pressed={showMap === section.map} onClick={() => onSelectMap(section.map)}
            className={`min-h-11 rounded-lg px-4 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-aero-blue ${showMap === section.map ? 'bg-aero-blue text-white' : 'bg-slate-200 text-slate-800 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700'}`}>
            {section.label}
          </button>
        ))}
      </nav>
    </header>
    {showMap ? <ShipmentsMapView /> : <FulfillmentHubView />}
  </div>
);
