import React, { useEffect, useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { apiService, getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { InternalCommand, InventoryItem, RFQ, Supplier, SupplierQuote } from '../../types';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';
import { 
  FileCheck, 
  AlertTriangle, 
  Send, 
  Split, 
  Flame, 
  CheckCircle,
  FileText,
  Loader2,
  Play,
  Pause,
} from 'lucide-react';
import { FallbackDataBanner } from '../common/FallbackDataBanner';
import { isFailedRfq, rfqStatusLabel } from '../../utils/rfqState';
import { useExecuteInternalCommand, useInventoryDirectory, useProcessRFQ, useRFQs, useSetAutomationPause, useSupplierDirectory, useSupplierOffers, useSupplierProfile } from '../../hooks/useApiResources';

export const AeroProcurementView: React.FC = () => {
  const [catalogTab, setCatalogTab] = useState<'inventory' | 'suppliers'>('inventory');
  const [selectedOfferId, setSelectedOfferId] = useState('');
  const [selectedRfqId, setSelectedRfqId] = useState('');
  const [selectedSupplierId, setSelectedSupplierId] = useState('');
  const [automationReason, setAutomationReason] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [commandPending, setCommandPending] = useState<InternalCommand | null>(null);
  const [noticeType, setNoticeType] = useState<'success' | 'error'>('success');
  const rfqQuery = useRFQs();
  const rfqs = rfqQuery.data || [];
  const loading = rfqQuery.isLoading;
  const loadError = rfqQuery.error?.message || null;
  const usingFallbackData = rfqQuery.isSampleData;
  const canViewInternalCatalog = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING']);
  const inventoryQuery = useInventoryDirectory(canViewInternalCatalog);
  const supplierDirectoryQuery = useSupplierDirectory(canViewInternalCatalog);
  const supplierProfileQuery = useSupplierProfile(selectedSupplierId);
  const inventory = inventoryQuery.data || [];
  const suppliers = supplierDirectoryQuery.data || [];
  const commandMutation = useExecuteInternalCommand();
  const processMutation = useProcessRFQ();
  const automationMutation = useSetAutomationPause();
  const selectedRfq = rfqs.find(rfq => rfq.id === selectedRfqId);
  const selectedPartNumber = selectedRfq?.part_number?.trim() || '';
  const actionsBlocked = loading || Boolean(loadError) || usingFallbackData || !selectedRfq || isFailedRfq(selectedRfq);
  const canProcessSelectedRfq = selectedRfq?.status === 'Intake'
    && !loading
    && !loadError
    && !usingFallbackData
    && apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING']);
  const canManageAutomation = Boolean(selectedRfq)
    && !loading
    && !loadError
    && !usingFallbackData
    && apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER']);
  const automationPaused = Boolean(selectedRfq?.automation_paused);
  const offersQuery = useSupplierOffers(selectedPartNumber);
  const offers = offersQuery.data || [];
  const selectedOffer = offers.find(offer => offer.id === selectedOfferId);
  const offersLoading = offersQuery.isLoading;
  const offersError = offersQuery.error?.message || null;

  useEffect(() => {
    if (!selectedRfqId && rfqs.length > 0) setSelectedRfqId(rfqs[0].id);
  }, [rfqs, selectedRfqId]);

  useEffect(() => {
    if (!selectedOfferId && offers.length > 0) setSelectedOfferId(offers[0].id);
  }, [offers, selectedOfferId]);

  useEffect(() => {
    if (!selectedSupplierId && suppliers.length > 0) setSelectedSupplierId(suppliers[0].id);
  }, [selectedSupplierId, suppliers]);

  useEffect(() => {
    setAutomationReason('');
  }, [selectedRfqId]);

  const runCommand = async (command: InternalCommand, description: string) => {
    if (actionsBlocked || commandMutation.isPending || !selectedRfq) return;
    if (!window.confirm(`Confirm ${description} for RFQ ${selectedRfq.id}?`)) return;
    setCommandPending(command);
    setNotice(null);
    try {
      const details = selectedOffer
        ? `Selected supplier offer ${selectedOffer.id} from ${selectedOffer.supplier_name}.`
        : undefined;
      const result = await commandMutation.mutateAsync({ command, entityId: selectedRfq.id, details });
      if (!result) return;
      setNoticeType('success');
      setNotice(result.message);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, `Unable to ${description}.`));
    } finally {
      setCommandPending(null);
    }
  };

  const processSelectedRfq = async () => {
    if (!selectedRfq || !canProcessSelectedRfq || processMutation.isPending) return;
    setNotice(null);
    try {
      const result = await processMutation.mutateAsync(selectedRfq.id);
      if (!result) return;
      const errorMessage = typeof result.error === 'string' ? result.error : null;
      const resultMessage = typeof result.message === 'string'
        ? result.message
        : typeof result.status === 'string'
          ? `RFQ processing returned ${result.status}.`
          : 'RFQ processing completed.';
      setNoticeType(errorMessage ? 'error' : 'success');
      setNotice(errorMessage || resultMessage);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, 'Unable to process this RFQ.'));
    }
  };

  const toggleAutomationPause = async () => {
    if (!selectedRfq || !canManageAutomation || automationMutation.isPending) return;
    const paused = !automationPaused;
    const reason = automationReason.trim();
    if (paused && !reason) return;
    if (!window.confirm(`${paused ? 'Pause' : 'Resume'} automation for RFQ ${selectedRfq.id}?`)) return;
    setNotice(null);
    try {
      const result = await automationMutation.mutateAsync({
        rfqId: selectedRfq.id,
        paused,
        reason: paused ? reason : undefined,
      });
      if (!result) return;
      setNoticeType('success');
      setNotice(paused ? 'Automation paused.' : 'Automation resumed.');
      setAutomationReason('');
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, `Unable to ${paused ? 'pause' : 'resume'} automation.`));
    }
  };

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
      {notice && <div role={noticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-xl border px-4 py-3 text-xs font-semibold ${noticeType === 'error' ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200' : 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-500/40 dark:bg-blue-500/10 dark:text-blue-200'}`}>{notice}</div>}
      {usingFallbackData && <FallbackDataBanner />}
      {loadError && <div role="alert" className="flex items-center justify-between rounded-xl border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"><span>{loadError}</span><button type="button" onClick={() => void rfqQuery.refetch()} className="font-bold underline">Retry</button></div>}
      {/* Top Section: Active RFQ Queue & Sourcing Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Active RFQ Queue (6 cols) */}
        <div className="lg:col-span-6 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aog-red animate-pulse" />
              <span>ACTIVE RFQ QUEUE (SLA FOCUSED)</span>
            </h2>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-[11px]">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-[10px]">
                  <th className="pb-2">RFQ ID</th>
                  <th className="pb-2">Part Number</th>
                  <th className="max-w-12 whitespace-normal pb-2 leading-tight">Requested<br />by</th>
                  <th className="pb-2">Urgency</th>
                  <th className="pb-2">SLA Status</th>
                  <th className="pb-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {loading && <tr><td colSpan={6} className="py-8 text-center text-slate-400" role="status">Loading RFQs...</td></tr>}
                {!loading && !loadError && rfqs.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-slate-400" role="status">No active RFQs.</td></tr>}
                {rfqs.map(rfq => {
                  return <tr key={rfq.id} tabIndex={0} role="button" aria-pressed={selectedRfqId === rfq.id} onClick={() => setSelectedRfqId(rfq.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedRfqId(rfq.id); } }} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 cursor-pointer transition-colors focus:outline-none focus-visible:bg-blue-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-aero-blue">
                    <td className="py-2.5 text-aero-blue font-bold">{rfq.id}</td>
                    <td className="py-2.5">
                      <div className="font-bold text-slate-900 dark:text-slate-200">{rfq.part_number || 'Pending extraction'}</div>
                      <div className={`text-[10px] truncate w-24 ${isFailedRfq(rfq) ? 'text-red-600 dark:text-red-400' : 'text-slate-500 dark:text-slate-400'}`}>{rfqStatusLabel(rfq)}</div>
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
                    <td className="py-2.5 text-right font-bold text-emerald-600 dark:text-emerald-400">{rfqStatusLabel(rfq)}</td>
                  </tr>;
                })}
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
            <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">P/N: {selectedRfq?.part_number || 'Unavailable'} | {selectedRfq?.condition || 'Condition unavailable'}</span>
          </div>

          {canManageAutomation && <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/60">
            <div className="min-w-0 flex-1">
              {automationPaused
                ? <p role="status" className="text-xs text-amber-800 dark:text-amber-200">Automation paused{selectedRfq?.pause_reason ? `: ${selectedRfq.pause_reason}` : '.'}</p>
                : <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300">
                  <span>Reason for pausing automation</span>
                  <input aria-label="Reason for pausing automation" value={automationReason} onChange={event => setAutomationReason(event.target.value)} maxLength={500} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" />
                </label>}
            </div>
            <button type="button" disabled={automationMutation.isPending || (!automationPaused && !automationReason.trim())} aria-busy={automationMutation.isPending} onClick={() => void toggleAutomationPause()} className={`inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50 ${automationPaused ? 'bg-emerald-700 text-white hover:bg-emerald-600' : 'bg-amber-600 text-white hover:bg-amber-500'}`}>
              {automationMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : automationPaused ? <Play className="h-3.5 w-3.5" aria-hidden="true" /> : <Pause className="h-3.5 w-3.5" aria-hidden="true" />}
              <span>{automationMutation.isPending ? 'SAVING...' : automationPaused ? 'RESUME AUTOMATION' : 'PAUSE AUTOMATION'}</span>
            </button>
          </div>}

          {canProcessSelectedRfq && <div className="flex items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800 dark:border-blue-500/40 dark:bg-blue-500/10 dark:text-blue-200">
            <span>RFQ is queued for intake processing.</span>
            <button type="button" disabled={processMutation.isPending} aria-busy={processMutation.isPending} onClick={() => void processSelectedRfq()} className="inline-flex min-h-10 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-blue-700 px-3 font-bold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60">
              {processMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Play className="h-3.5 w-3.5" aria-hidden="true" />}
              <span>{processMutation.isPending ? 'PROCESSING...' : 'PROCESS RFQ'}</span>
            </button>
          </div>}
          {isFailedRfq(selectedRfq) && <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-3 text-xs font-semibold text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300">{selectedRfq?.status.trim().toUpperCase() === 'NEEDS_HUMAN_REVIEW' ? 'Operator review required. Complete the review before processing.' : 'Intake failed. A safe retry requires an intake reset that is not available in this view.'} Sourcing and order actions are disabled.</div>}
          <div className="font-mono text-[11px] text-slate-800 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800">
            <span className="text-aero-blue font-bold">REQUEST:</span> {selectedRfq?.raw_text || 'Select an RFQ to view its submitted request.'}
          </div>

          <div className="space-y-2 font-mono text-[11px]">
            <h3 className="flex items-center justify-between gap-2 font-display text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
              <span>Live Supplier Offers</span>
              <span className="text-[10px] font-normal text-slate-500">{selectedPartNumber || 'Select an RFQ'}</span>
            </h3>
            {offersLoading && <p role="status" className="py-4 text-center text-slate-500">Loading supplier offers...</p>}
            {offersError && <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 p-3 text-xs text-red-700"><span>{offersError}</span><button type="button" onClick={() => void offersQuery.refetch()} className="shrink-0 font-bold underline">Retry</button></div>}
            {!offersLoading && !offersError && offers.length === 0 && <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">No persisted supplier offers are available for this part.</p>}
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              {offers.map(offer => (
                <button key={offer.id} type="button" aria-pressed={selectedOfferId === offer.id} onClick={() => setSelectedOfferId(offer.id)} className={`rounded-xl border p-3 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${selectedOfferId === offer.id ? 'border-aero-blue bg-blue-50 dark:bg-aero-blue/20' : 'border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900/60'}`}>
                  <span className="flex items-start justify-between gap-2 font-bold text-aero-blue"><span>{offer.supplier_name}</span><span>${offer.unit_cost.toLocaleString()}</span></span>
                  <span className="mt-2 block space-y-0.5 text-[10px] text-slate-600 dark:text-slate-300">
                    <span className="block">Condition: {offer.condition || 'Not provided'}</span>
                    <span className="block">Certificate: {offer.certificate_type || 'Not provided'}</span>
                    <span className="block">Available: {offer.quantity_available}</span>
                    <span className="block">Lead: {offer.lead_time_days} days{offer.location ? ` · ${offer.location}` : ''}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Traceability Compliance Vault */}
          <div className="bg-slate-50 dark:bg-slate-900/90 border border-slate-200 dark:border-slate-800 rounded-xl p-3.5 space-y-2 font-mono text-[11px]">
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-900 dark:text-slate-200 flex items-center space-x-1.5">
                <FileCheck className="w-4 h-4 text-emerald-500" />
                <span>TRACEABILITY COMPLIANCE VAULT</span>
              </span>
              <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
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
            <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'generate_quote'} onClick={() => void runCommand('generate_quote', 'generate a quote')} className="bg-aero-blue hover:bg-blue-600 text-white font-bold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center space-x-1 shadow-sm disabled:cursor-not-allowed disabled:opacity-50">
              {commandPending === 'generate_quote' ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <FileText className="w-3.5 h-3.5" />}
              <span>{commandPending === 'generate_quote' ? 'GENERATING...' : 'GENERATE SMART QUOTE'}</span>
            </button>
            <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'split_po'} onClick={() => void runCommand('split_po', 'split the purchase order')} className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 font-bold py-2.5 px-3 rounded-xl text-xs border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-1 disabled:cursor-not-allowed disabled:opacity-50">
              {commandPending === 'split_po' ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Split className="w-3.5 h-3.5" />}
              <span>{commandPending === 'split_po' ? 'SPLITTING...' : 'SPLIT PO'}</span>
            </button>
            <button type="button" disabled={actionsBlocked || commandMutation.isPending} aria-busy={commandPending === 'escalate_aog'} onClick={() => void runCommand('escalate_aog', 'escalate this AOG')} className="bg-red-700 hover:bg-red-600 text-white font-bold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center space-x-1 shadow aog-pulse-badge disabled:cursor-not-allowed disabled:opacity-50">
              {commandPending === 'escalate_aog' ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Flame className="w-3.5 h-3.5" />}
              <span>{commandPending === 'escalate_aog' ? 'ESCALATING...' : 'ESCALATE AOG'}</span>
            </button>
          </div>
        </div>
      </div>

      {canViewInternalCatalog && <section aria-labelledby="inventory-supplier-directory-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="inventory-supplier-directory-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">INVENTORY & SUPPLIER DIRECTORY</h2>
          <div role="tablist" aria-label="Internal catalog views" className="inline-flex border border-slate-300 dark:border-slate-700">
            <button type="button" role="tab" aria-selected={catalogTab === 'inventory'} onClick={() => setCatalogTab('inventory')} className={`min-h-9 px-3 text-xs font-semibold ${catalogTab === 'inventory' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>Inventory</button>
            <button type="button" role="tab" aria-selected={catalogTab === 'suppliers'} onClick={() => setCatalogTab('suppliers')} className={`min-h-9 px-3 text-xs font-semibold ${catalogTab === 'suppliers' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>Suppliers</button>
          </div>
        </div>
        {catalogTab === 'inventory' && inventoryQuery.isSampleData && <FallbackDataBanner message="Internal inventory is showing local sample records, not confirmed stock." />}
        {catalogTab === 'suppliers' && supplierDirectoryQuery.isSampleData && <FallbackDataBanner message="Supplier directory is showing local sample records, not confirmed supplier data." />}
        {catalogTab === 'inventory' && inventoryQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{inventoryQuery.error.message}</span><button type="button" onClick={() => void inventoryQuery.refetch()} className="font-bold underline">Retry</button></div>}
        {catalogTab === 'suppliers' && supplierDirectoryQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{supplierDirectoryQuery.error.message}</span><button type="button" onClick={() => void supplierDirectoryQuery.refetch()} className="font-bold underline">Retry</button></div>}
        {catalogTab === 'inventory' && <>
          {inventoryQuery.isLoading && <p role="status" className="py-4 text-center text-xs text-slate-500">Loading internal inventory...</p>}
          {!inventoryQuery.isLoading && !inventoryQuery.error && inventory.length === 0 && <p role="status" className="py-4 text-center text-xs text-slate-500">No inventory records are available.</p>}
          {inventory.length > 0 && <div className="overflow-x-auto border-y border-slate-200 dark:border-slate-800"><table className="w-full min-w-[740px] text-left text-xs">
            <thead><tr className="text-[10px] font-semibold uppercase text-slate-500"><th className="py-2 pr-3">Part</th><th className="py-2 pr-3">Serial</th><th className="py-2 pr-3">Condition</th><th className="py-2 pr-3 text-right">Available</th><th className="py-2 pr-3 text-right">Unit cost</th><th className="py-2 pr-3">Location</th><th className="py-2">Certificate</th></tr></thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">{inventory.map((item: InventoryItem) => <tr key={item.id}><td className="py-2 pr-3 font-semibold">{item.part_number}</td><td className="py-2 pr-3">{item.serial_number}</td><td className="py-2 pr-3">{item.condition_code}</td><td className="py-2 pr-3 text-right tabular-nums">{item.quantity_available.toLocaleString()}</td><td className="py-2 pr-3 text-right tabular-nums">${item.unit_cost.toLocaleString()}</td><td className="py-2 pr-3">{item.warehouse_location}</td><td className="py-2">{item.certificate_type}</td></tr>)}</tbody>
          </table></div>}
        </>}
        {catalogTab === 'suppliers' && <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.6fr)]">
          <div className="space-y-1" aria-label="Supplier directory">
            {supplierDirectoryQuery.isLoading && <p role="status" className="py-4 text-xs text-slate-500">Loading suppliers...</p>}
            {!supplierDirectoryQuery.isLoading && !supplierDirectoryQuery.error && suppliers.length === 0 && <p role="status" className="py-4 text-xs text-slate-500">No suppliers are available.</p>}
            {suppliers.map((supplier: Supplier) => <button key={supplier.id} type="button" aria-pressed={selectedSupplierId === supplier.id} onClick={() => setSelectedSupplierId(supplier.id)} className={`w-full rounded-md border px-3 py-2.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${selectedSupplierId === supplier.id ? 'border-aero-blue bg-blue-50 dark:bg-aero-blue/10' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900'}`}>
              <span className="flex items-center justify-between gap-2 text-xs font-bold"><span>{supplier.company_name}</span><span className="text-[10px] font-semibold uppercase text-slate-500">{supplier.approval_status}</span></span>
              <span className="mt-1 block text-[11px] text-slate-600 dark:text-slate-400">{supplier.country} · ITAR {supplier.itar_certified ? 'certified' : 'not certified'}</span>
            </button>)}
          </div>
          <div aria-live="polite" className="min-w-0 border-l border-slate-200 pl-4 dark:border-slate-800">
            {supplierProfileQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{supplierProfileQuery.error.message}</span><button type="button" onClick={() => void supplierProfileQuery.refetch()} className="font-bold underline">Retry</button></div>}
            {supplierProfileQuery.isLoading && <p role="status" className="py-4 text-xs text-slate-500">Loading supplier profile...</p>}
            {supplierProfileQuery.data && <div className="space-y-2 text-xs">
              <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">{supplierProfileQuery.data.company_name}</h3>
              <p>{supplierProfileQuery.data.contact_name}{supplierProfileQuery.data.contact_title ? ` · ${supplierProfileQuery.data.contact_title}` : ''}</p>
              <p><a className="underline" href={`mailto:${supplierProfileQuery.data.email}`}>{supplierProfileQuery.data.email}</a></p>
              <p>{supplierProfileQuery.data.phone}</p>
              <p>{supplierProfileQuery.data.address_line1}{supplierProfileQuery.data.address_line2 ? `, ${supplierProfileQuery.data.address_line2}` : ''}, {supplierProfileQuery.data.city}, {supplierProfileQuery.data.state_province} {supplierProfileQuery.data.postal_code}, {supplierProfileQuery.data.country}</p>
              <p>Approval: {supplierProfileQuery.data.approval_status} · ITAR: {supplierProfileQuery.data.itar_certified ? 'Certified' : 'Not certified'}</p>
              {supplierProfileQuery.data.notes && <p className="whitespace-pre-wrap text-slate-600 dark:text-slate-400">{supplierProfileQuery.data.notes}</p>}
            </div>}
          </div>
        </div>}
      </section>}

      {/* Bottom Section: AOG Triage Matrix & Lead Time Chart & Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* AOG Triage Heatmap Matrix (4 cols) */}
        <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
            AOG TRIAGE MATRIX (WORKLOAD VS RESPONSE)
          </h2>
          <Badge variant="outline">SAMPLE / DEMO DATA</Badge>

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
          <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
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
          <WorldMapTelemetry title="AERO-LOGISTICS ROUTE DEMO" subtitle="Example air and ground routes. Carrier locations are not live." />
        </div>
      </div>
    </div>
  );
};
