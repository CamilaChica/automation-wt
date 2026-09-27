import React, { useState } from 'react';
import { getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { InternalCommand } from '../../types';
import { useExecuteInternalCommand, useFulfillmentStages } from '../../hooks/useApiResources';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { 
  QrCode, 
  Camera, 
  CheckSquare, 
  Printer, 
  ShieldCheck, 
  CheckCircle,
  FileCheck,
  Loader2
} from 'lucide-react';

export const FulfillmentHubView: React.FC = () => {
  const shipmentsQuery = useFulfillmentStages();
  const stages = shipmentsQuery.data || [];
  const shipments = stages;
  const loading = shipmentsQuery.isLoading;
  const error = shipmentsQuery.error?.message || null;
  const [notice, setNotice] = useState<string | null>(null);
  const [commandPending, setCommandPending] = useState<InternalCommand | null>(null);
  const [noticeType, setNoticeType] = useState<'success' | 'error'>('success');
  const commandMutation = useExecuteInternalCommand();
  const selectedShipment = shipments[0];
  const actionsBlocked = loading || Boolean(error) || !selectedShipment;

  const runCommand = async (command: InternalCommand, description: string) => {
    if (commandMutation.isPending || actionsBlocked || !selectedShipment) return;
    if (!window.confirm(`Confirm ${description}?`)) return;
    setCommandPending(command);
    setNotice(null);
    try {
      const result = await commandMutation.mutateAsync({ command, entityId: selectedShipment.shipment_id, details: `Shipment ${selectedShipment.shipment_id}: ${description}` });
      if (!result) return;
      setNoticeType('success');
      setNotice(result.message);
    } catch (requestError) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(requestError, `Unable to ${description}.`));
    } finally {
      setCommandPending(null);
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {notice && <div role={noticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-xl border px-4 py-3 text-xs font-semibold ${noticeType === 'error' ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200' : 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-500/40 dark:bg-blue-500/10 dark:text-blue-200'}`}>{notice}</div>}
      {/* Stage Progress Breadcrumb Tracker */}
      <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-2 font-mono text-[11px] sm:grid-cols-2 lg:grid-cols-5">
          <div className="flex min-w-0 items-center gap-2 text-emerald-600 dark:text-emerald-400 font-bold">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-500/20">1</span>
            <span className="min-w-0 leading-tight">ORDER INGEST</span>
          </div>

          <div className="flex min-w-0 items-center gap-2 text-emerald-600 dark:text-emerald-400 font-bold">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-500/20">2</span>
            <span className="min-w-0 leading-tight">INBOUND RECEIVING</span>
          </div>

          <div className="flex min-w-0 items-center gap-2 text-aero-blue font-bold dark:text-blue-300">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-aero-blue text-white shadow-sm">3</span>
            <span className="min-w-0 leading-tight">DIGITAL QA</span>
          </div>

          <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-300">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 font-bold dark:bg-slate-800">4</span>
            <span className="min-w-0 leading-tight">AERO-PACKAGING</span>
          </div>

          <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-300">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 font-bold dark:bg-slate-800">5</span>
            <span className="min-w-0 leading-tight">CARRIER TELEMETRY</span>
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="font-display font-bold text-xs uppercase tracking-wider">Live Shipments</h2>
          <span className="font-mono text-[10px] text-aero-blue">{loading ? '…' : error ? '—' : `${shipments.length} tracked`}</span>
        </div>
        {error && <div role="alert" className="mt-4 flex items-center justify-between rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700"><span>{error}</span><button type="button" onClick={() => void shipmentsQuery.refetch()} className="font-bold underline">Retry</button></div>}
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {loading ? <p className="text-sm text-slate-400" role="status" aria-live="polite" aria-busy="true">Loading shipments...</p> : shipments.length === 0 ? <p className="text-sm text-slate-400" role="status" aria-live="polite">No shipments are currently registered.</p> : shipments.slice(0, 6).map(shipment => (
            <div key={shipment.shipment_id} className="rounded-xl border border-slate-200 dark:border-slate-800 p-3 text-xs">
              <div className="font-mono font-bold text-aero-blue">{shipment.shipment_id}</div>
              <div className="mt-1 font-semibold">{shipment.stage}: {shipment.status}</div>
              <div className="mt-1 text-slate-500">{shipment.carrier || 'Carrier pending'} {shipment.tracking_number || ''}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Main Workspace Grid: 3 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (4 cols): DIGITAL QA WORKBENCH */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aero-blue" />
              <span>DIGITAL QA WORKBENCH</span>
            </h2>
            <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
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
                <span className="bg-emerald-700 text-white text-[8px] font-bold font-mono px-1.5 py-0.5 rounded shadow">
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
              AERO-PACKAGING PROTOCOL (ATA 300)
            </h2>
            <Badge variant="outline">SAMPLE / DEMO DATA</Badge>

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

            <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'print_tags'} onClick={() => void runCommand('print_tags', 'print ATA 300 Category I tags')} className="w-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-display font-bold py-2.5 px-3 rounded-xl text-xs border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-2 transition-colors disabled:cursor-not-allowed disabled:opacity-50">
              {commandPending === 'print_tags' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Printer className="w-4 h-4 text-aero-blue" />}
              <span>{commandPending === 'print_tags' ? 'QUEUEING TAGS...' : 'PRINT ATA 300 CAT I TAGS'}</span>
            </button>
          </div>

          {/* Carrier Telemetry Tracking */}
          <WorldMapTelemetry title="CARRIER ROUTE DEMO" subtitle="Example route: MIA (Miami International) to DFW (Dallas Fort Worth). Not live carrier telemetry." />
        </div>

        {/* Right Column (4 cols): COMPLIANCE PACKET COMPILER DRAWER */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <ShieldCheck className="w-4 h-4 text-emerald-500" />
              <span>6. COMPLIANCE PACKET COMPILER</span>
            </h2>
            <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
          </div>

          <div className="space-y-3 font-mono text-[11px]">
            <div className="flex items-center justify-between gap-3 bg-slate-50 p-3 text-slate-800 dark:bg-slate-900/80 dark:text-slate-200">
              <span className="min-w-0 font-semibold">Airworthiness verification</span>
              <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1">
              <div className="text-slate-500 dark:text-slate-400 uppercase text-[9px] font-bold">CALIBRATION & VERIFICATION LOG</div>
              <div className="text-emerald-700 dark:text-emerald-400 font-bold">DIGITAL TAMPER-EVIDENT STAMPS</div>
            </div>

            <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'generate_stamps'} onClick={() => void runCommand('generate_stamps', 'generate serialized tamper-evident stamps')} className="w-full bg-blue-50 hover:bg-blue-100 dark:bg-aero-blue/20 dark:hover:bg-aero-blue text-aero-blue dark:text-aero-blue dark:hover:text-white border border-blue-200 dark:border-aero-blue/40 font-bold py-2.5 px-3 rounded-xl text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50">
              {commandPending === 'generate_stamps' && <Loader2 className="mr-2 inline h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {commandPending === 'generate_stamps' ? 'GENERATING STAMPS...' : 'SERIALIZED TAMPER-EVIDENT STAMPS'}
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
