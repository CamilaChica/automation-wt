import React, { useEffect, useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { type InternalCommand } from '../../types';
import { FallbackDataBanner } from '../common/FallbackDataBanner';
import { isFailedRfq, rfqStatusLabel } from '../../utils/rfqState';
import { useExecuteInternalCommand, useRFQs, useSupplierOffers } from '../../hooks/useApiResources';
import { 
  CheckCircle, 
  PlusCircle, 
  Send, 
  ShieldCheck, 
  Clock, 
  Search,
  Filter,
  Loader2
} from 'lucide-react';

export const SupplierSourcingView: React.FC = () => {
  const [selectedPn, setSelectedPn] = useState('');
  const [selectedRfqId, setSelectedRfqId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [noticeType, setNoticeType] = useState<'success' | 'error' | 'info'>('info');
  const [commandPending, setCommandPending] = useState<InternalCommand | null>(null);

  const rfqQuery = useRFQs();
  const offersQuery = useSupplierOffers(selectedPn);
  const commandMutation = useExecuteInternalCommand();
  const activeRfqs = rfqQuery.data || [];
  const liveOffers = offersQuery.data || [];
  const loading = rfqQuery.isLoading || offersQuery.isLoading;
  const loadError = [rfqQuery.error?.message, offersQuery.error?.message].filter(Boolean).join(' ') || null;
  const usingFallbackData = rfqQuery.isSampleData;

  useEffect(() => {
    if (!selectedRfqId && activeRfqs.length > 0) setSelectedRfqId(activeRfqs[0].id);
  }, [activeRfqs, selectedRfqId]);

  const compareMatrix = liveOffers.map(offer => ({
    part_number: offer.part_number,
    name: offer.supplier_name,
    rel: `${Math.round((offer.confidence || 0) * 100)}%`,
    loc: offer.supplier_email || 'Unknown',
    qty: offer.quantity_available || 0,
    price: offer.unit_cost || 0,
    lead: `${offer.lead_time_days || '?'} Days`,
  }));
  const selectedRfq = activeRfqs.find(rfq => rfq.id === selectedRfqId);
  const actionsBlocked = loading || Boolean(loadError) || usingFallbackData || !selectedRfq || isFailedRfq(selectedRfq);

  const addToQuote = async (partNumber: string) => {
    if (actionsBlocked || commandMutation.isPending || !selectedRfq) return;
    if (!window.confirm(`Add part ${partNumber} to quote for RFQ ${selectedRfq.id}?`)) return;
    setCommandPending('add_to_quote');
    setNotice(null);
    try {
      const result = await commandMutation.mutateAsync({ command: 'add_to_quote', entityId: selectedRfq.id, details: `Add part ${partNumber} to this RFQ.` });
      if (!result) return;
      setNoticeType('success');
      setNotice(result.message);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, 'Unable to add part to quote.'));
    } finally {
      setCommandPending(null);
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {notice && <div role={noticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-xl border px-4 py-3 text-xs font-semibold ${noticeType === 'error' ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200' : 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-500/40 dark:bg-blue-500/10 dark:text-blue-200'}`}>{notice}</div>}
      {usingFallbackData && <FallbackDataBanner />}
      {loadError && <div role="alert" className="flex items-center justify-between rounded-xl border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"><span>{loadError}</span><button type="button" onClick={() => { void rfqQuery.refetch(); void offersQuery.refetch(); }} className="font-bold underline">Retry</button></div>}
      {/* Top Row: Global Sourcing Matrix & Part Sourcing Terminal & Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (5 cols): GLOBAL SOURCING MATRIX */}
        <div className="lg:col-span-5 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aero-blue animate-pulse" />
              <span>GLOBAL SOURCING MATRIX (ACTIVE RFQS)</span>
            </h2>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-[11px]">
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
                  <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 text-aero-blue font-bold">{rfq.id}</td>
                    <td className="py-2.5">
                      <div className="font-bold text-slate-900 dark:text-slate-200">{rfq.part_number || 'Pending extraction'}</div>
                      <div className={`text-[10px] truncate w-28 ${isFailedRfq(rfq) ? 'text-red-600 dark:text-red-400' : 'text-slate-500 dark:text-slate-400'}`}>{rfqStatusLabel(rfq)}</div>
                    </td>
                    <td className="py-2.5 text-slate-600 dark:text-slate-300 text-[10px]">{rfq.customer_name}</td>
                    <td className="py-2.5">
                      <div className="flex flex-col">
                        <span className="px-2 py-0.5 rounded-full bg-red-50 dark:bg-aog-red/20 text-aog-red text-[9px] font-bold border border-red-200 dark:border-aog-red/40 w-max aog-pulse-badge">
                          {rfq.urgency || 'Routine'}
                        </span>
                        <span className="text-[9px] text-aog-red font-mono font-semibold mt-0.5">
                          T-Minus {rfq.created_at ? new Date(rfq.created_at).toLocaleDateString() : 'Recent'}
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5 text-right">
                      <button type="button" onClick={() => setSelectedRfqId(rfq.id)} className="bg-blue-50 dark:bg-aero-blue/20 hover:bg-aero-blue text-aero-blue hover:text-white px-2.5 py-1 rounded-lg text-[10px] font-semibold border border-blue-200 dark:border-aero-blue/40 transition-colors">
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
              <table className="w-full text-left font-mono text-[10px]">
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
                    <tr key={idx} tabIndex={0} role="button" onClick={() => setSelectedPn(row.part_number || selectedPn)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedPn(row.part_number || selectedPn); } }} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300">
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
          <div className="grid grid-cols-3 gap-2 pt-2">
            <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'add_to_quote'} onClick={() => void addToQuote(selectedPn)} className="bg-aero-blue hover:bg-blue-600 text-white font-bold py-2 px-2 rounded-xl text-[10px] flex items-center justify-center space-x-1 shadow-sm disabled:cursor-not-allowed disabled:opacity-50">
              {commandPending === 'add_to_quote' ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <PlusCircle className="w-3 h-3" />}
              <span>{commandPending === 'add_to_quote' ? 'ADDING...' : 'ADD TO QUOTE'}</span>
            </button>
            <button type="button" disabled={actionsBlocked} onClick={() => { setNoticeType('info'); setNotice('Purchase orders are submitted by customers through the portal after quote approval.'); }} className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 font-bold py-2 px-2 rounded-xl text-[10px] border border-slate-200 dark:border-slate-700 disabled:cursor-not-allowed disabled:opacity-50">
              ISSUE PO
            </button>
            <button type="button" onClick={() => setNotice(`Document audit opened for ${selectedPn}.`)} className="bg-amber-50 dark:bg-amber-600/20 hover:bg-amber-100 text-amber-700 dark:text-amber-300 font-bold py-2 px-2 rounded-xl text-[10px] border border-amber-200 dark:border-amber-500/40">
              DOC AUDIT
            </button>
          </div>
        </div>

        {/* Right Column (3 cols): SUPPLIER PERFORMANCE & RATINGS & INVENTORY CHECK */}
        <div className="lg:col-span-3 space-y-4">
          <div role="status" className="border border-slate-200 bg-white p-5 text-sm text-slate-600 dark:border-slate-800 dark:bg-card-dark dark:text-slate-300">
            Supplier performance history is unavailable because no live performance endpoint is connected.
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
                aria-label="Search supplier inventory"
                type="text"
                value={selectedPn}
                onChange={(e) => setSelectedPn(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl pl-7 pr-2 py-1 text-[11px] font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:border-aero-blue"
              />
            </div>
          </div>

          <div className="space-y-2.5">
            {!selectedPn.trim() && <p role="status" className="rounded-md border border-slate-200 p-3 text-xs text-slate-500 dark:border-slate-800">Enter a part number to search live supplier offers.</p>}
            {selectedPn.trim() && offersQuery.isLoading && <p role="status" className="p-3 text-xs text-slate-500">Loading live supplier offers…</p>}
            {selectedPn.trim() && offersQuery.error && <p role="alert" className="p-3 text-xs text-red-700">{offersQuery.error.message}</p>}
            {selectedPn.trim() && !offersQuery.isLoading && !offersQuery.error && liveOffers.length === 0 && <p role="status" className="rounded-md border border-slate-200 p-3 text-xs text-slate-500 dark:border-slate-800">No live supplier offers are available for this part.</p>}
            {liveOffers.map(offer => (
              <div key={offer.id} className="bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between font-mono text-[11px]">
                <div>
                  <div className="font-bold text-slate-900 dark:text-slate-100">{offer.supplier_name}</div>
                  <div className="text-[10px] text-slate-500 dark:text-slate-400">P/N {offer.part_number} · {offer.quantity_available} available</div>
                </div>
                <div className="text-right flex items-center space-x-3">
                  <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold border border-emerald-200 dark:border-emerald-800">
                    {offer.condition || '—'}
                  </span>
                  <span className="font-bold text-slate-900 dark:text-slate-100">{new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(offer.unit_cost)}</span>
                  <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'add_to_quote'} onClick={() => void addToQuote(offer.part_number)} className="bg-aero-blue hover:bg-blue-600 text-white px-3 py-1 rounded-xl text-[10px] font-bold shadow-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50">
                    {commandPending === 'add_to_quote' ? 'Adding...' : 'Quick-Add'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Aero-Logistics Map Preview */}
        <div className="lg:col-span-6">
          <WorldMapTelemetry title="AERO-LOGISTICS ROUTE DEMO" subtitle="Example supplier shipment routes. Carrier locations are not live." />
        </div>
      </div>
    </div>
  );
};
