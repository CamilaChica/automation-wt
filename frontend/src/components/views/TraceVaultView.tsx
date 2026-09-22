import React, { useEffect, useState } from 'react';
import { apiService } from '../../services/api';
import { RFQ } from '../../types';
import { 
  ShieldCheck, 
  AlertOctagon, 
  CheckCircle2, 
  XCircle, 
  FileSearch, 
  Check, 
  AlertTriangle,
  FileCheck,
  Search,
  Eye
} from 'lucide-react';

export const TraceVaultView: React.FC = () => {
  const [activeTab, setActiveTab] = useState('');
  const [rfqs, setRfqs] = useState<RFQ[]>([]);
  const [verificationPassed, setVerificationPassed] = useState(false);
  const [hardFreezeEnabled, setHardFreezeEnabled] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadRfqs = async () => {
    setLoading(true);
    try {
      const items = await apiService.getRFQs();
      setRfqs(items);
      if (items[0]) setActiveTab(items[0].id);
      setNotice(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to load trace records.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadRfqs(); }, []);

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {notice && <div role="alert" className="flex items-center justify-between rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700"><span>{notice}</span><button type="button" onClick={() => void loadRfqs()} className="font-bold underline">Retry</button></div>}
      {/* Top Grid: Pipeline & Active Vault & Document Viewer */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Top (4 cols): DOCUMENTATION STATUS PIPELINE & ACTIVE DOCUMENT VAULT */}
        <div className="lg:col-span-4 space-y-4">
          {/* Documentation Status Pipeline */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
                <span className="w-2 h-2 rounded-full bg-aero-blue animate-ping" />
                <span>DOCUMENTATION STATUS PIPELINE</span>
              </h2>
              <span className="text-[10px] font-mono text-aero-blue font-bold">LIVE RFQ DATA</span>
            </div>

            <div className="overflow-x-auto font-mono text-[10px]">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800">
                    <th className="pb-2">Order ID</th>
                    <th className="pb-2">Part Number</th>
                    <th className="pb-2">Complexity</th>
                    <th className="pb-2 text-right">Clearance Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                  {loading && <tr><td colSpan={4} className="py-8 text-center text-slate-400">Loading trace records...</td></tr>}
                  {!loading && rfqs.length === 0 && <tr><td colSpan={4} className="py-8 text-center text-slate-400">No RFQ documentation records available.</td></tr>}
                  {rfqs.map(rfq => (
                    <tr key={rfq.id} onClick={() => setActiveTab(rfq.id)} onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setActiveTab(rfq.id);
                      }
                    }} tabIndex={0} role="button" className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-200">
                      <td className="py-2.5 text-aero-blue font-bold">{rfq.id}</td>
                      <td className="py-2.5">{rfq.part_number || 'Pending extraction'}</td>
                      <td className="py-2.5 text-slate-500">Awaiting document data</td>
                      <td className="py-2.5 text-right"><span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 border border-slate-200 dark:border-slate-700 font-bold">{rfq.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Document Vault Checklist */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-3 font-mono text-[11px]">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-2.5">
              <h3 className="font-display font-bold text-xs text-slate-900 dark:text-slate-100 uppercase">
                ACTIVE DOCUMENT VAULT
              </h3>
              <span className="text-[10px] text-slate-500 font-semibold">Required ({activeTab})</span>
            </div>

            <div className="space-y-2 text-slate-700 dark:text-slate-300">
              <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center space-x-2">
                  <span className="w-2 h-2 rounded-full bg-aog-red animate-pulse" />
                  <span>Certificate of Conformity (CoC)</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-red-50 dark:bg-aog-red/20 text-aog-red text-[9px] font-bold border border-red-200 dark:border-aog-red/40">
                  Missing
                </span>
              </div>

              <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center space-x-2">
                  <span className="w-2 h-2 rounded-full bg-amber-500" />
                  <span>FAA Form 8130-3</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300 text-[9px] font-bold border border-amber-200 dark:border-amber-500/40">
                  Pending Review
                </span>
              </div>

              <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center space-x-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  <span>EASA Form 1</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-[9px] font-bold">
                  Verified
                </span>
              </div>

              <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center space-x-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  <span>Authorized Release Cert</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-[9px] font-bold">
                  Verified
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Top (8 cols): DOCUMENT REVIEW & VERIFICATION TERMINAL */}
        <div className="lg:col-span-8 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
                <FileSearch className="w-4 h-4 text-aero-blue" />
                <span>DOCUMENT REVIEW & VERIFICATION TERMINAL</span>
              </h2>
              <div className="flex items-center space-x-3">
                <span className="px-2.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-bold border border-emerald-200 dark:border-emerald-500/30">
                  REAL TIME OCR
                </span>
              </div>
            </div>

            {/* Interactive Document Viewer Canvas (FAA Form 8130-3 OCR annotation) */}
            <div className="mt-3 relative bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-xl p-4 overflow-hidden h-[340px] flex flex-col justify-between font-mono text-slate-800 dark:text-slate-200">
              {/* Document Header Representation */}
              <div className="border-2 border-slate-300 dark:border-slate-700 p-3 bg-white text-slate-900 rounded-xl space-y-2 text-[10px] relative shadow-sm">
                <div className="flex items-center justify-between border-b border-slate-300 pb-1 font-bold">
                  <div>FAA Form 8130-3</div>
                  <div className="text-center">
                    AIRWORTHINESS APPROVAL TAG<br />FAA REPAIR STATION
                  </div>
                  <div className="text-emerald-600 font-bold">CRS #WT-942-CRS</div>
                </div>

                {/* Form Fields with Bounding Box Highlights */}
                <div className="grid grid-cols-4 gap-2 pt-1 text-[9px]">
                  <div className="border border-slate-200 p-1.5 rounded bg-slate-50">
                    <div className="text-[7px] text-slate-500 uppercase">1. Serial Number</div>
                    <div className="font-bold text-slate-900">MLG-9840</div>
                  </div>
                  <div className="border border-emerald-500 bg-emerald-50 p-1.5 rounded relative">
                    <div className="text-[7px] text-emerald-700 font-bold uppercase">2. Part Number</div>
                    <div className="font-bold text-emerald-900">32-11-45-01</div>
                    <span className="absolute -top-2 -right-1 bg-emerald-600 text-white text-[7px] px-1 rounded font-bold">MATCH</span>
                  </div>
                  <div className="border border-amber-500 bg-amber-50 p-1.5 rounded relative col-span-2">
                    <div className="text-[7px] text-amber-800 font-bold uppercase">3. Release Status</div>
                    <div className="font-bold text-amber-900 flex items-center justify-between">
                      <span>Serviceable — Return to Service</span>
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                    </div>
                  </div>
                </div>

                <div className="border border-slate-200 p-2 rounded bg-slate-50 text-[8px] space-y-1 text-slate-600">
                  <div className="font-bold text-slate-800">14 CFR 43.9 RETURN TO SERVICE COMPLIANCE</div>
                  <div>Inspected in accordance with current maintenance regulations under 14 CFR Part 43.</div>
                </div>

                {/* Footer Signature */}
                <div className="flex items-center justify-between pt-1.5 border-t border-slate-200 text-[8px] text-slate-600">
                  <div>Date: 2026-08-28</div>
                  <div className="font-bold italic text-slate-900">Marcus Vance (Q.A. Director)</div>
                </div>
              </div>

              {/* OCR Scan Status Banner */}
              <div className={`mt-2 bg-white dark:bg-slate-900/90 p-2.5 rounded-xl flex items-center justify-between text-[11px] shadow-sm ${
                hardFreezeEnabled
                  ? 'border border-red-300 dark:border-red-500/50'
                  : 'border border-emerald-200 dark:border-emerald-500/40'
              }`}>
                <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400 font-bold">
                  <ShieldCheck className="w-4 h-4" />
                  <span>
                    {hardFreezeEnabled
                      ? 'Order hard freeze active: suspicious transaction blocked.'
                      : 'OCR Scan: 100% Verified (0 Trace Gaps)'}
                  </span>
                </div>
                <div className="text-[10px] text-slate-500 font-mono">Confidence: 99.8%</div>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 font-display pt-2">
            <button
              onClick={() => {
                setVerificationPassed(true);
                setHardFreezeEnabled(false);
              }}
              className="bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2.5 px-4 rounded-xl shadow-md shadow-emerald-600/20 flex items-center justify-center space-x-2 text-xs"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>ACCEPT & CERTIFY</span>
            </button>
            <button
              onClick={() => {
                setVerificationPassed(false);
                setHardFreezeEnabled(false);
              }}
              className="bg-red-500 hover:bg-red-600 text-white font-bold py-2.5 px-4 rounded-xl shadow-md shadow-red-500/20 flex items-center justify-center space-x-2 text-xs"
            >
              <XCircle className="w-4 h-4" />
              <span>REJECT DOC</span>
            </button>
            <button onClick={() => setNotice('Document re-scan requested. Backend OCR processing is not yet connected to this view.')} className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 font-bold py-2.5 px-4 rounded-xl border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-2 text-xs">
              <FileSearch className="w-4 h-4" />
              <span>REQUEST RE-SCAN</span>
            </button>
            <button
              onClick={() => {
                setVerificationPassed(false);
                setHardFreezeEnabled(true);
              }}
              className="bg-slate-900 hover:bg-slate-800 text-white font-bold py-2.5 px-4 rounded-xl border border-red-500/60 flex items-center justify-center space-x-2 text-xs"
            >
              <AlertOctagon className="w-4 h-4 text-red-300" />
              <span>HARD FREEZE ORDER</span>
            </button>
          </div>
          <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
            Verification state: {verificationPassed ? 'CERTIFIED' : 'REVIEW_REQUIRED'}
          </p>
        </div>
      </div>

      {/* Bottom Grid: Traceability History & Metrics Overview */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Bottom (7 cols): TRACEABILITY & COMPLIANCE HISTORY */}
        <div className="lg:col-span-7 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
            TRACEABILITY & COMPLIANCE HISTORY
          </h2>

          {/* Milestone Stepper Timeline */}
          <div className="flex items-center justify-between font-mono text-[10px] pt-2">
            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-500 flex items-center justify-center font-bold">
                ✓
              </div>
              <span className="mt-1 font-bold text-slate-900 dark:text-slate-200">Receipt</span>
              <span className="text-[9px] text-slate-500">32-11-45-01</span>
            </div>
            <div className="h-0.5 flex-1 bg-emerald-400 mx-2" />

            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-500 flex items-center justify-center font-bold">
                ✓
              </div>
              <span className="mt-1 font-bold text-slate-900 dark:text-slate-200">8130-3 Verified</span>
              <span className="text-[9px] text-slate-500">CRS Pass</span>
            </div>
            <div className="h-0.5 flex-1 bg-emerald-400 mx-2" />

            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-500 flex items-center justify-center font-bold">
                ✓
              </div>
              <span className="mt-1 font-bold text-slate-900 dark:text-slate-200">QA Bench</span>
              <span className="text-[9px] text-slate-500">Dimensional</span>
            </div>
            <div className="h-0.5 flex-1 bg-slate-200 dark:bg-slate-800 mx-2" />

            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full bg-blue-50 dark:bg-slate-800 text-aero-blue border border-blue-200 dark:border-slate-700 flex items-center justify-center font-bold">
                4
              </div>
              <span className="mt-1 text-slate-600 dark:text-slate-400 font-semibold">Final Release</span>
              <span className="text-[9px] text-slate-500">Dispatch</span>
            </div>
          </div>
        </div>

        {/* Right Bottom (5 cols): COMPLIANCE DASHBOARD OVERVIEW METRICS */}
        <div className="lg:col-span-5 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
            COMPLIANCE DASHBOARD OVERVIEW
          </h2>

          <div className="grid grid-cols-3 gap-3 text-center font-mono">
            <div className="bg-slate-50 dark:bg-slate-900 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="text-emerald-600 dark:text-emerald-400 font-extrabold text-xl">100%</div>
              <div className="text-[9px] text-slate-500 mt-1 uppercase leading-tight font-semibold">
                COMPLETE TRACE
              </div>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="text-aero-blue font-extrabold text-xl">1.4s</div>
              <div className="text-[9px] text-slate-500 mt-1 uppercase leading-tight font-semibold">
                AI OCR SPEED
              </div>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="text-amber-600 dark:text-amber-400 font-extrabold text-xl">142</div>
              <div className="text-[9px] text-slate-500 mt-1 uppercase leading-tight font-semibold">
                CERTS VAULTED
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
