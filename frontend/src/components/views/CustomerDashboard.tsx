import React, { useEffect, useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { WorkflowStepper } from '../common/WorkflowStepper';
import { getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { FallbackDataBanner } from '../common/FallbackDataBanner';
import { RFQ } from '../../types';
import { isFailedRfq } from '../../utils/rfqState';
import { getAgentIdentity } from '../../services/agentIdentity';
import { useCreateRFQ, useDispatchQuote, useRFQDetail, useRFQs, useShipments } from '../../hooks/useApiResources';
import { 
  Send, 
  CheckCircle, 
  AlertTriangle, 
  FileCheck, 
  Download, 
  ExternalLink,
  ChevronRight,
  ShieldCheck,
  FileText,
  Clock,
  Plane,
  Package,
  CheckCircle2,
  XCircle,
  Search,
  Filter,
  ArrowRight,
  TrendingUp,
  Sparkles,
  Info,
  Calendar,
  DollarSign,
  Layers,
  Award,
  Eye,
  X,
  Loader2
} from 'lucide-react';

type ClientTab = 'quotations' | 'new-rfq' | 'tracking' | 'trace-vault' | 'analytics';
type ConditionKey = 'SV' | 'OH' | 'NEW' | 'AR';

export const CustomerDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ClientTab>('quotations');

  // Form State for RFQ
  const [partNumber, setPartNumber] = useState('32-11-45-01');
  const [partName, setPartName] = useState('Main Landing Gear Actuator');
  const [ataChapter, setAtaChapter] = useState('32');
  const [aircraftType, setAircraftType] = useState('Boeing 737-800 / MAX');
  const [quantity, setQuantity] = useState(1);
  const [urgency, setUrgency] = useState<'AOG' | 'Critical' | 'Routine'>('AOG');
  const [deliveryIcao, setDeliveryIcao] = useState('MIA');
  const [dockLocation, setDockLocation] = useState('Dock A-12 (Line Maint)');
  const [requiredDate, setRequiredDate] = useState('2026-09-08');
  const [conditions, setConditions] = useState<Record<ConditionKey, boolean>>({ SV: true, OH: true, NEW: false, AR: false });
  const [documents, setDocuments] = useState({ faa8130: true, easaForm1: false, trace121: true, nonIncident: true });
  
  // Active RFQs & Quotations
  const [selectedRfqId, setSelectedRfqId] = useState('');
  const [notification, setNotification] = useState<{ type: 'success' | 'info' | 'error'; message: string } | null>(null);
  const [selectedOption, setSelectedOption] = useState<'A' | 'B' | 'C'>('A');

  // Modals
  const [isApproveModalOpen, setIsApproveModalOpen] = useState(false);
  const [isDocModalOpen, setIsDocModalOpen] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<{ tag: string; pn: string; sn: string; cert: string; date: string } | null>(null);
  const [approverName, setApproverName] = useState('Alex R. (Lead MRO Engineer)');

  const rfqQuery = useRFQs();
  const shipmentQuery = useShipments();
  const rfqDetailQuery = useRFQDetail(selectedRfqId);
  const createRfqMutation = useCreateRFQ();
  const dispatchQuoteMutation = useDispatchQuote();
  const activeRfqs = rfqQuery.data || [];
  const selectedRfqDetail = rfqDetailQuery.data;
  const shipments = shipmentQuery.data || [];
  const loadingRfqs = rfqQuery.isLoading;
  const loadingShipments = shipmentQuery.isLoading;
  const loadingRfqDetail = rfqDetailQuery.isLoading;
  const rfqLoadError = rfqQuery.error?.message || null;
  const shipmentLoadError = shipmentQuery.error?.message || null;
  const rfqDetailError = rfqDetailQuery.error?.message || null;
  const usingFallbackData = rfqQuery.isSampleData;
  const approving = dispatchQuoteMutation.isPending;
  const submitting = createRfqMutation.isPending;
  const refreshRfqs = rfqQuery.refetch;
  const refreshShipments = shipmentQuery.refetch;

  const selectedRfq: RFQ = activeRfqs.find(r => r.id === selectedRfqId) || {
    id: selectedRfqId || 'No RFQ selected',
    customer_name: 'Customer',
    customer_email: '',
    status: 'Loading',
    raw_text: '',
    created_at: new Date(0).toISOString()
  };
  const selectedRfqFailed = isFailedRfq(activeRfqs.find(rfq => rfq.id === selectedRfqId));
  const liveQuote = selectedRfqDetail && !selectedRfqDetail.isFallback
    ? selectedRfqDetail.quote_details?.quote
    : undefined;

  const readyForApprovalCount = activeRfqs.filter(rfq =>
    ['quoted', 'quote_ready', 'pending_approval', 'pending_internal_review'].includes(rfq.status.trim().toLowerCase().replace(/[\s-]+/g, '_')),
  ).length;
  const inTransitShipmentCount = shipments.filter(shipment => /transit|shipped|out_for_delivery/i.test(shipment.status)).length;

  useEffect(() => {
    if (!selectedRfqId && activeRfqs.length > 0) setSelectedRfqId(activeRfqs[0].id);
  }, [activeRfqs, selectedRfqId]);

  // Quick Preset Handlers
  const applyPreset = (preset: 'aog-actuator' | 'routine-overhaul' | 'hydraulic-pump' | 'avionics') => {
    if (preset === 'aog-actuator') {
      setPartNumber('32-11-45-01');
      setPartName('Main Landing Gear Actuator');
      setAtaChapter('32');
      setAircraftType('Boeing 737-800');
      setQuantity(1);
      setUrgency('AOG');
      setConditions({ SV: true, OH: false, NEW: false, AR: false });
    } else if (preset === 'routine-overhaul') {
      setPartNumber('32-11-45-01');
      setPartName('Main Landing Gear Actuator (Overhaul)');
      setAtaChapter('32');
      setAircraftType('Boeing 737-MAX');
      setQuantity(2);
      setUrgency('Routine');
      setConditions({ SV: false, OH: true, NEW: false, AR: false });
    } else if (preset === 'hydraulic-pump') {
      setPartNumber('747-1011-00');
      setPartName('Engine-Driven Hydraulic Pump');
      setAtaChapter('29');
      setAircraftType('Boeing 777-300ER');
      setQuantity(1);
      setUrgency('Critical');
      setConditions({ SV: true, OH: true, NEW: false, AR: false });
    } else if (preset === 'avionics') {
      setPartNumber('NAV-4402-A');
      setPartName('Flight Management Guidance Computer');
      setAtaChapter('34');
      setAircraftType('Airbus A320neo');
      setQuantity(1);
      setUrgency('Routine');
      setConditions({ SV: true, OH: false, NEW: true, AR: false });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const rawText = `RFQ P/N ${partNumber} (${partName}) Qty ${quantity} Condition: ${Object.keys(conditions).filter(key => conditions[key as ConditionKey]).join(', ')} Urgency: ${urgency} Delivery: ${deliveryIcao} ${dockLocation}`;
    try {
      const res = await createRfqMutation.mutateAsync({ raw_text: rawText, customer_name: 'GLOBAL AIRLINES', customer_email: 'mro.ops@globalairlines.com' });
      if (!res) return;
      setSelectedRfqId(res.rfq_id);
      setActiveTab('quotations');
      setNotification({ type: 'success', message: `RFQ ${res.rfq_id} submitted and is now visible in your RFQ list.` });
      setTimeout(() => setNotification(null), 6000);
    } catch (error) {
      setNotification({ type: 'error', message: getApiErrorMessage(error, 'RFQ submission failed. Please retry.') });
    }
  };

  const handleApproveQuote = async () => {
    if (approving) return;
    if (usingFallbackData || selectedRfqFailed || !liveQuote || selectedRfqDetail?.isFallback) {
      setNotification({ type: 'error', message: selectedRfqFailed ? 'Intake failed. Approval is disabled; contact intake operations.' : 'Approval is disabled until a persisted quote is available.' });
      return;
    }
    try {
      const result = await dispatchQuoteMutation.mutateAsync({ quoteId: liveQuote.id, operatorName: approverName });
      if (!result) return;
      setIsApproveModalOpen(false);
      setNotification({ type: 'success', message: result.message });
      setTimeout(() => setNotification(null), 7000);
    } catch (error) {
      setNotification({ type: 'error', message: getApiErrorMessage(error, 'Quote approval failed. Please retry.') });
    }
  };

  const openDocViewer = (tag: string, pn: string, sn: string, cert: string, date: string) => {
    setSelectedDoc({ tag, pn, sn, cert, date });
    setIsDocModalOpen(true);
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans">
      <div role="note" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[10px] text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
        <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
        <span>Pricing options, document previews, and response-time estimates are illustrative. RFQ and shipment counts load from the API.</span>
      </div>
      {usingFallbackData && <FallbackDataBanner message="RFQ API unavailable; local sample RFQs are shown and mutation actions are disabled." />}
      {/* 1. Client Header & Profile Card */}
      <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm transition-all">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex min-w-0 items-center space-x-3.5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-tr from-blue-600 to-sky-400 text-lg font-display font-bold text-white shadow-md shadow-blue-500/20">
              GA
            </div>
            <div>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <h1 className="text-xl font-display font-bold text-slate-900 dark:text-white">
                  GLOBAL AIRLINES
                </h1>
                <span className="inline-flex shrink-0 items-center whitespace-nowrap leading-4 bg-blue-50 dark:bg-blue-950/40 text-aero-blue border border-blue-200 dark:border-blue-800 text-[11px] font-mono font-bold px-2 py-0.5 rounded-full">
                  MRO FLEET OPS
                </span>
                <span className="inline-flex shrink-0 items-center space-x-1 whitespace-nowrap leading-4 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 text-[11px] font-mono font-bold px-2 py-0.5 rounded-full">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span>VIP GOLD TIER</span>
                </span>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Account ID: <span className="font-mono font-semibold text-slate-700 dark:text-slate-300">GL-8820</span> • Primary Hub: <span className="font-semibold text-slate-700 dark:text-slate-300">MIA Intl Airport (Miami, FL)</span>
              </p>
            </div>
          </div>

          {/* Action Button */}
          <div className="flex items-center space-x-3">
            <button
              onClick={() => setActiveTab('new-rfq')}
              className="bg-aero-blue hover:bg-blue-600 text-white font-display font-bold text-xs px-4 py-2.5 rounded-xl shadow-md shadow-aero-blue/20 flex items-center space-x-2 transition-all transform active:scale-95"
            >
              <Send className="w-4 h-4" />
              <span>+ NEW QUICK RFQ</span>
            </button>
          </div>
        </div>

        {/* Quick KPI Stat Tiles */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5 pt-4 border-t border-slate-100 dark:border-slate-800/80">
          <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-100 dark:border-slate-800">
            <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">ACTIVE RFQS</div>
            <div className="text-xl font-display font-bold text-slate-900 dark:text-white mt-0.5 flex items-center justify-between">
              <span>{loadingRfqs ? '…' : rfqLoadError ? '—' : activeRfqs.length}</span>
              <Package className="w-4 h-4 text-blue-500" />
            </div>
          </div>

          <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-100 dark:border-slate-800">
            <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">READY FOR APPROVAL</div>
            <div className="text-xl font-display font-bold text-amber-600 dark:text-amber-400 mt-0.5 flex items-center justify-between">
              <span>{loadingRfqs ? '…' : rfqLoadError ? '—' : readyForApprovalCount}</span>
              <Clock className="w-4 h-4 text-amber-500" />
            </div>
          </div>

          <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-100 dark:border-slate-800">
            <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">IN-TRANSIT SHIPMENTS</div>
            <div className="text-xl font-display font-bold text-emerald-600 dark:text-emerald-400 mt-0.5 flex items-center justify-between">
              <span>{loadingShipments ? '…' : shipmentLoadError ? '—' : inTransitShipmentCount}</span>
              <Plane className="w-4 h-4 text-emerald-500" />
            </div>
            {shipmentLoadError && <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-red-700" role="alert"><span>{shipmentLoadError}</span><button type="button" onClick={() => void refreshShipments()} className="shrink-0 font-bold underline">Retry</button></div>}
          </div>

          <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-100 dark:border-slate-800">
            <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">AVG RESPONSE SLA</div>
            <div className="text-xl font-display font-bold text-aero-blue mt-0.5 flex items-center justify-between">
              <span>14.2 min</span>
              <ShieldCheck className="w-4 h-4 text-aero-blue" />
            </div>
            <Badge variant="outline" className="mt-2">SAMPLE / DEMO DATA</Badge>
          </div>
        </div>
      </div>

      {/* 2. Notification Banner */}
      {notification && (
        <div role={notification.type === 'error' ? 'alert' : 'status'} aria-live="polite" className={`border p-4 rounded-xl flex items-center justify-between text-xs font-semibold shadow-sm animate-fade-in ${notification.type === 'error' ? 'bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800 text-red-800 dark:text-red-300' : 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'}`}>
          <div className="flex items-center space-x-2.5">
            {notification.type === 'error' ? <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" /> : <CheckCircle className="w-5 h-5 text-emerald-500 shrink-0" />}
            <span>{notification.message}</span>
          </div>
          <button 
            onClick={() => setNotification(null)}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-white p-1 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* 3. Client Sub-Navigation Bar (Light & Easy to Navigate) */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-1">
        <nav aria-label="Customer dashboard" className="w-full min-w-0 overflow-x-auto">
          <div className="flex w-max min-w-max flex-nowrap items-center gap-2 sm:gap-4">
          {[
            { id: 'quotations', label: 'Quotations & Approvals', icon: FileText, badge: '2 Ready' },
            { id: 'new-rfq', label: 'Submit New RFQ', icon: Send, badge: null },
            { id: 'tracking', label: 'Shipment Route Demo', icon: Plane, badge: 'Sample' },
            { id: 'trace-vault', label: 'Airworthiness Trace Vault', icon: ShieldCheck, badge: '4 Certs' },
            { id: 'analytics', label: 'Spend & Fleet Analytics', icon: TrendingUp, badge: null }
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as ClientTab)}
                className={`flex shrink-0 items-center space-x-2 py-3 px-3.5 border-b-2 font-display text-xs font-bold transition-all whitespace-nowrap ${
                  isActive
                    ? 'border-aero-blue text-aero-blue bg-blue-50/50 dark:bg-blue-950/20 rounded-t-lg'
                    : 'border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:border-slate-300'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-aero-blue' : 'text-slate-400'}`} />
                <span>{tab.label}</span>
                {tab.badge && (
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full font-bold ${
                    isActive 
                      ? 'bg-aero-blue text-white' 
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                  }`}>
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
          </div>
        </nav>
      </div>

      {/* 4. Tab Contents */}

      {/* TAB 1: QUOTATIONS & APPROVALS */}
      {activeTab === 'quotations' && (
        <div className="space-y-6">
          {/* Progress Tracker Stepper */}
          <WorkflowStepper currentStepIndex={6} />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Column (5 Cols): Quotation Inbox List */}
            <div className="lg:col-span-5 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm flex flex-col justify-between">
              <div>
                <div className="mb-4 flex min-w-0 flex-col gap-2 border-b border-slate-100 pb-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <h2 className="font-display font-bold text-sm text-slate-900 dark:text-white">
                      ACTIVE QUOTES & RFQS
                    </h2>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">Select an item to view sourcing comparison & approve.</p>
                  </div>
                  <span className="inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold leading-none text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {activeRfqs.length} Total
                  </span>
                </div>

                {/* RFQs List Cards */}
                <div className="space-y-2.5">
                  {loadingRfqs && <div className="space-y-2" role="status" aria-live="polite" aria-busy="true"><div className="h-16 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" /><div className="h-16 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" /></div>}
                  {rfqLoadError && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">{rfqLoadError}<button type="button" onClick={() => void refreshRfqs()} className="ml-2 font-bold underline">Retry</button></div>}
                  {!loadingRfqs && !rfqLoadError && activeRfqs.length === 0 && <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">No RFQs are currently available.</p>}
                  {activeRfqs.map((rfq) => {
                    const isSelected = selectedRfqId === rfq.id;
                    const isAOG = rfq.urgency === 'AOG';
                    return (
                      <div
                        key={rfq.id}
                        onClick={() => setSelectedRfqId(rfq.id)}
                        className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                          isSelected
                            ? 'bg-blue-50/70 dark:bg-slate-800/80 border-aero-blue shadow-sm'
                            : 'bg-white dark:bg-slate-900/40 border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-start justify-between">
                          <div className="space-y-1">
                            <div className="flex items-center space-x-2">
                              <span className="font-mono font-bold text-xs text-aero-blue">{rfq.id}</span>
                              <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full ${
                                isAOG
                                  ? 'bg-red-50 dark:bg-red-950/40 text-aog-red border border-red-200 dark:border-red-900'
                                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                              }`}>
                                {rfq.urgency}
                              </span>
                              <span className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded-full">
                                {rfq.status}
                              </span>
                            </div>
                            <div className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">
                              P/N: {rfq.part_number || '32-11-45-01'} (Qty: {rfq.quantity || 1})
                            </div>
                            <div className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-1">
                              {rfq.raw_text}
                            </div>
                          </div>

                          <div className="text-right shrink-0">
                            <div className="font-mono font-bold text-sm text-slate-900 dark:text-white">
                              ${rfq.best_price?.toLocaleString()}
                            </div>
                            <div className="text-[10px] font-mono text-slate-500 dark:text-slate-400">
                              {rfq.lead_time}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-[11px] text-slate-500 font-mono">
                <span>Auto-sourcing active</span>
                <span className="text-aero-blue font-semibold">FastAPI Gateway Connected</span>
              </div>
            </div>

            {/* Right Column (7 Cols): Detailed Quotation Review & Approval Panel */}
            <div className="lg:col-span-7 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-5">
              <div className="flex min-w-0 flex-col gap-3 border-b border-slate-100 pb-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
                    <span className="text-xs text-slate-500 dark:text-slate-400">PROPOSAL REVIEW</span>
                    <h2 className="flex min-w-0 flex-wrap items-baseline gap-x-2 font-display text-sm font-bold leading-tight text-slate-900 dark:text-white sm:text-base">
                      <span>RFQ {selectedRfq.id}</span>
                      <span className="whitespace-nowrap">P/N {selectedRfq.part_number || '32-11-45-01'}</span>
                    </h2>
                  </div>
                  <p className="mt-1 break-words text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                    Main Landing Gear Actuator • Aircraft Type: Boeing 737-800
                  </p>
                </div>

                <button 
                  onClick={() => openDocViewer('8130-3-2026-99', selectedRfq.part_number || '32-11-45-01', 'MLG-9840', 'FAA 8130-3 Airworthiness Release', '2026-08-28')}
                  className="inline-flex min-h-11 shrink-0 items-center justify-center space-x-1.5 rounded-lg border border-slate-200 bg-slate-100 px-3 text-[11px] text-slate-700 transition-colors hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                >
                  <Eye className="w-3.5 h-3.5 text-aero-blue" />
                  <span>Preview FAA 8130-3</span>
                </button>
              </div>

              {rfqDetailError && <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"><span>{rfqDetailError}</span><button type="button" onClick={() => void rfqDetailQuery.refetch()} className="shrink-0 font-bold underline">Retry</button></div>}
              {loadingRfqDetail && <p role="status" className="text-xs text-slate-500">Loading persisted quote details...</p>}
              {!loadingRfqDetail && !rfqDetailError && selectedRfqDetail && !liveQuote && <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">No quote is attached to this RFQ yet.</p>}
              {selectedRfqFailed && <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-3 text-xs font-semibold text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300">{activeRfqs.find(rfq => rfq.id === selectedRfqId)?.status.trim().toUpperCase() === 'NEEDS_HUMAN_REVIEW' ? 'Operator review required.' : 'Intake failed.'} Approval and sourcing actions are disabled. Contact intake operations for escalation; the reprocess API is not available.</div>}

              {/* Sourcing Option Comparison Cards */}
              <div className="space-y-3">
                <div className="text-xs font-display font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider flex items-center justify-between">
                  <span>Available Inventory & Sourcing Options</span>
                  <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {/* Option A (Recommended / Internal Stock) */}
                  <div 
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedOption('A')}
                    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedOption('A'); } }}
                    className={`p-3.5 rounded-xl border cursor-pointer relative transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${
                      selectedOption === 'A'
                        ? 'border-aero-blue bg-blue-50/50 dark:bg-blue-950/20 shadow-sm ring-1 ring-aero-blue'
                        : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30'
                    }`}
                  >
                    <div className="absolute top-2.5 right-2.5">
                      <span className="bg-aero-blue text-white text-[9px] font-bold font-mono px-1.5 py-0.5 rounded">
                        RECOMMENDED
                      </span>
                    </div>

                    <div className="font-mono text-xs font-bold text-slate-900 dark:text-white">
                      OPTION A
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono">Miami Internal Warehouse</div>

                    <div className="my-2.5">
                      <div className="text-lg font-display font-bold text-emerald-600 dark:text-emerald-400">
                        $14,200
                      </div>
                      <div className="text-[10px] font-mono text-slate-500">1 Day • Hot-Shot Dispatch</div>
                    </div>

                    <div className="space-y-1 text-[10px] font-mono text-slate-600 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-2">
                      <div>Condition: <span className="font-bold text-slate-800 dark:text-slate-200">SV (Serviceable)</span></div>
                      <div>Release: <span className="text-emerald-600 dark:text-emerald-400 font-semibold">FAA 8130-3</span></div>
                      <div>Trace: <span className="text-emerald-600 dark:text-emerald-400 font-semibold">121 Operator</span></div>
                    </div>
                  </div>

                  {/* Option B (Overhauled / Frankfurt) */}
                  <div 
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedOption('B')}
                    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedOption('B'); } }}
                    className={`p-3.5 rounded-xl border cursor-pointer relative transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${
                      selectedOption === 'B'
                        ? 'border-aero-blue bg-blue-50/50 dark:bg-blue-950/20 shadow-sm ring-1 ring-aero-blue'
                        : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30'
                    }`}
                  >
                    <div className="font-mono text-xs font-bold text-slate-900 dark:text-white">
                      OPTION B
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono">Frankfurt Logistics Hub</div>

                    <div className="my-2.5">
                      <div className="text-lg font-display font-bold text-slate-900 dark:text-white">
                        $11,800
                      </div>
                      <div className="text-[10px] font-mono text-slate-500">2 Days • Air Express</div>
                    </div>

                    <div className="space-y-1 text-[10px] font-mono text-slate-600 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-2">
                      <div>Condition: <span className="font-bold text-slate-800 dark:text-slate-200">OH (Overhauled)</span></div>
                      <div>Release: <span className="text-aero-blue font-semibold">EASA Form 1</span></div>
                      <div>Trace: <span className="text-emerald-600 dark:text-emerald-400 font-semibold">OEM Lufthansa</span></div>
                    </div>
                  </div>

                  {/* Option C (DFW Stock) */}
                  <div 
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedOption('C')}
                    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedOption('C'); } }}
                    className={`p-3.5 rounded-xl border cursor-pointer relative transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${
                      selectedOption === 'C'
                        ? 'border-aero-blue bg-blue-50/50 dark:bg-blue-950/20 shadow-sm ring-1 ring-aero-blue'
                        : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30'
                    }`}
                  >
                    <div className="font-mono text-xs font-bold text-slate-900 dark:text-white">
                      OPTION C
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono">Texas Aviation DFW</div>

                    <div className="my-2.5">
                      <div className="text-lg font-display font-bold text-slate-900 dark:text-white">
                        $12,500
                      </div>
                      <div className="text-[10px] font-mono text-slate-500">2 Days • Ground Priority</div>
                    </div>

                    <div className="space-y-1 text-[10px] font-mono text-slate-600 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-2">
                      <div>Condition: <span className="font-bold text-slate-800 dark:text-slate-200">SV (Serviceable)</span></div>
                      <div>Release: <span className="text-emerald-600 dark:text-emerald-400 font-semibold">FAA 8130-3</span></div>
                      <div>Trace: <span className="text-slate-500">FAA 145 Station</span></div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Price Breakdown Summary & 1-Click Action */}
              <div className="bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
                <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 text-xs">
                  <span className="min-w-0 break-words text-slate-500">Selected Option:</span>
                  <span className="whitespace-nowrap text-right font-bold text-slate-900 dark:text-white">
                    Option {selectedOption} ({selectedOption === 'A' ? 'Internal Miami Stock' : selectedOption === 'B' ? 'Frankfurt Hub' : 'Texas Aviation'})
                  </span>
                </div>
                <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 text-xs">
                  <span className="min-w-0 break-words text-slate-500">Unit Base Price:</span>
                  <span className="whitespace-nowrap text-right font-semibold text-slate-900 dark:text-white">
                    ${selectedOption === 'A' ? '14,200.00' : selectedOption === 'B' ? '11,800.00' : '12,500.00'}
                  </span>
                </div>
                <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 text-xs">
                  <span className="min-w-0 break-words text-slate-500">AOG Hot-Shot Logistics:</span>
                  <span className="whitespace-nowrap text-right font-semibold text-slate-900 dark:text-white">$250.00</span>
                </div>
                <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 text-xs">
                  <span className="min-w-0 break-words text-slate-500">FAA 8130-3 Digital Cert Packet:</span>
                  <span className="whitespace-nowrap text-right font-semibold text-emerald-600 dark:text-emerald-400">Included (FREE)</span>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 border-t border-slate-200 pt-2 text-sm font-bold dark:border-slate-700">
                  <span className="min-w-0 break-words text-slate-900 dark:text-white">TOTAL DELIVERED COST:</span>
                  <span className="whitespace-nowrap text-right text-base text-emerald-600 dark:text-emerald-400">
                    ${selectedOption === 'A' ? '14,450.00' : selectedOption === 'B' ? '12,050.00' : '12,750.00'}
                  </span>
                </div>

                <div className="mt-4 flex flex-col sm:flex-row items-center gap-3">
                  <button
                    onClick={() => setIsApproveModalOpen(true)}
                    disabled={loadingRfqs || loadingRfqDetail || Boolean(rfqDetailError) || usingFallbackData || selectedRfqFailed || !liveQuote || Boolean(selectedRfqDetail?.isFallback)}
                    className="w-full sm:flex-1 bg-emerald-700 hover:bg-emerald-600 text-white font-display font-bold py-2.5 px-4 rounded-xl shadow-md shadow-emerald-600/20 flex items-center justify-center space-x-2 transition-all transform active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    <span>APPROVE & DISPATCH QUOTE</span>
                  </button>

                  <button
                    onClick={() => openDocViewer('8130-3-2026-99', selectedRfq.part_number || '32-11-45-01', 'MLG-9840', 'FAA 8130-3 Airworthiness Release', '2026-08-28')}
                    className="w-full sm:w-auto bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 hover:bg-slate-50 text-slate-700 dark:text-slate-200 font-display font-semibold py-2.5 px-4 rounded-xl text-xs flex items-center justify-center space-x-1.5 transition-colors"
                  >
                    <FileText className="w-4 h-4 text-aero-blue" />
                    <span>View Pro-Forma Quote PDF</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: SUBMIT NEW RFQ */}
      {activeTab === 'new-rfq' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column (8 cols): Clean RFQ Intake Form */}
          <div className="lg:col-span-8 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-5">
            <div className="border-b border-slate-100 dark:border-slate-800 pb-3 flex items-center justify-between">
              <div>
                <h2 className="font-display font-bold text-base text-slate-900 dark:text-white flex items-center space-x-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-aero-blue" />
                  <span>REQUEST FOR QUOTATION (RFQ) INTAKE</span>
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  AI-powered instant multi-agent part identification, compliance checking, and live pricing.
                </p>
              </div>

              <span className="text-[11px] font-mono text-aero-blue bg-blue-50 dark:bg-blue-950/40 px-2.5 py-1 rounded-full font-semibold">
                SLA Target: &lt; 15 mins
              </span>
            </div>

            {/* Fast Presets */}
            <div>
              <div className="text-[11px] font-mono font-semibold text-slate-500 uppercase tracking-wider mb-2">
                ⚡ Quick Fleet Presets (Click to autofill):
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                <button
                  type="button"
                  onClick={() => applyPreset('aog-actuator')}
                  className="p-2.5 rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50/50 dark:bg-red-950/20 hover:bg-red-100/60 text-left transition-all"
                >
                  <div className="font-bold text-aog-red font-mono text-[11px]">AOG Actuator</div>
                  <div className="text-[10px] text-slate-500 font-mono">P/N 32-11-45-01 (B737)</div>
                </button>

                <button
                  type="button"
                  onClick={() => applyPreset('routine-overhaul')}
                  className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 hover:bg-slate-100 text-left transition-all"
                >
                  <div className="font-bold text-slate-800 dark:text-slate-200 font-mono text-[11px]">Routine OH</div>
                  <div className="text-[10px] text-slate-500 font-mono">P/N 32-11-45-01 (Qty 2)</div>
                </button>

                <button
                  type="button"
                  onClick={() => applyPreset('hydraulic-pump')}
                  className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 hover:bg-slate-100 text-left transition-all"
                >
                  <div className="font-bold text-slate-800 dark:text-slate-200 font-mono text-[11px]">Hydraulic Pump</div>
                  <div className="text-[10px] text-slate-500 font-mono">P/N 747-1011-00 (B777)</div>
                </button>

                <button
                  type="button"
                  onClick={() => applyPreset('avionics')}
                  className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 hover:bg-slate-100 text-left transition-all"
                >
                  <div className="font-bold text-slate-800 dark:text-slate-200 font-mono text-[11px]">Avionics FMGC</div>
                  <div className="text-[10px] text-slate-500 font-mono">P/N NAV-4402-A (A320)</div>
                </button>
              </div>
            </div>

            {/* Intake Form */}
            <form onSubmit={handleSubmit} className="space-y-4 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Part Number */}
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Aviation Part Number (P/N):
                  </label>
                  <input
                    type="text"
                    required
                    value={partNumber}
                    onChange={(e) => setPartNumber(e.target.value)}
                    placeholder="e.g. 32-11-45-01"
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3.5 py-2 font-mono text-sm text-aero-blue font-bold focus:ring-2 focus:ring-aero-blue/20 focus:border-aero-blue focus:outline-none"
                  />
                </div>

                {/* Part Name */}
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Part Description / Nomenclature:
                  </label>
                  <input
                    type="text"
                    value={partName}
                    onChange={(e) => setPartName(e.target.value)}
                    placeholder="e.g. Main Landing Gear Actuator"
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3.5 py-2 text-slate-800 dark:text-slate-200 focus:ring-2 focus:ring-aero-blue/20 focus:border-aero-blue focus:outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                {/* ATA Chapter */}
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    ATA Chapter:
                  </label>
                  <input
                    type="text"
                    value={ataChapter}
                    onChange={(e) => setAtaChapter(e.target.value)}
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 font-mono text-slate-800 dark:text-slate-200 text-center"
                  />
                </div>

                {/* Quantity */}
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Quantity (Qty):
                  </label>
                  <input
                    type="number"
                    min="1"
                    value={quantity}
                    onChange={(e) => setQuantity(parseInt(e.target.value) || 1)}
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 font-mono text-slate-800 dark:text-slate-200 text-center font-bold"
                  />
                </div>

                {/* Aircraft Type */}
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Aircraft Fleet:
                  </label>
                  <input
                    type="text"
                    value={aircraftType}
                    onChange={(e) => setAircraftType(e.target.value)}
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-800 dark:text-slate-200 font-mono text-[11px]"
                  />
                </div>
              </div>

              {/* Condition & Quality Requirements */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Acceptable Conditions:
                  </label>
                  <div className="flex flex-wrap gap-2 p-2.5 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-200 dark:border-slate-800">
                    {[
                      { key: 'SV', label: 'SV (Serviceable)' },
                      { key: 'OH', label: 'OH (Overhauled)' },
                      { key: 'NEW', label: 'NEW (Factory)' },
                      { key: 'AR', label: 'AR (As Removed)' }
                    ].map(({ key, label }) => (
                      <label key={key} className="flex items-center space-x-1.5 cursor-pointer text-xs font-mono">
                        <input
                          type="checkbox"
                          checked={conditions[key as ConditionKey]}
                          onChange={(e) => setConditions({ ...conditions, [key]: e.target.checked })}
                          className="rounded border-slate-300 text-aero-blue focus:ring-aero-blue"
                        />
                        <span className={conditions[key as ConditionKey] ? 'font-bold text-aero-blue' : 'text-slate-500'}>
                          {label}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Required Compliance Certification:
                  </label>
                  <div className="grid grid-cols-2 gap-2 p-2.5 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-200 dark:border-slate-800 text-[11px] font-mono">
                    <label className="flex items-center space-x-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={documents.faa8130}
                        onChange={(e) => setDocuments({ ...documents, faa8130: e.target.checked })}
                        className="rounded border-slate-300 text-aero-blue"
                      />
                      <span>FAA 8130-3</span>
                    </label>

                    <label className="flex items-center space-x-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={documents.easaForm1}
                        onChange={(e) => setDocuments({ ...documents, easaForm1: e.target.checked })}
                        className="rounded border-slate-300 text-aero-blue"
                      />
                      <span>EASA Form 1</span>
                    </label>

                    <label className="flex items-center space-x-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={documents.trace121}
                        onChange={(e) => setDocuments({ ...documents, trace121: e.target.checked })}
                        className="rounded border-slate-300 text-aero-blue"
                      />
                      <span>121 Operator Trace</span>
                    </label>

                    <label className="flex items-center space-x-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={documents.nonIncident}
                        onChange={(e) => setDocuments({ ...documents, nonIncident: e.target.checked })}
                        className="rounded border-slate-300 text-aero-blue"
                      />
                      <span>Non-Incident Stmt</span>
                    </label>
                  </div>
                </div>
              </div>

              {/* Delivery Location & Urgency */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Delivery Airport (ICAO):
                  </label>
                  <input
                    type="text"
                    value={deliveryIcao}
                    onChange={(e) => setDeliveryIcao(e.target.value)}
                    placeholder="MIA"
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 font-mono text-center font-bold text-slate-800 dark:text-slate-200"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Hangar / Dock Bay:
                  </label>
                  <input
                    type="text"
                    value={dockLocation}
                    onChange={(e) => setDockLocation(e.target.value)}
                    placeholder="Dock A-12"
                    className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 font-mono text-slate-800 dark:text-slate-200 text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Urgency Priority:
                  </label>
                  <select
                    value={urgency}
                    onChange={(e) => setUrgency(e.target.value as 'AOG' | 'Critical' | 'Routine')}
                    className="w-full bg-white dark:bg-slate-900 border border-red-300 dark:border-red-900/60 rounded-xl px-3 py-2 font-mono text-xs font-bold text-aog-red focus:ring-2 focus:ring-red-200 focus:outline-none"
                  >
                    <option value="AOG">🚨 AOG (4h Target SLA)</option>
                    <option value="Critical">Critical (24h SLA)</option>
                    <option value="Routine">Routine (48h Standard)</option>
                  </select>
                </div>
              </div>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={submitting}
                  aria-busy={submitting}
                className="w-full bg-aero-blue hover:bg-blue-600 text-white font-display font-bold py-3 px-6 rounded-xl shadow-lg shadow-aero-blue/20 flex items-center justify-center space-x-2 text-sm transition-all transform active:scale-98"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Sparkles className="w-4 h-4" />}
                <span>{submitting ? 'DISPATCHING TO MULTI-AGENT PIPELINE...' : 'SUBMIT RFQ & GENERATE INSTANT QUOTE'}</span>
              </button>
            </form>
          </div>

          {/* Right Column (4 cols): AI Pipeline Assistant Info */}
          <div className="lg:col-span-4 space-y-4">
            <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
              <div className="flex items-center space-x-2 border-b border-slate-100 dark:border-slate-800 pb-3">
                <ShieldCheck className="w-5 h-5 text-emerald-500" />
                <div>
                  <h3 className="font-display font-bold text-xs text-slate-900 dark:text-white uppercase">
                    Automated Agent Pipeline
                  </h3>
                  <p className="text-[10px] text-slate-500">Autonomous MRO Fulfillment Engine</p>
                </div>
              </div>

              <div className="space-y-3 font-mono text-[11px]">
                <div className="flex items-start space-x-2.5">
                  <div className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-950 text-aero-blue flex items-center justify-center text-[10px] font-bold shrink-0">1</div>
                  <div>
                    <span className="font-bold text-slate-800 dark:text-slate-200">{getAgentIdentity('PartsIntelligenceAgent').name} · {getAgentIdentity('PartsIntelligenceAgent').role}</span>
                    <p className="text-slate-500 text-[10px]">Validates ATA chapters, IPC superseded part numbers, and OEM compatibility.</p>
                  </div>
                </div>

                <div className="flex items-start space-x-2.5">
                  <div className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-950 text-aero-blue flex items-center justify-center text-[10px] font-bold shrink-0">2</div>
                  <div>
                    <span className="font-bold text-slate-800 dark:text-slate-200">{getAgentIdentity('ComplianceAgent').name} · {getAgentIdentity('ComplianceAgent').role}</span>
                    <p className="text-slate-500 text-[10px]">Scans FAA 8130-3 release tags, 121 air carrier pedigree, and non-incident statements.</p>
                  </div>
                </div>

                <div className="flex items-start space-x-2.5">
                  <div className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-950 text-aero-blue flex items-center justify-center text-[10px] font-bold shrink-0">3</div>
                  <div>
                    <span className="font-bold text-slate-800 dark:text-slate-200">{getAgentIdentity('DynamicPricingAgent').name} · {getAgentIdentity('DynamicPricingAgent').role}</span>
                    <p className="text-slate-500 text-[10px]">Calculates wholesale margin, core charges, and hot-shot freight premiums.</p>
                  </div>
                </div>
              </div>

              <div className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900/60 p-3 rounded-xl text-[11px] text-blue-900 dark:text-blue-300 space-y-1">
                <div className="font-bold flex items-center space-x-1">
                  <Info className="w-3.5 h-3.5 text-aero-blue" />
                  <span>Human-in-the-Loop Safeguard</span>
                </div>
                <p className="text-[10px] leading-relaxed">
                  Every quotation is pre-audited and ready for your immediate digital sign-off or operator review before any billing or dispatch.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: LIVE TELEMETRY & TRACKING */}
      {activeTab === 'tracking' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-8">
              <WorldMapTelemetry 
                title="GLOBAL SHIPMENT ROUTE DEMO"
                subtitle="Example routes for MRO parts. Carrier locations are not live."
                orderId="WT-29471" 
              />
            </div>

            <div className="lg:col-span-4 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3 mb-3">
                  <h3 className="font-display font-bold text-sm text-slate-900 dark:text-white">
                    DEMO FLIGHT STATUS
                  </h3>
                  <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
                </div>

                <div className="space-y-3 font-mono text-xs">
                  <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                    <div className="text-[10px] text-slate-500">CARRIER / FLIGHT</div>
                    <div className="font-bold text-slate-900 dark:text-white flex items-center space-x-2">
                      <Plane className="w-4 h-4 text-aero-blue" />
                      <span>FEDEX AVIATION #FDX-8821</span>
                    </div>
                    <div className="text-[11px] text-slate-600 dark:text-slate-400">
                      Airbus A300-600F • Tail: N718FA
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div className="bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800">
                      <div className="text-[10px] text-slate-500">ORIGIN</div>
                      <div className="font-bold text-slate-900 dark:text-white">MIA (Miami, FL)</div>
                      <div className="text-[10px] text-emerald-600 font-semibold">Departed 08:45 EDT</div>
                    </div>
                    <div className="bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800">
                      <div className="text-[10px] text-slate-500">DESTINATION</div>
                      <div className="font-bold text-slate-900 dark:text-white">DFW (Dallas, TX)</div>
                      <div className="text-[10px] text-aero-blue font-semibold">ETA: 11:20 CDT</div>
                    </div>
                  </div>

                  <div className="p-3 bg-blue-50/60 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-900 rounded-xl space-y-1">
                    <div className="text-[10px] font-bold text-aero-blue">HOT-SHOT COURIER DISPATCH</div>
                    <div className="text-[11px] text-slate-700 dark:text-slate-300">
                      Direct tarmac transfer arranged to <span className="font-bold">Hangar Bay 4</span> upon touchdown.
                    </div>
                  </div>
                </div>
              </div>

              <div className="pt-3 border-t border-slate-100 dark:border-slate-800">
                <button type="button" onClick={() => window.open('https://www.flightaware.com/', '_blank', 'noopener,noreferrer')} className="w-full bg-slate-900 dark:bg-white text-white dark:text-slate-900 font-display font-bold py-2 rounded-xl text-xs flex items-center justify-center space-x-1.5 hover:opacity-90 transition-opacity">
                  <ExternalLink className="w-3.5 h-3.5" />
                  <span>Open Carrier Live Radar (FlightAware)</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: AIRWORTHINESS TRACE VAULT */}
      {activeTab === 'trace-vault' && (
        <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
            <div>
              <h2 className="font-display font-bold text-base text-slate-900 dark:text-white flex items-center space-x-2">
                <ShieldCheck className="w-5 h-5 text-emerald-500" />
                <span>CUSTOMER AIRWORTHINESS & TRACE VAULT</span>
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Digital back-to-birth documentation, FAA 8130-3 release forms, and EASA Form 1 certificates.
              </p>
            </div>

            <div className="flex items-center space-x-2">
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Filter by P/N, S/N, Tag..."
                  className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl pl-8 pr-3 py-1.5 text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:border-aero-blue"
                />
              </div>
            </div>
          </div>

          {/* Trace Document Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-[11px]">
                  <th className="pb-3">Certificate Type</th>
                  <th className="pb-3">Part Number (P/N)</th>
                  <th className="pb-3">Serial Number (S/N)</th>
                  <th className="pb-3">Airworthiness Authority</th>
                  <th className="pb-3">Release Date</th>
                  <th className="pb-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {[
                  { tag: '8130-3-2026-9941', pn: '32-11-45-01', sn: 'MLG-9840', cert: 'FAA 8130-3 (Airworthiness Release)', auth: 'FAA (US)', date: '2026-08-28', status: 'VERIFIED' },
                  { tag: 'EASA-F1-8812', pn: '32-11-45-01', sn: 'MLG-9841', cert: 'EASA Form 1 (Authorized Release)', auth: 'EASA (EU)', date: '2026-08-15', status: 'VERIFIED' },
                  { tag: '8130-3-2026-7471', pn: '747-1011-00', sn: 'HYD-3301', cert: 'FAA 8130-3 Dual Release', auth: 'FAA / EASA', date: '2026-07-20', status: 'VERIFIED' },
                  { tag: 'TRC-121-GLOBAL', pn: '68-99-12-04', sn: 'BRK-7719', cert: '121 Airline Trace Pedigree Record', auth: 'Delta MRO Records', date: '2026-06-11', status: 'VERIFIED' }
                ].map((doc, idx) => (
                  <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300">
                    <td className="py-3.5 font-bold text-slate-900 dark:text-white flex items-center space-x-2">
                      <FileCheck className="w-4 h-4 text-emerald-500 shrink-0" />
                      <span>{doc.cert}</span>
                    </td>
                    <td className="py-3.5 font-bold text-aero-blue">{doc.pn}</td>
                    <td className="py-3.5 text-slate-600 dark:text-slate-400">{doc.sn}</td>
                    <td className="py-3.5">
                      <span className="bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-[10px] font-semibold text-slate-700 dark:text-slate-300">
                        {doc.auth}
                      </span>
                    </td>
                    <td className="py-3.5 text-slate-500">{doc.date}</td>
                    <td className="py-3.5 text-right space-x-2">
                      <button 
                        onClick={() => openDocViewer(doc.tag, doc.pn, doc.sn, doc.cert, doc.date)}
                        className="bg-blue-50 dark:bg-blue-950/40 hover:bg-blue-100 text-aero-blue px-2.5 py-1 rounded-lg border border-blue-200 dark:border-blue-900 text-[11px] font-semibold transition-colors"
                      >
                        View Tag
                      </button>
                      <button 
                        onClick={() => {
                          setNotification({ type: 'info', message: `Downloaded ${doc.tag}.pdf to your local browser vault.` });
                          setTimeout(() => setNotification(null), 5000);
                        }}
                        className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-600 dark:text-slate-300 p-1.5 rounded-lg border border-slate-200 dark:border-slate-700 inline-flex items-center transition-colors"
                      >
                        <Download className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 5: SPEND & FLEET ANALYTICS */}
      {activeTab === 'analytics' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
            <h3 className="font-display font-bold text-xs uppercase text-slate-900 dark:text-white">
              FLEET SPEND DISTRIBUTION (YTD)
            </h3>
            <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
            <div className="space-y-2 font-mono text-xs">
              <div className="flex justify-between items-center text-slate-600 dark:text-slate-400">
                <span>Boeing 737 Fleet</span>
                <span className="font-bold text-slate-900 dark:text-white">$342,000 (58%)</span>
              </div>
              <div className="w-full bg-slate-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-aero-blue h-full w-[58%]" />
              </div>

              <div className="flex justify-between items-center text-slate-600 dark:text-slate-400 pt-2">
                <span>Airbus A320 Fleet</span>
                <span className="font-bold text-slate-900 dark:text-white">$164,500 (28%)</span>
              </div>
              <div className="w-full bg-slate-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-emerald-500 h-full w-[28%]" />
              </div>

              <div className="flex justify-between items-center text-slate-600 dark:text-slate-400 pt-2">
                <span>Boeing 777 Widebody</span>
                <span className="font-bold text-slate-900 dark:text-white">$82,300 (14%)</span>
              </div>
              <div className="w-full bg-slate-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-amber-500 h-full w-[14%]" />
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
            <h3 className="font-display font-bold text-xs uppercase text-slate-900 dark:text-white">
              SLA & FULFILLMENT METRICS
            </h3>
            <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
            <div className="space-y-3 font-mono text-xs">
              <div className="p-3 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between">
                <div>
                  <div className="text-[10px] text-slate-500">AVERAGE QUOTE TIME</div>
                  <div className="text-base font-bold text-emerald-600">14.2 Minutes</div>
                </div>
                <Clock className="w-5 h-5 text-emerald-500" />
              </div>

              <div className="p-3 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between">
                <div>
                  <div className="text-[10px] text-slate-500">ON-TIME HOT-SHOT DISPATCH</div>
                  <div className="text-base font-bold text-aero-blue">99.4% SLA Pass</div>
                </div>
                <Award className="w-5 h-5 text-aero-blue" />
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
            <h3 className="font-display font-bold text-xs uppercase text-slate-900 dark:text-white">
              ESTIMATED ANNUAL SAVINGS
            </h3>
            <Badge variant="outline">SAMPLE / DEMO DATA</Badge>
            <div className="p-4 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-xl text-center space-y-1">
              <div className="text-[11px] font-mono text-emerald-700 dark:text-emerald-400 font-semibold">AI SOURCING EFFICIENCY</div>
              <div className="text-2xl font-display font-bold text-emerald-600 dark:text-emerald-300">$64,800 saved</div>
              <div className="text-[10px] text-emerald-800/80 dark:text-emerald-400 font-mono">Vs. Broker Spot Rate Averages</div>
            </div>
          </div>
        </div>
      )}

      {/* 5. MODALS */}

      {/* APPROVE QUOTE MODAL */}
      {isApproveModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-700 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-5 animate-fade-in">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                <h3 className="font-display font-bold text-base text-slate-900 dark:text-white">
                  Confirm Quote Approval and Dispatch
                </h3>
              </div>
              <button 
                onClick={() => setIsApproveModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs font-mono">
              <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-slate-500">RFQ ID:</span>
                  <span className="font-bold text-slate-900 dark:text-white">{selectedRfq.id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Part Number:</span>
                  <span className="font-bold text-aero-blue">{selectedRfq.part_number || '32-11-45-01'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Quote ID:</span>
                  <span className="font-bold text-slate-900 dark:text-white">{liveQuote?.id || 'Unavailable'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Quote Total:</span>
                  <span className="font-bold text-emerald-600 text-sm">{liveQuote ? `$${liveQuote.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : 'Unavailable'}</span>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-slate-700 dark:text-slate-300">
                  Authorized Approver / License:
                </label>
                <input
                  type="text"
                  value={approverName}
                  disabled={approving}
                  onChange={(e) => setApproverName(e.target.value)}
                  className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-900 dark:text-white"
                />
              </div>
            </div>

            <div className="flex space-x-3 pt-2">
              <button
                onClick={() => setIsApproveModalOpen(false)}
                disabled={approving}
                className="flex-1 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-300 font-display font-semibold py-2.5 rounded-xl text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleApproveQuote}
                disabled={approving}
                aria-busy={approving}
                className="flex-1 bg-emerald-700 hover:bg-emerald-600 text-white font-display font-bold py-2.5 rounded-xl text-xs shadow-lg shadow-emerald-600/20"
              >
                {approving && <Loader2 className="mr-2 inline h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                {approving ? 'DISPATCHING...' : 'CONFIRM & DISPATCH QUOTE'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DOCUMENT PREVIEW MODAL */}
      {isDocModalOpen && selectedDoc && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-700 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 animate-fade-in">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <div className="flex items-center space-x-2">
                <ShieldCheck className="w-5 h-5 text-emerald-500" />
                <h3 className="font-display font-bold text-sm text-slate-900 dark:text-white">
                  {selectedDoc.cert}
                </h3>
              </div>
              <button 
                onClick={() => setIsDocModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Official FAA 8130-3 Style Document Canvas */}
            <div className="bg-slate-50 dark:bg-slate-900 border-2 border-slate-300 dark:border-slate-700 p-4 rounded-xl font-mono text-[11px] text-slate-800 dark:text-slate-200 space-y-3">
              <div className="flex justify-between border-b border-slate-300 dark:border-slate-700 pb-2 text-[10px]">
                <div>
                  <div className="font-bold">1. Approving National Aviation Authority:</div>
                  <div className="text-aero-blue font-bold">FEDERAL AVIATION ADMINISTRATION (FAA)</div>
                </div>
                <div className="text-right">
                  <div className="font-bold">2. AUTHORIZED RELEASE CERTIFICATE</div>
                  <div className="font-bold text-emerald-600">FAA Form 8130-3, AIRWORTHINESS APPROVAL TAG</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 border-b border-slate-300 dark:border-slate-700 pb-2">
                <div>
                  <span className="text-slate-500">3. Form Tracking #:</span> <span className="font-bold">{selectedDoc.tag}</span>
                </div>
                <div>
                  <span className="text-slate-500">4. Organization:</span> <span className="font-bold">FAA CRS #WT-942-CRS</span>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 border-b border-slate-300 dark:border-slate-700 pb-2">
                <div>
                  <span className="text-slate-500">6. Item Description:</span>
                  <div className="font-bold">Main Landing Gear Actuator</div>
                </div>
                <div>
                  <span className="text-slate-500">7. Part Number:</span>
                  <div className="font-bold text-aero-blue">{selectedDoc.pn}</div>
                </div>
                <div>
                  <span className="text-slate-500">9. Serial Number:</span>
                  <div className="font-bold">{selectedDoc.sn}</div>
                </div>
              </div>

              <div className="bg-emerald-50 dark:bg-emerald-950/30 p-2.5 rounded border border-emerald-200 dark:border-emerald-800 text-[10px] space-y-1 text-emerald-900 dark:text-emerald-300">
                <div className="font-bold">14a. 14 CFR 43.9 Return to Service Certification:</div>
                <p>
                  Certifies that the work specified in Block 12 was carried out in accordance with current maintenance regulations under 14 CFR Part 43 and in respect to that work the items are approved for return to service.
                </p>
                <div className="flex justify-between pt-1 font-mono font-bold">
                  <span>Authorized Signature: Marcus Vance (Q.A. Director)</span>
                  <span>Date: {selectedDoc.date}</span>
                </div>
              </div>
            </div>

            <div className="flex justify-end space-x-3 pt-2">
              <button
                onClick={() => setIsDocModalOpen(false)}
                className="bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-4 py-2 rounded-xl text-xs font-semibold"
              >
                Close
              </button>
              <button
                onClick={() => {
                  setIsDocModalOpen(false);
                  setNotification({ type: 'info', message: `Downloaded ${selectedDoc.tag}.pdf certificate.` });
                  setTimeout(() => setNotification(null), 5000);
                }}
                className="bg-aero-blue hover:bg-blue-600 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center space-x-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download Official Certificate</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
