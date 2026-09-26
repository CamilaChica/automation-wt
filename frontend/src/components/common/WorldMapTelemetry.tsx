import React from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBounds, type LatLngExpression } from 'leaflet';
import { MapPin, CheckCircle, Clock } from 'lucide-react';

const mia: LatLngExpression = [25.7959, -80.287];
const dfw: LatLngExpression = [32.8998, -97.0403];
const fra: LatLngExpression = [50.0379, 8.5622];
const routeBounds = new LatLngBounds([25.7959, -97.0403], [50.0379, 8.5622]);

interface WorldMapTelemetryProps {
  title?: string;
  subtitle?: string;
  orderId?: string;
}

export const WorldMapTelemetry: React.FC<WorldMapTelemetryProps> = ({
  title = 'DEMO ROUTE TRACKING',
  subtitle = 'Example routes. Carrier locations are not live.',
  orderId = "WT-29471"
}) => {
  const [tilesUnavailable, setTilesUnavailable] = React.useState(false);

  return (
    <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 flex flex-col justify-between shadow-sm relative overflow-hidden transition-colors">
      <div className="mb-3 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="flex min-w-0 items-center space-x-2 font-display text-xs font-bold tracking-wider text-slate-900 dark:text-slate-100">
            <span className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
            <span className="min-w-0 break-words uppercase">{title}</span>
          </h3>
          <p className="max-w-full break-words text-[11px] font-mono text-slate-500 dark:text-slate-400">
            {subtitle}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="inline-flex items-center whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-mono text-[10px] font-bold text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">DEMO ROUTE</span>
          <span className="inline-flex items-center whitespace-nowrap rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 font-mono text-[10px] font-bold text-aero-blue dark:border-aero-blue/30 dark:bg-aero-blue/10">ORDER: {orderId}</span>
        </div>
      </div>

      <div className="relative h-48 w-full overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-800 dark:bg-slate-950/80">
        {tilesUnavailable ? (
          <div role="status" className="flex h-full flex-col justify-center gap-2 p-4 text-xs text-slate-700 dark:text-slate-200">
            <strong>Map tiles unavailable. Demo routes:</strong>
            <span>MIA, Miami to DFW, Dallas-Fort Worth</span>
            <span>MIA, Miami to FRA, Frankfurt</span>
          </div>
        ) : (
          <MapContainer
            bounds={routeBounds}
            boundsOptions={{ padding: [20, 20] }}
            className="h-full w-full"
            attributionControl={false}
            scrollWheelZoom={false}
            zoomControl={false}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              eventHandlers={{ tileerror: () => setTilesUnavailable(true) }}
            />
            <Polyline positions={[mia, dfw]} pathOptions={{ color: '#006BFF', weight: 3, dashArray: '6 5' }} />
            <Polyline positions={[mia, fra]} pathOptions={{ color: '#10B981', weight: 3 }} />
            {[
              { position: mia, code: 'MIA', name: 'Miami International Airport', color: '#006BFF' },
              { position: dfw, code: 'DFW', name: 'Dallas Fort Worth International Airport', color: '#10B981' },
              { position: fra, code: 'FRA', name: 'Frankfurt Airport', color: '#10B981' },
            ].map(airport => (
              <CircleMarker key={airport.code} center={airport.position} radius={6} pathOptions={{ color: '#fff', weight: 2, fillColor: airport.color, fillOpacity: 1 }}>
                <Tooltip>{airport.code}: {airport.name}</Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        )}
      </div>
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 text-[10px] text-slate-500 dark:text-slate-400">
        <p>Demo route geometry only; carrier locations are not live.</p>
        <a className="inline-flex min-h-11 items-center underline underline-offset-2" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          Map data: OpenStreetMap contributors
        </a>
      </div>

      {/* Courier Timeline Stepper Bar */}
      <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
        <div className="flex flex-col text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-bold">
            <CheckCircle className="w-3 h-3" />
            <span>SAMPLE PICKUP COMPLETED</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">WAREHOUSE DOCK</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">FEDEX AVIATION</span>
        </div>

        <div className="flex flex-col text-left p-2 rounded-xl bg-blue-50/60 dark:bg-slate-900/40 border border-blue-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-aero-blue font-mono text-[10px] font-bold">
            <Clock className="w-3 h-3 animate-spin" />
            <span>SAMPLE IN TRANSIT</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">AIR FREIGHT</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">FDX AIR CARGO</span>
        </div>

        <div className="flex flex-col text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-slate-600 dark:text-slate-400 font-mono text-[10px] font-semibold">
            <MapPin className="w-3 h-3 text-slate-400" />
            <span>SAMPLE CUSTOMS / DOCS</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">FAA 8130-3 ATTACHED</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">CLEARED AIRSIDE</span>
        </div>

        <div className="flex flex-col text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-amber-600 dark:text-amber-400 font-mono text-[10px] font-bold">
            <Clock className="w-3 h-3" />
            <span>SAMPLE ESTIMATED ARRIVAL</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">TOUCHDOWN</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">11:20 CDT (HOT-SHOT)</span>
        </div>
      </div>
    </div>
  );
};
