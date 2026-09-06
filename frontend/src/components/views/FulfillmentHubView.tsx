import React from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { 
  QrCode, 
  Camera, 
  CheckSquare, 
  Printer, 
  ShieldCheck, 
  CheckCircle,
  FileCheck
} from 'lucide-react';

export const FulfillmentHubView: React.FC = () => {
  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {/* Stage Progress Breadcrumb Tracker */}
      <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between font-mono text-[11px] gap-2">
          <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400 font-bold">
            <span className="w-6 h-6 rounded-full bg-emerald-50 dark:bg-emerald-500/20 flex items-center justify-center border border-emerald-300 dark:border-emerald-500/40">1</span>
            <span>1. ORDER INGEST</span>
          </div>
          <div className="hidden sm:block h-0.5 w-12 bg-emerald-300 dark:bg-emerald-500/40" />

          <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400 font-bold">
            <span className="w-6 h-6 rounded-full bg-emerald-50 dark:bg-emerald-500/20 flex items-center justify-center border border-emerald-300 dark:border-emerald-500/40">2</span>
            <span>2. INBOUND RECEIVING</span>
          </div>
          <div className="hidden sm:block h-0.5 w-12 bg-emerald-300 dark:bg-emerald-500/40" />

          <div className="flex items-center space-x-2 text-aero-blue font-bold">
            <span className="w-6 h-6 rounded-full bg-aero-blue text-white flex items-center justify-center shadow-sm">3</span>
            <span className="bg-blue-50 dark:bg-aero-blue/20 px-2 py-0.5 rounded border border-blue-200 dark:border-aero-blue/40">3. DIGITAL QA</span>
          </div>
          <div className="hidden sm:block h-0.5 w-12 bg-slate-200 dark:bg-slate-800" />

          <div className="flex items-center space-x-2 text-slate-400 dark:text-slate-500">
            <span className="w-6 h-6 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-bold">4</span>
            <span>4. AERO-PACKAGING</span>
          </div>
          <div className="hidden sm:block h-0.5 w-12 bg-slate-200 dark:bg-slate-800" />

          <div className="flex items-center space-x-2 text-slate-400 dark:text-slate-500">
            <span className="w-6 h-6 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-bold">5</span>
            <span>5. CARRIER TELEMETRY</span>
          </div>
        </div>
      </div>

      {/* Main Workspace Grid: 3 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (4 cols): DIGITAL QA WORKBENCH */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aero-blue" />
              <span>3. DIGITAL QA WORKBENCH</span>
            </h2>
          </div>

          <div className="font-mono text-[11px] space-y-0.5">
            <div className="text-slate-500 dark:text-slate-400">Part Number: <span className="text-slate-900 dark:text-slate-100 font-bold">32-11-45-01</span></div>
            <div className="font-semibold text-slate-700 dark:text-slate-300">Main Landing Gear Actuator</div>
          </div>

          {/* Barcode/QR Scan Status */}
          <div className="bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/40 p-3 rounded-xl flex items-center justify-between font-mono text-[11px]">
            <div className="flex items-center space-x-2 text-emerald-700 dark:text-emerald-400 font-bold">
              <CheckCircle className="w-4 h-4" />
              <span>Serial Match: SN: MLG-9840</span>
            </div>
            <QrCode className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
          </div>

          {/* Computer Vision Integrity Check Camera Viewer */}
          <div className="relative bg-slate-100 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-xl h-44 flex items-center justify-center overflow-hidden">
            {/* Actuator mock photo outline */}
            <div className="w-4/5 h-4/5 border-2 border-dashed border-aero-blue/60 rounded-lg flex items-center justify-center bg-white/70 dark:bg-slate-900/60 relative">
              <span className="font-mono text-[10px] text-aero-blue font-bold text-center px-2">ACTUATOR MLG-9840 IN INSPECTION</span>
              <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-[9px] font-mono text-slate-700 dark:text-slate-300 flex items-center space-x-1 shadow-sm">
                <Camera className="w-3 h-3 text-aero-blue" />
                <span>Photo</span>
              </div>

              {/* Bounding box target overlay */}
              <div className="absolute inset-3 border-2 border-emerald-500 rounded pointer-events-none flex items-start justify-end p-1">
                <span className="bg-emerald-600 text-white text-[8px] font-bold font-mono px-1.5 py-0.5 rounded shadow">
                  CV MATCH 99.8%
                </span>
              </div>
            </div>
          </div>

          {/* Non-Destructive Testing Log */}
          <div className="bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 font-mono text-[11px] flex items-center justify-between text-slate-800 dark:text-slate-200">
            <div className="flex items-center space-x-2">
              <CheckSquare className="w-4 h-4 text-aero-blue" />
              <span className="font-bold">NDT: MPI/FPI Complete</span>
            </div>
            <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/20 px-2 py-0.5 rounded border border-emerald-200 dark:border-emerald-500/30">PASSED</span>
          </div>
        </div>

        {/* Center Column (4 cols): AERO-PACKAGING PROTOCOL & CARRIER TELEMETRY */}
        <div className="lg:col-span-4 space-y-6">
          {/* Aero-Packaging Protocol */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase border-b border-slate-100 dark:border-slate-800 pb-3">
              4. AERO-PACKAGING PROTOCOL (ATA 300)
            </h2>

            <div className="font-mono text-[11px] space-y-0.5">
              <div className="text-slate-500 dark:text-slate-400">Part Number: <span className="text-slate-900 dark:text-slate-100 font-bold">32-11-45-01</span></div>
              <div className="font-semibold text-slate-700 dark:text-slate-300">Main Landing Gear Actuator</div>
            </div>

            <div className="space-y-2 font-mono text-[11px]">
              <div className="bg-slate-50 dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center space-x-2 text-emerald-700 dark:text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>Nitro Pre-Charge: Tag #NP-204</span>
              </div>
              <div className="bg-slate-50 dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center space-x-2 text-emerald-700 dark:text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>ShockWatch Sensor: Attached #S-991</span>
              </div>
            </div>

            <button className="w-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-display font-bold py-2.5 px-3 rounded-xl text-xs border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-2 transition-colors">
              <Printer className="w-4 h-4 text-aero-blue" />
              <span>PRINT ATA 300 CAT I TAGS</span>
            </button>
          </div>

          {/* Carrier Telemetry Tracking */}
          <WorldMapTelemetry title="5. CARRIER TELEMETRY & FLIGHT TRACKING" subtitle="Links: Carrier vehicle GPS to AA Flight 1482 (MIA ✈️ DFW)" />
        </div>

        {/* Right Column (4 cols): COMPLIANCE PACKET COMPILER DRAWER */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <ShieldCheck className="w-4 h-4 text-emerald-500" />
              <span>6. COMPLIANCE PACKET COMPILER</span>
            </h2>
          </div>

          <div className="space-y-3 font-mono text-[11px]">
            <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-200">
              <span className="font-semibold">Verified Airworthiness</span>
              <div className="w-9 h-5 bg-emerald-500 rounded-full flex items-center justify-end p-0.5 cursor-pointer">
                <div className="w-4 h-4 rounded-full bg-white shadow" />
              </div>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1">
              <div className="text-slate-500 dark:text-slate-400 uppercase text-[9px] font-bold">CALIBRATION & VERIFICATION LOG</div>
              <div className="text-emerald-700 dark:text-emerald-400 font-bold">DIGITAL TAMPER-EVIDENT STAMPS</div>
            </div>

            <button className="w-full bg-blue-50 hover:bg-blue-100 dark:bg-aero-blue/20 dark:hover:bg-aero-blue text-aero-blue dark:text-aero-blue dark:hover:text-white border border-blue-200 dark:border-aero-blue/40 font-bold py-2.5 px-3 rounded-xl text-xs transition-colors">
              SERIALIZED TAMPER-EVIDENT STAMPS
            </button>

            <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
              <div className="text-slate-500 dark:text-slate-400 text-[10px] uppercase font-bold">Verified Airworthiness Documents</div>
              
              <div className="bg-slate-50 dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200">
                <div className="flex items-center space-x-2">
                  <FileCheck className="w-3.5 h-3.5 text-emerald-500" />
                  <span>FAA 8130-3</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 text-[9px] font-bold border border-emerald-200 dark:border-emerald-500/30">VERIFIED</span>
              </div>

              <div className="bg-slate-50 dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200">
                <div className="flex items-center space-x-2">
                  <FileCheck className="w-3.5 h-3.5 text-emerald-500" />
                  <span>EASA Form 1</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 text-[9px] font-bold border border-emerald-200 dark:border-emerald-500/30">VERIFIED</span>
              </div>

              <div className="bg-slate-50 dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200">
                <div className="flex items-center space-x-2">
                  <FileCheck className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Trace Packet</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 text-[9px] font-bold border border-emerald-200 dark:border-emerald-500/30">VERIFIED</span>
              </div>
            </div>

            <div className="pt-2 text-[10px] text-slate-500 text-center font-bold">
              DIGITAL-PHYSICAL DOCUMENT MATCH 100%
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
