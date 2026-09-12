import React, { useEffect, useMemo, useState } from 'react';
import { Plane, MapPin, CheckCircle, Clock, Satellite, LocateFixed } from 'lucide-react';
import {
  AIRPORTS,
  AircraftTrack,
  TelemetrySource,
  probeLiveFeed,
  simulateFleet,
} from '../../services/flightTracking';

interface WorldMapTelemetryProps {
  title?: string;
  subtitle?: string;
  orderId?: string;
}

// --- Flat 2D equirectangular projection -----------------------------------
// Plain lat/lon -> x/y mapping onto a flat map canvas. Landmasses are kept as
// a soft, implicit background shade (not a rendered "planet") so the focus
// stays on the live flight corridors, UTC time meridians, and the user's
// own location.

const MAP_W = 1000;
const MAP_H = 500;

function projectFlat(lat: number, lon: number) {
  const x = ((lon + 180) / 360) * MAP_W;
  const y = ((90 - lat) / 180) * MAP_H;
  return { x, y };
}

// Simplified but geographically-shaped continent outlines [lon, lat].
const CONTINENTS: [number, number][][] = [
  // North America
  [[-160, 68], [-140, 60], [-125, 49], [-124, 40], [-117, 32], [-106, 31], [-97, 26], [-90, 29], [-81, 25], [-80, 31], [-75, 35], [-70, 41], [-67, 45], [-60, 50], [-65, 60], [-80, 65], [-100, 70], [-130, 72], [-160, 68]],
  // South America
  [[-80, 10], [-77, 0], [-70, -18], [-70, -30], [-72, -45], [-68, -55], [-62, -52], [-58, -35], [-48, -25], [-35, -8], [-50, 3], [-60, 8], [-73, 8], [-80, 10]],
  // Europe
  [[-10, 36], [-9, 44], [0, 50], [5, 58], [15, 60], [25, 60], [30, 50], [20, 45], [28, 42], [23, 36], [10, 38], [-5, 37], [-10, 36]],
  // Africa
  [[-10, 35], [10, 37], [20, 32], [33, 31], [43, 12], [51, 12], [45, 0], [40, -15], [35, -25], [20, -35], [15, -30], [12, -18], [10, 4], [-5, 5], [-17, 15], [-10, 35]],
  // Asia
  [[28, 42], [40, 45], [60, 55], [80, 68], [110, 72], [140, 65], [150, 55], [140, 45], [130, 35], [120, 25], [105, 15], [95, 10], [80, 8], [70, 20], [60, 25], [50, 25], [40, 30], [28, 42]],
  // Australia
  [[113, -22], [122, -18], [135, -12], [142, -11], [148, -20], [145, -32], [138, -35], [130, -32], [118, -35], [113, -22]],
];

function buildContinentPath(points: [number, number][]) {
  const projected = points.map(([lon, lat]) => projectFlat(lat, lon));
  const d = projected
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');
  return `${d} Z`;
}

// UTC hour meridian lines, one every 15 degrees of longitude (24 total).
const UTC_MERIDIANS = Array.from({ length: 24 }, (_, i) => {
  const lon = -180 + i * 15;
  const utcHour = (12 + i) % 24; // lon -180 => UTC-12, lon 0 => UTC0, wrapping east
  return { lon, x: projectFlat(0, lon).x, utcHour };
});

export const WorldMapTelemetry: React.FC<WorldMapTelemetryProps> = ({
  title = 'ORDER TELEMETRY & TRACING',
  subtitle = 'In-Transit orders in a next-mask-mode interactive live tracking.',
  orderId = 'WT-29471',
}) => {
  const [fleet, setFleet] = useState<AircraftTrack[]>(() => simulateFleet());
  const [source, setSource] = useState<TelemetrySource>('SIMULATED');
  const [userPos, setUserPos] = useState<{ lat: number; lon: number } | null>(null);
  const [userGeoStatus, setUserGeoStatus] = useState<'locating' | 'located' | 'unavailable'>('locating');
  const [utcNow, setUtcNow] = useState(() => new Date());

  // Live-feel animation loop: advances aircraft along their routes every second.
  useEffect(() => {
    const tick = setInterval(() => {
      setFleet(simulateFleet());
      setUtcNow(new Date());
    }, 1000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    let cancelled = false;
    probeLiveFeed().then((result) => {
      if (!cancelled) setSource(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Adapt the map to the user's real connection location via browser geolocation,
  // falling back to a timezone-derived approximate longitude if permission is denied.
  useEffect(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setUserGeoStatus('unavailable');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserPos({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        setUserGeoStatus('located');
      },
      () => {
        const offsetHours = -new Date().getTimezoneOffset() / 60;
        setUserPos({ lat: 20, lon: offsetHours * 15 });
        setUserGeoStatus('unavailable');
      },
      { timeout: 5000, maximumAge: 300000 }
    );
  }, []);

  const continentPaths = useMemo(() => CONTINENTS.map(buildContinentPath), []);

  const airportPoints = useMemo(
    () =>
      Object.values(AIRPORTS).map((ap) => ({
        ...ap,
        ...projectFlat(ap.lat, ap.lon),
      })),
    []
  );

  const aircraftPoints = useMemo(
    () =>
      fleet.map((ac) => ({
        ac,
        ...projectFlat(ac.lat, ac.lon),
      })),
    [fleet]
  );

  const userPoint = useMemo(
    () => (userPos ? { ...userPos, ...projectFlat(userPos.lat, userPos.lon) } : null),
    [userPos]
  );

  const primary = fleet[0];
  const currentUtcHour = utcNow.getUTCHours();

  return (
    <div className="brand-card bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-4 sm:p-5 flex flex-col justify-between shadow-sm relative overflow-hidden transition-colors">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-aero-blue animate-ping" />
            <span>{title}</span>
          </h3>
          <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div
            className={`flex items-center gap-1 px-2.5 py-1 rounded-full border font-mono text-[10px] font-bold ${
              source === 'LIVE'
                ? 'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-300 dark:border-emerald-500/40 text-emerald-700 dark:text-emerald-400'
                : 'bg-amber-50 dark:bg-amber-500/10 border-amber-300 dark:border-amber-500/40 text-amber-700 dark:text-amber-400'
            }`}
          >
            <Satellite className="w-3 h-3" />
            <span>{source === 'LIVE' ? 'LIVE ADS-B FEED' : 'SIMULATED TELEMETRY'}</span>
          </div>
          <div className="px-2.5 py-1 rounded-full bg-blue-50 dark:bg-aero-blue/10 border border-blue-200 dark:border-aero-blue/30 text-aero-blue font-mono text-[10px] font-bold">
            ORDER: {orderId}
          </div>
        </div>
      </div>

      {/* Flat 2D World Map Canvas */}
      <div className="relative w-full h-64 sm:h-80 md:h-96 bg-slate-50 dark:bg-slate-950/80 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
          {/* Soft, implicit landmasses — a faint shade, not a rendered planet */}
          <g fill="#8fa6b8" className="fill-slate-400 dark:fill-slate-600" opacity="0.28">
            {continentPaths.map((d, i) => (
              <path key={i} d={d} />
            ))}
          </g>

          {/* UTC hour meridian lines, one every 15 degrees longitude */}
          <g>
            {UTC_MERIDIANS.map((m) => {
              const isCurrentHour = m.utcHour === currentUtcHour;
              return (
                <g key={m.utcHour}>
                  <line
                    x1={m.x}
                    y1={0}
                    x2={m.x}
                    y2={MAP_H}
                    stroke={isCurrentHour ? '#c9a227' : '#94a3b8'}
                    strokeOpacity={isCurrentHour ? 0.75 : 0.18}
                    strokeWidth={isCurrentHour ? 1.4 : 0.6}
                    strokeDasharray={isCurrentHour ? undefined : '2 4'}
                  />
                  <text
                    x={m.x + 2}
                    y={11}
                    fontSize="8"
                    fontFamily="monospace"
                    fill={isCurrentHour ? '#c9a227' : '#94a3b8'}
                    opacity={isCurrentHour ? 1 : 0.55}
                  >
                    UTC{m.utcHour - 12 >= 0 ? `+${m.utcHour - 12}` : m.utcHour - 12}
                  </text>
                </g>
              );
            })}
          </g>

          {/* Equator + reference parallels */}
          <g stroke="#94a3b8" strokeOpacity="0.15" strokeWidth="0.6" strokeDasharray="2 4">
            <line x1="0" y1={MAP_H / 2} x2={MAP_W} y2={MAP_H / 2} />
            <line x1="0" y1={MAP_H / 4} x2={MAP_W} y2={MAP_H / 4} />
            <line x1="0" y1={(MAP_H / 4) * 3} x2={MAP_W} y2={(MAP_H / 4) * 3} />
          </g>

          {/* Flight corridor arcs */}
          {aircraftPoints.map(({ ac, x, y }) => {
            const origin = airportPoints.find((a) => a.iata === ac.originIata);
            const dest = airportPoints.find((a) => a.iata === ac.destIata);
            if (!origin || !dest) return null;
            const midX = (origin.x + dest.x) / 2;
            const midY = (origin.y + dest.y) / 2 - 24;
            return (
              <path
                key={`arc-${ac.id}`}
                d={`M ${origin.x.toFixed(1)} ${origin.y.toFixed(1)} Q ${midX.toFixed(1)} ${midY.toFixed(1)} ${dest.x.toFixed(1)} ${dest.y.toFixed(1)}`}
                fill="none"
                stroke="#c9a227"
                strokeOpacity="0.55"
                strokeWidth="1.5"
                strokeDasharray="5 4"
              />
            );
          })}

          {/* Airport nodes */}
          {airportPoints.map((ap) => (
            <g key={ap.iata}>
              <circle cx={ap.x} cy={ap.y} r="4" fill="#10b981" stroke="#fff" strokeWidth="1.2" />
              <circle cx={ap.x} cy={ap.y} r="7" fill="none" stroke="#10b981" strokeOpacity="0.5" strokeWidth="1" />
            </g>
          ))}

          {/* User connection location */}
          {userPoint && (
            <g>
              <circle cx={userPoint.x} cy={userPoint.y} r="8" fill="#2563eb" opacity="0.25">
                <animate attributeName="r" values="8;16;8" dur="2.4s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.35;0;0.35" dur="2.4s" repeatCount="indefinite" />
              </circle>
              <circle cx={userPoint.x} cy={userPoint.y} r="4.5" fill="#2563eb" stroke="#fff" strokeWidth="1.4" />
            </g>
          )}

          {/* Live aircraft markers, oriented by true heading */}
          {aircraftPoints.map(({ ac, x, y }) => (
            <g key={ac.id} transform={`translate(${x} ${y}) rotate(${ac.headingDeg})`}>
              <path d="M0,-6 L4,5 L0,2 L-4,5 Z" fill="#f4b400" stroke="#fff" strokeWidth="0.6" />
            </g>
          ))}
        </svg>

        {/* Airport / flight / user labels overlaid as HTML for crisp text at any zoom */}
        {airportPoints.map((ap) => (
          <span
            key={ap.iata}
            className="absolute font-mono text-[9px] font-bold text-slate-900 dark:text-white bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 rounded-md border border-slate-200 dark:border-slate-700 shadow-sm pointer-events-none"
            style={{
              left: `${(ap.x / MAP_W) * 100}%`,
              top: `${(ap.y / MAP_H) * 100 + 3}%`,
              transform: 'translate(-50%, 0)',
            }}
          >
            {ap.iata}
          </span>
        ))}
        {aircraftPoints.map(({ ac, x, y }) => (
          <span
            key={`lbl-${ac.id}`}
            className="absolute font-mono text-[9px] font-bold text-amber-600 dark:text-amber-300 bg-white/90 dark:bg-slate-950/80 px-1.5 py-0.5 rounded-md border border-amber-400/40 dark:border-amber-500/30 shadow-sm pointer-events-none flex items-center gap-1"
            style={{
              left: `${(x / MAP_W) * 100}%`,
              top: `${(y / MAP_H) * 100 - 3}%`,
              transform: 'translate(-50%, -100%)',
            }}
          >
            <Plane className="w-2.5 h-2.5" />
            {ac.callsign} · FL{Math.round(ac.altitudeFt / 100)}
          </span>
        ))}
        {userPoint && (
          <span
            className="absolute font-mono text-[9px] font-bold text-blue-700 dark:text-blue-300 bg-white/90 dark:bg-slate-950/80 px-1.5 py-0.5 rounded-md border border-blue-400/40 dark:border-blue-500/30 shadow-sm pointer-events-none flex items-center gap-1"
            style={{
              left: `${(userPoint.x / MAP_W) * 100}%`,
              top: `${(userPoint.y / MAP_H) * 100 + 3}%`,
              transform: 'translate(-50%, 0)',
            }}
          >
            <LocateFixed className="w-2.5 h-2.5" />
            YOU {userGeoStatus === 'unavailable' ? '(EST.)' : ''}
          </span>
        )}
      </div>

      {/* Live Carrier Readout */}
      {primary && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] font-mono text-slate-500 dark:text-slate-400 px-1">
          <span className="font-bold text-slate-700 dark:text-slate-300">{primary.callsign}</span>
          <span>{primary.carrier}</span>
          <span>{AIRPORTS[primary.originIata].iata} → {AIRPORTS[primary.destIata].iata}</span>
          <span>ALT {primary.altitudeFt.toLocaleString()} FT</span>
          <span>GS {primary.groundSpeedKts} KTS</span>
          <span>HDG {Math.round(primary.headingDeg)}°</span>
          <span className="ml-auto">UTC {utcNow.toISOString().slice(11, 19)}</span>
        </div>
      )}

      {/* Courier Timeline Stepper Bar */}
      <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
        <div className="flex flex-col text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-bold">
            <CheckCircle className="w-3 h-3" />
            <span>PICKUP COMPLETED</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">WAREHOUSE DOCK</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">FEDEX AVIATION</span>
        </div>

        <div className="flex flex-col text-left p-2 rounded-xl bg-blue-50/60 dark:bg-slate-900/40 border border-blue-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-aero-blue font-mono text-[10px] font-bold">
            <Clock className="w-3 h-3 animate-spin" />
            <span>IN TRANSIT</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">AIR FREIGHT</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">FDX AIR CARGO</span>
        </div>

        <div className="flex flex-col text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-slate-600 dark:text-slate-400 font-mono text-[10px] font-semibold">
            <MapPin className="w-3 h-3 text-slate-400" />
            <span>CUSTOMS / DOCS</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">FAA 8130-3 ATTACHED</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">CLEARED AIRSIDE</span>
        </div>

        <div className="flex flex-col text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
          <div className="flex items-center space-x-1 text-amber-600 dark:text-amber-400 font-mono text-[10px] font-bold">
            <Clock className="w-3 h-3" />
            <span>ESTIMATED ARRIVAL</span>
          </div>
          <span className="text-[10px] text-slate-500 truncate">TOUCHDOWN</span>
          <span className="text-[11px] font-mono text-slate-900 dark:text-slate-200 font-bold truncate">11:20 CDT (HOT-SHOT)</span>
        </div>
      </div>
    </div>
  );
};
