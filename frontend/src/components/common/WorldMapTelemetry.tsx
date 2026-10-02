import React from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBounds, type LatLngExpression } from 'leaflet';
import { Package, Truck } from 'lucide-react';
import { apiService } from '../../services/api';
import type { Shipment } from '../../types';

interface WorldMapTelemetryProps {
  title?: string;
  subtitle?: string;
  orderId?: string;
}

const hub = { code: 'MIA', name: 'Miami hub (Winged Tycoons)', position: [25.7959, -80.287] as LatLngExpression };
const lanes = [
  { code: 'DFW', name: 'Dallas-Fort Worth', position: [32.8998, -97.0403] as LatLngExpression },
  { code: 'LAX', name: 'Los Angeles', position: [33.9416, -118.4085] as LatLngExpression },
  { code: 'JFK', name: 'New York', position: [40.6413, -73.7781] as LatLngExpression },
  { code: 'BOG', name: 'Bogotá', position: [4.7016, -74.1469] as LatLngExpression },
  { code: 'GRU', name: 'São Paulo', position: [-23.4356, -46.4731] as LatLngExpression },
  { code: 'MEX', name: 'Mexico City', position: [19.4361, -99.0719] as LatLngExpression },
  { code: 'FRA', name: 'Frankfurt', position: [50.0379, 8.5622] as LatLngExpression },
  { code: 'DXB', name: 'Dubai', position: [25.2532, 55.3657] as LatLngExpression },
];
const bounds = new LatLngBounds([-30, -125], [55, 60]);

const statusColor = (status: string) => {
  const s = status.toLowerCase();
  if (s.includes('deliver')) return 'bg-emerald-500';
  if (s.includes('transit') || s.includes('ship')) return 'bg-sky-500';
  if (s.includes('exception') || s.includes('hold')) return 'bg-red-500';
  return 'bg-amber-500';
};

export const WorldMapTelemetry: React.FC<WorldMapTelemetryProps> = ({
  title = 'Shipment map',
  subtitle = 'Winged Tycoons logistics lanes and live shipment status',
}) => {
  const [tilesUnavailable, setTilesUnavailable] = React.useState(false);
  const [shipments, setShipments] = React.useState<Shipment[] | null>(null);

  React.useEffect(() => {
    let active = true;
    if (apiService.getRole() !== 'internal') {
      setShipments([]);
      return () => { active = false; };
    }
    apiService.getShipments()
      .then(rows => { if (active) setShipments(rows); })
      .catch(() => { if (active) setShipments([]); });
    return () => { active = false; };
  }, []);

  const inTransit = (shipments || []).filter(s => !s.status.toLowerCase().includes('deliver')).length;

  return (
    <section aria-label={title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-card-dark">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-slate-100">
            <span className="h-2 w-2 rounded-full bg-sky-500" />{title}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
        </div>
        <div className="flex gap-2 text-[11px] font-semibold">
          <span className="rounded-full bg-sky-50 px-2.5 py-1 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">{shipments ? shipments.length : '…'} shipments</span>
          <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">{inTransit} active</span>
        </div>
      </div>

      <div className="relative h-64 w-full overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-800 dark:bg-slate-950/80">
        {tilesUnavailable ? (
          <div role="status" className="flex h-full flex-col justify-center gap-1 p-4 text-xs text-slate-700 dark:text-slate-200">
            <strong>Map tiles could not load. Active lanes from Miami:</strong>
            <span>{lanes.map(l => l.code).join(' · ')}</span>
          </div>
        ) : (
          <MapContainer bounds={bounds} className="h-full w-full" attributionControl={false} scrollWheelZoom={false} worldCopyJump>
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              eventHandlers={{ tileerror: () => setTilesUnavailable(true) }}
            />
            {lanes.map(lane => (
              <Polyline key={lane.code} positions={[hub.position, lane.position]} pathOptions={{ color: '#38bdf8', weight: 2, opacity: 0.7, dashArray: '6 6' }} />
            ))}
            {lanes.map(lane => (
              <CircleMarker key={`m-${lane.code}`} center={lane.position} radius={5} pathOptions={{ color: '#fff', weight: 1, fillColor: '#38bdf8', fillOpacity: 1 }}>
                <Tooltip>{lane.code}: {lane.name}</Tooltip>
              </CircleMarker>
            ))}
            <CircleMarker center={hub.position} radius={8} pathOptions={{ color: '#fff', weight: 2, fillColor: '#f5b301', fillOpacity: 1 }}>
              <Tooltip permanent direction="top">{hub.code}</Tooltip>
            </CircleMarker>
          </MapContainer>
        )}
      </div>
      <p className="mt-1 text-right text-[10px] text-slate-400">Map data © OpenStreetMap contributors, © CARTO</p>

      <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
        {shipments === null ? (
          <p className="text-xs text-slate-500">Loading shipments…</p>
        ) : shipments.length === 0 ? (
          <p className="flex items-center gap-2 text-xs text-slate-500"><Package className="h-4 w-4" />No shipments yet. They appear here as soon as a purchase order ships.</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {shipments.slice(0, 6).map(s => (
              <li key={s.id} className="flex items-center gap-3 rounded-xl bg-slate-50 p-2 text-xs dark:bg-slate-900/50">
                <Truck className="h-4 w-4 shrink-0 text-slate-400" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold text-slate-800 dark:text-slate-200">{s.carrier || 'Carrier'} {s.tracking_number || s.id}</div>
                  <div className="truncate text-slate-500">{(s.part_numbers || []).join(', ') || s.rfq_id || ''}</div>
                </div>
                <span className="flex items-center gap-1 whitespace-nowrap text-slate-600 dark:text-slate-300"><span className={`h-2 w-2 rounded-full ${statusColor(s.status)}`} />{s.status}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};
