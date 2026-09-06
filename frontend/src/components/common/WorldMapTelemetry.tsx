import React from 'react';
import { Plane, MapPin, CheckCircle, Clock } from 'lucide-react';

interface WorldMapTelemetryProps {
  title?: string;
  subtitle?: string;
  orderId?: string;
}

export const WorldMapTelemetry: React.FC<WorldMapTelemetryProps> = ({
  title = "ORDER TELEMETRY & TRACING",
  subtitle = "In-Transit orders in a next-mask-mode interactive live tracking.",
  orderId = "WT-29471"
}) => {
  return (
    <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 flex flex-col justify-between shadow-sm relative overflow-hidden transition-colors">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-aero-blue animate-ping" />
            <span>{title}</span>
          </h3>
          <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
            {subtitle}
          </p>
        </div>
        <div className="px-2.5 py-1 rounded-full bg-blue-50 dark:bg-aero-blue/10 border border-blue-200 dark:border-aero-blue/30 text-aero-blue font-mono text-[10px] font-bold">
          ORDER: {orderId}
        </div>
      </div>

      {/* SVG Map Canvas */}
      <div className="relative w-full h-48 bg-slate-50 dark:bg-slate-950/80 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden flex items-center justify-center">
        {/* World Map SVG outlines */}
        <svg viewBox="0 0 1000 450" className="w-full h-full opacity-60 dark:opacity-30 stroke-slate-300 dark:stroke-slate-600 fill-slate-200 dark:fill-slate-800/40">
          {/* Continents simplified SVG paths */}
          {/* North America */}
          <path d="M150,90 Q220,60 300,100 T350,220 T200,280 T100,200 Z" />
          {/* South America */}
          <path d="M300,290 Q340,320 320,400 T260,420 T280,330 Z" />
          {/* Europe & Asia */}
          <path d="M500,80 Q650,50 850,90 T900,240 T700,260 T550,180 Z" />
          {/* Africa */}
          <path d="M480,200 Q560,220 580,340 T500,380 T460,250 Z" />
          {/* Australia */}
          <path d="M800,320 Q880,300 890,380 T810,390 Z" />
        </svg>

        {/* Flight Trajectory Arcs */}
        <svg viewBox="0 0 1000 450" className="absolute inset-0 w-full h-full">
          <defs>
            <linearGradient id="flightArc" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#006BFF" stopOpacity="0.3" />
              <stop offset="50%" stopColor="#006BFF" stopOpacity="1" />
              <stop offset="100%" stopColor="#10B981" stopOpacity="0.9" />
            </linearGradient>
          </defs>
          {/* Flight 1 Arc MIA -> DFW */}
          <path
            d="M 240,210 Q 210,140 180,180"
            fill="none"
            stroke="url(#flightArc)"
            strokeWidth="2.5"
            strokeDasharray="6 4"
          />
          {/* Flight 2 Arc MIA -> FRA */}
          <path
            d="M 240,210 Q 380,80 520,130"
            fill="none"
            stroke="url(#flightArc)"
            strokeWidth="3"
          />
          {/* Flight 3 Arc FRA -> NFO Delivery */}
          <path
            d="M 520,130 Q 680,110 820,200"
            fill="none"
            stroke="url(#flightArc)"
            strokeWidth="2"
            strokeDasharray="4 4"
          />
        </svg>

        {/* Live Nodes / Airports */}
        {/* MIA */}
        <div className="absolute left-[24%] top-[46%] flex flex-col items-center group cursor-pointer">
          <div className="w-3.5 h-3.5 rounded-full bg-aero-blue animate-ping absolute" />
          <div className="w-3.5 h-3.5 rounded-full bg-aero-blue border-2 border-white flex items-center justify-center shadow-md" />
          <span className="font-mono text-[9px] font-bold text-slate-900 dark:text-white bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 rounded-md border border-slate-200 dark:border-slate-700 shadow-sm mt-1">
            MIA (ORIGIN)
          </span>
        </div>

        {/* Flying Plane 1 */}
        <div className="absolute left-[38%] top-[24%] -rotate-12 animate-pulse text-aero-blue">
          <Plane className="w-5 h-5 drop-shadow-md" />
        </div>

        {/* DFW */}
        <div className="absolute left-[18%] top-[40%] flex flex-col items-center">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 border border-white" />
          <span className="font-mono text-[9px] font-semibold text-slate-700 dark:text-slate-300 bg-white/90 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 px-1 py-0.5 rounded shadow-sm mt-1">
            DFW
          </span>
        </div>

        {/* FRA */}
        <div className="absolute left-[52%] top-[28%] flex flex-col items-center">
          <div className="w-3 h-3 rounded-full bg-emerald-500 border border-white" />
          <span className="font-mono text-[9px] font-bold text-emerald-700 dark:text-emerald-400 bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 rounded border border-emerald-200 dark:border-emerald-500/40 shadow-sm mt-1">
            FRA (SUPPLIER B)
          </span>
        </div>

        {/* Flying Plane 2 */}
        <div className="absolute left-[66%] top-[30%] rotate-45 text-emerald-500">
          <Plane className="w-4 h-4 drop-shadow-md" />
        </div>
      </div>

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
