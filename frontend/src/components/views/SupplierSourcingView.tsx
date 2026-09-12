import React, { useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';
import { 
  CheckCircle, 
  PlusCircle, 
  Send, 
  ShieldCheck, 
  Clock, 
  Search,
  Filter
} from 'lucide-react';

export const SupplierSourcingView: React.FC = () => {
  const [selectedPn, setSelectedPn] = useState('32-11-45-01');
  const [notification, setNotification] = useState<string | null>(null);
  const [quotedRfqs, setQuotedRfqs] = useState<Set<string>>(new Set());

  const notify = (message: string) => {
    setNotification(message);
    setTimeout(() => setNotification(null), 4000);
  };

  const handleViewSourcing = (rfqId: string) => {
    notify(`Loaded live sourcing comparison for ${rfqId}.`);
  };

  const handleAddToQuote = () => {
    notify(`${selectedPn} added to active quote draft.`);
  };

  const handleIssuePo = () => {
    notify(`Purchase order drafted for ${selectedPn}. Routed to Procurement for signature.`);
  };

  const handleDocAudit = () => {
    notify(`Compliance document audit triggered for ${selectedPn}.`);
  };

  const handleQuickAdd = (supplier: string) => {
    setQuotedRfqs(prev => new Set(prev).add(supplier));
    notify(`Offer from ${supplier} quick-added to quote.`);
  };

  const activeRfqs = [
    { id: 'WT-29471', part: '32-11-45-01', name: 'Main Landing Gear Actuator', customer: 'GLOBAL AIRLINES', urgency: 'AOG', timer: '0:14:31' },
    { id: 'WT-29472', part: '32-11-45-01', name: 'Main Landing Gear Actuator', customer: 'GLOBAL AIRLINES', urgency: 'AOG', timer: '0:14:31' },
    { id: 'WT-29473', part: '32-11-45-01', name: 'Main Landing Gear Actuator', customer: 'GLOBAL AIRLINES', urgency: 'AOG', timer: '0:14:31' },
    { id: 'WT-29474', part: '32-11-45-01', name: 'Main Landing Gear Actuator', customer: 'GLOBAL AIRLINES', urgency: 'AOG', timer: '0:14:31' }
  ];

  const compareMatrix = [
    { name: 'Supplier A', rel: '96%', returnRate: '1.5%', cage: '1S300', loc: 'DFW', qty: 300, price: 14200, lead: '2 Days', cond: 'SV' },
    { name: 'Supplier B', rel: '96%', returnRate: '1.5%', cage: '1S300', loc: 'MIA', qty: 1200, price: 12300, lead: '2 Days', cond: 'SV' },
    { name: 'Supplier C', rel: '96%', returnRate: '1.5%', cage: '1S300', loc: 'FRA', qty: 300, price: 1300, lead: '3 Days', cond: 'OH' },
    { name: 'Supplier D', rel: '96%', returnRate: '1.5%', cage: '1S250', loc: 'NFO', qty: 1000, price: 1350, lead: '2 Days', cond: 'NEW' }
  ];

  const otdData = [
    { month: 'JAN', otd: 88, quality: 94 },
    { month: 'FEB', otd: 92, quality: 96 },
    { month: 'MAR', otd: 85, quality: 91 },
    { month: 'APR', otd: 95, quality: 98 },
    { month: 'MAY', otd: 91, quality: 95 },
    { month: 'JUN', otd: 96, quality: 97 }
  ];

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {/* Top Row: Global Sourcing Matrix & Part Sourcing Terminal & Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (5 cols): GLOBAL SOURCING MATRIX */}
        <div className="lg:col-span-5 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aero-blue animate-pulse" />
              <span>GLOBAL SOURCING MATRIX (ACTIVE RFQS)</span>
            </h2>
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-bold border border-emerald-200 dark:border-emerald-500/30">
              REAL TIME DATA
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left font-mono text-[11px]">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-[10px]">
                  <th className="pb-2">RFQ ID</th>
                  <th className="pb-2">Part Number</th>
                  <th className="pb-2">Requestor</th>
                  <th className="pb-2">Urgency</th>
                  <th className="pb-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {activeRfqs.map((rfq, i) => (
                  <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 cursor-pointer transition-colors">
                    <td className="py-2.5 text-aero-blue font-bold">{rfq.id}</td>
                    <td className="py-2.5">
                      <div className="font-bold text-slate-900 dark:text-slate-200">{rfq.part}</div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate w-28">{rfq.name}</div>
                    </td>
                    <td className="py-2.5 text-slate-600 dark:text-slate-300 text-[10px]">{rfq.customer}</td>
                    <td className="py-2.5">
                      <div className="flex flex-col">
                        <span className="px-2 py-0.5 rounded-full bg-red-50 dark:bg-aog-red/20 text-aog-red text-[9px] font-bold border border-red-200 dark:border-aog-red/40 w-max aog-pulse-badge">
                          {rfq.urgency}
                        </span>
                        <span className="text-[9px] text-aog-red font-mono font-semibold mt-0.5">
                          T-Minus {rfq.timer}
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5 text-right">
                      <button
                        onClick={() => handleViewSourcing(rfq.id)}
                        className="bg-blue-50 dark:bg-aero-blue/20 hover:bg-aero-blue text-aero-blue hover:text-white px-2.5 py-1 rounded-lg text-[10px] font-semibold border border-blue-200 dark:border-aero-blue/40 transition-colors"
                      >
                        View Sourcing
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Center Column (4 cols): PART SOURCING TERMINAL */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <span>PART SOURCING TERMINAL</span>
            </h2>
          </div>

          <div className="bg-slate-50 dark:bg-slate-900/90 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 text-[11px] font-mono text-slate-600 dark:text-slate-400 flex items-center justify-between">
            <span>Multi-source search:</span>
            <span className="text-aero-blue font-bold">{selectedPn}</span>
          </div>

          {/* Supplier Compare Matrix */}
          <div className="space-y-2">
            <h3 className="font-mono text-[10px] font-bold text-slate-400 uppercase">SUPPLIER COMPARE MATRIX</h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-left font-mono text-[10px]">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800">
                    <th className="pb-1.5">Supplier</th>
                    <th className="pb-1.5">OTD</th>
                    <th className="pb-1.5">Loc</th>
                    <th className="pb-1.5">Qty</th>
                    <th className="pb-1.5">Price</th>
                    <th className="pb-1.5">Lead</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                  {compareMatrix.map((row, idx) => (
                    <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300">
                      <td className="py-2 font-bold text-slate-900 dark:text-slate-100">{row.name}</td>
                      <td className="py-2 text-emerald-600 dark:text-emerald-400 font-bold">{row.rel}</td>
                      <td className="py-2">{row.loc}</td>
                      <td className="py-2 font-bold text-aero-blue">{row.qty}</td>
                      <td className="py-2 font-bold text-slate-900 dark:text-slate-100">${row.price.toLocaleString()}</td>
                      <td className="py-2 text-slate-500">{row.lead}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Sourcing Action Triggers */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-2">
            <button
              onClick={handleAddToQuote}
              className="bg-aero-blue hover:bg-blue-600 text-white font-bold py-2 px-2 rounded-xl text-[10px] flex items-center justify-center space-x-1 shadow-sm transition-colors"
            >
              <PlusCircle className="w-3 h-3" />
              <span>ADD TO QUOTE</span>
            </button>
            <button
              onClick={handleIssuePo}
              className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 font-bold py-2 px-2 rounded-xl text-[10px] border border-slate-200 dark:border-slate-700 transition-colors"
            >
              ISSUE PO
            </button>
            <button
              onClick={handleDocAudit}
              className="bg-amber-50 dark:bg-amber-600/20 hover:bg-amber-100 text-amber-700 dark:text-amber-300 font-bold py-2 px-2 rounded-xl text-[10px] border border-amber-200 dark:border-amber-500/40 transition-colors"
            >
              DOC AUDIT
            </button>
          </div>

          {notification && (
            <div className="bg-emerald-50 dark:bg-emerald-500/20 border border-emerald-300 dark:border-emerald-500 text-emerald-800 dark:text-emerald-300 p-2.5 rounded-xl flex items-center justify-between text-[10px] font-semibold animate-fade-in shadow-sm">
              <span>{notification}</span>
              <button onClick={() => setNotification(null)} className="text-slate-400 hover:text-slate-700 dark:hover:text-white">✕</button>
            </div>
          )}
        </div>

        {/* Right Column (3 cols): SUPPLIER PERFORMANCE & RATINGS & INVENTORY CHECK */}
        <div className="lg:col-span-3 space-y-4">
          {/* Supplier Performance Chart */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
              SUPPLIER PERFORMANCE & RATINGS
            </h2>
            <div className="h-28 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={otdData}>
                  <XAxis dataKey="month" stroke="#94a3b8" fontSize={9} />
                  <YAxis stroke="#94a3b8" fontSize={9} domain={[70, 100]} />
                  <Tooltip contentStyle={{ backgroundColor: '#ffffff', borderColor: '#e2e8f0', fontSize: '10px', borderRadius: '8px' }} />
                  <Line type="monotone" dataKey="otd" stroke="#006BFF" strokeWidth={2} dot={false} name="On-Time Delivery %" />
                  <Line type="monotone" dataKey="quality" stroke="#10B981" strokeWidth={2} dot={false} name="Quality Acceptance %" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Inventory Check Checklist */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-2.5 font-mono text-[11px]">
            <h3 className="font-bold text-slate-900 dark:text-slate-200 text-xs">Inventory Check</h3>
            <div className="space-y-2 text-slate-700 dark:text-slate-300">
              <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>Query Warehouse Database</span>
              </div>
              <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>Multiple Warehouse Check</span>
              </div>
              <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>Supplier Stock Verification</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Row: Multi-Channel Search & Aero-Logistics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Multi-Channel Supplier Search & Offers */}
        <div className="lg:col-span-6 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
              MULTI-CHANNEL SUPPLIER SEARCH & OFFERS
            </h2>
            <div className="relative w-48">
              <Search className="w-3 h-3 absolute left-2.5 top-2 text-slate-400" />
              <input
                type="text"
                value={selectedPn}
                onChange={(e) => setSelectedPn(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl pl-7 pr-2 py-1 text-[11px] font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:border-aero-blue"
              />
            </div>
          </div>

          <div className="space-y-2.5">
            {[
              { supplier: 'Aero Parts Direct LLC', name: 'Main Landing Gear Actuator (Internal)', pn: '32-11-45-01', price: '$14,200.00', cond: 'SV' },
              { supplier: 'Frankfurt Aero Logistics', name: 'External Supplier APIs / OEM Stock', pn: '32-11-45-01', price: '$11,800.00', cond: 'OH' },
              { supplier: 'Texas Aviation Components', name: 'Main Landing Gear, DFW Depot Stock', pn: '32-11-45-01', price: '$12,500.00', cond: 'SV' }
            ].map((item, i) => (
              <div key={i} className="bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between font-mono text-[11px]">
                <div>
                  <div className="font-bold text-slate-900 dark:text-slate-100">{item.supplier}</div>
                  <div className="text-[10px] text-slate-500 dark:text-slate-400">{item.name}</div>
                </div>
                <div className="text-right flex items-center space-x-3">
                  <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold border border-emerald-200 dark:border-emerald-800">
                    {item.cond}
                  </span>
                  <span className="font-bold text-slate-900 dark:text-slate-100">{item.price}</span>
                  <button
                    onClick={() => handleQuickAdd(item.supplier)}
                    disabled={quotedRfqs.has(item.supplier)}
                    className="bg-aero-blue hover:bg-blue-600 disabled:opacity-60 disabled:cursor-not-allowed text-white px-3 py-1 rounded-xl text-[10px] font-bold shadow-sm transition-colors"
                  >
                    {quotedRfqs.has(item.supplier) ? 'Added' : 'Quick-Add'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Aero-Logistics Map Preview */}
        <div className="lg:col-span-6">
          <WorldMapTelemetry title="AERO-LOGISTICS & SHIPMENT PREVIEW" subtitle="Reimagined next-generation flight and courier tracking" />
        </div>
      </div>
    </div>
  );
};
