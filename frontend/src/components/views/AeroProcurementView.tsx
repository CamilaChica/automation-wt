import React, { useEffect, useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { apiService } from '../../services/api';
import { RFQ } from '../../types';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';
import { 
  FileCheck, 
  AlertTriangle, 
  Send, 
  Split, 
  Flame, 
  CheckCircle,
  FileText
} from 'lucide-react';

export const AeroProcurementView: React.FC = () => {
  const [selectedSupplier, setSelectedSupplier] = useState<'A' | 'B' | 'C'>('A');
  const [rfqs, setRfqs] = useState<RFQ[]>([]);

  useEffect(() => {
    void apiService.getRFQs().then(setRfqs).catch(() => setRfqs([]));
  }, []);

  const leadTimeData = [
    { month: 'JAN', volume: 120 },
    { month: 'FEB', volume: 150 },
    { month: 'MAR', volume: 110 },
    { month: 'APR', volume: 180 },
    { month: 'MAY', volume: 210 },
    { month: 'JUN', volume: 190 }
  ];

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {/* Top Section: Active RFQ Queue & Sourcing Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Active RFQ Queue (6 cols) */}
        <div className="lg:col-span-6 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aog-red animate-pulse" />
              <span>ACTIVE RFQ QUEUE (SLA FOCUSED)</span>
            </h2>
            <span className="px-2.5 py-0.5 rounded-full bg-blue-50 dark:bg-aero-blue/10 text-aero-blue font-mono text-[10px] font-bold border border-blue-200 dark:border-aero-blue/30">
              REAL TIME DATA
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-[11px]">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-[10px]">
                  <th className="pb-2">RFQ ID</th>
                  <th className="pb-2">Part Number</th>
                  <th className="pb-2">Requestor</th>
                  <th className="pb-2">Urgency</th>
                  <th className="pb-2">SLA Status</th>
                  <th className="pb-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {rfqs.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-slate-400">No active RFQs.</td></tr>}
                {rfqs.map((rfq, idx) => (
                  <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 cursor-pointer transition-colors">
                    <td className="py-2.5 text-aero-blue font-bold">{rfq.id}</td>
                    <td className="py-2.5">
                      <div className="font-bold text-slate-900 dark:text-slate-200">{rfq.part_number || 'Pending extraction'}</div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate w-24">{rfq.status}</div>
                    </td>
                    <td className="py-2.5 text-slate-600 dark:text-slate-300 text-[10px]">{rfq.customer_name}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold ${
                        rfq.urgency === 'AOG' ? 'bg-red-50 dark:bg-aog-red/20 text-aog-red border border-red-200 dark:border-aog-red/40 aog-pulse-badge' : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                      }`}>
                        {rfq.urgency || 'Routine'}
                      </span>
                    </td>
                    <td className="py-2.5 text-aog-red font-mono text-[10px] font-bold">
                      {rfq.created_at ? new Date(rfq.created_at).toLocaleDateString() : 'Recent'}
                    </td>
                    <td className="py-2.5 text-right font-bold text-emerald-600 dark:text-emerald-400">{rfq.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* RFQ Detail & Sourcing Matrix (6 cols) */}
        <div className="lg:col-span-6 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
              RFQ DETAIL & SOURCING
            </h2>
            <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">P/N: 32-11-45-01 | SV</span>
          </div>

          <div className="font-mono text-[11px] text-slate-800 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800">
            <span className="text-aero-blue font-bold">PART:</span> Main Landing Gear Actuator | 32-11-45-01 | Condition: SV (Serviceable)
          </div>

          {/* Source Matrix Cards */}
          <div className="grid grid-cols-3 gap-2.5 font-mono text-[11px]">
            {/* Supplier A */}
            <div 
              onClick={() => setSelectedSupplier('A')}
              className={`p-3 rounded-xl border cursor-pointer transition-all ${
                selectedSupplier === 'A'
                  ? 'bg-blue-50/70 dark:bg-aero-blue/20 border-aero-blue text-slate-900 dark:text-white shadow-sm ring-1 ring-aero-blue'
                  : 'bg-slate-50 dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:border-slate-300 dark:hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold text-aero-blue">SUPPLIER A</span>
                <span className="font-bold text-emerald-600 dark:text-emerald-400">$14,200</span>
              </div>
              <div className="text-[10px] space-y-0.5 text-slate-600 dark:text-slate-300">
                <div className="font-bold">(INTERNAL STOCK)</div>
                <div>Condition: SV</div>
                <div>Cert: FAA 8130-3</div>
                <div>Lead: Immediate</div>
              </div>
            </div>

            {/* Supplier B */}
            <div 
              onClick={() => setSelectedSupplier('B')}
              className={`p-3 rounded-xl border cursor-pointer transition-all ${
                selectedSupplier === 'B'
                  ? 'bg-blue-50/70 dark:bg-aero-blue/20 border-aero-blue text-slate-900 dark:text-white shadow-sm ring-1 ring-aero-blue'
                  : 'bg-slate-50 dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:border-slate-300 dark:hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold text-slate-900 dark:text-slate-200">SUPPLIER B</span>
                <span className="font-bold text-slate-900 dark:text-slate-100">$11,800</span>
              </div>
              <div className="text-[10px] space-y-0.5 text-slate-500 dark:text-slate-400">
                <div>Condition: OH</div>
                <div>Cert: EASA Form 1</div>
                <div>Location: FRA</div>
                <div>Lead: 3 Days</div>
              </div>
            </div>

            {/* Supplier C */}
            <div 
              onClick={() => setSelectedSupplier('C')}
              className={`p-3 rounded-xl border cursor-pointer transition-all ${
                selectedSupplier === 'C'
                  ? 'bg-blue-50/70 dark:bg-aero-blue/20 border-aero-blue text-slate-900 dark:text-white shadow-sm ring-1 ring-aero-blue'
                  : 'bg-slate-50 dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:border-slate-300 dark:hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold text-slate-900 dark:text-slate-200">SUPPLIER C</span>
                <span className="font-bold text-slate-900 dark:text-slate-100">$12,500</span>
              </div>
              <div className="text-[10px] space-y-0.5 text-slate-500 dark:text-slate-400">
                <div>Condition: SV</div>
                <div>Cert: 8130-3</div>
                <div>Location: DFW</div>
                <div>Lead: Hot Shot</div>
              </div>
            </div>
          </div>

          {/* Traceability Compliance Vault */}
          <div className="bg-slate-50 dark:bg-slate-900/90 border border-slate-200 dark:border-slate-800 rounded-xl p-3.5 space-y-2 font-mono text-[11px]">
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-900 dark:text-slate-200 flex items-center space-x-1.5">
                <FileCheck className="w-4 h-4 text-emerald-500" />
                <span>TRACEABILITY COMPLIANCE VAULT</span>
              </span>
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-bold">Mandatory Documents Verified</span>
            </div>

            <div className="flex items-center space-x-4 text-[10px]">
              <div className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                <CheckCircle className="w-3 h-3" />
                <span>Non-Incident Statement</span>
              </div>
              <div className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                <CheckCircle className="w-3 h-3" />
                <span>Trace to 121 Operator</span>
              </div>
              <div className="flex items-center space-x-1 text-amber-600 dark:text-amber-400 font-semibold">
                <AlertTriangle className="w-3 h-3" />
                <span>Tag Date Verification</span>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="grid grid-cols-3 gap-2 pt-1 font-display">
            <button className="bg-aero-blue hover:bg-blue-600 text-white font-bold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center space-x-1 shadow-sm">
              <FileText className="w-3.5 h-3.5" />
              <span>GENERATE SMART QUOTE</span>
            </button>
            <button className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 font-bold py-2.5 px-3 rounded-xl text-xs border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-1">
              <Split className="w-3.5 h-3.5" />
              <span>SPLIT PO</span>
            </button>
            <button className="bg-red-500 hover:bg-red-600 text-white font-bold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center space-x-1 shadow aog-pulse-badge">
              <Flame className="w-3.5 h-3.5" />
              <span>ESCALATE AOG</span>
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Section: AOG Triage Matrix & Lead Time Chart & Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* AOG Triage Heatmap Matrix (4 cols) */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
            AOG TRIAGE MATRIX (WORKLOAD VS RESPONSE)
          </h2>

          {/* 3x3 Heatmap grid */}
          <div className="grid grid-cols-3 gap-2 text-center font-mono text-[10px] font-bold">
            <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/30">
              Low Workload
            </div>
            <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-500/30 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-500/40">
              High Workload
            </div>
            <div className="p-3 rounded-xl bg-red-50 dark:bg-aog-red/30 text-aog-red border border-red-200 dark:border-aog-red/50 aog-pulse-badge">
              Critical AOG
            </div>

            <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800 text-slate-400">
              -
            </div>
            <div className="p-3 rounded-xl bg-blue-50 dark:bg-aero-blue/30 text-aero-blue border border-blue-200 dark:border-aero-blue/40 font-extrabold text-xs">
              ✓ Active
            </div>
            <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-500/30 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-500/40">
              Short Turn
            </div>

            <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800 text-slate-400">
              -
            </div>
            <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800 text-slate-400">
              -
            </div>
            <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400">
              Routine
            </div>
          </div>
        </div>

        {/* Lead Time Analytics (3 cols) */}
        <div className="lg:col-span-3 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
          <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
            LEAD TIME & QUOTES VOLUME
          </h2>
          <div className="h-36 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={leadTimeData}>
                <XAxis dataKey="month" stroke="#94a3b8" fontSize={9} />
                <YAxis stroke="#94a3b8" fontSize={9} />
                <Tooltip contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e2e8f0', fontSize: '10px', borderRadius: '8px' }} />
                <Bar dataKey="volume" fill="#006BFF" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Aero-Logistics Telemetry Map (5 cols) */}
        <div className="lg:col-span-5">
          <WorldMapTelemetry title="AERO-LOGISTICS TRACKING" subtitle="In-transit flight and ground courier telemetry" />
        </div>
      </div>
    </div>
  );
};
