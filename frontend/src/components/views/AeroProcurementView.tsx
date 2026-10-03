import React, { useEffect, useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { apiService, getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { InternalCommand, InventoryItem, RFQ, Supplier, SupplierQuote } from '../../types';
import type { FreightQuoteBody, FreightQuoteResponse, MailboxMessageSummary } from '../../types/api';
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
  RotateCcw,
} from 'lucide-react';
import { FallbackDataBanner } from '../common/FallbackDataBanner';
import { isFailedRfq, rfqStatusLabel } from '../../utils/rfqState';
import { describeRfqProcessingResult, type RfqProcessingNotice } from '../../utils/rfqProcessingResult';
import { useExecuteInternalCommand, useFreightQuote, useInventoryDirectory, useMailboxInbox, useProcessRFQ, useResetFailedIntake, useRFQs, useSendMailboxMessage, useSetAutomationPause, useSupplierDirectory, useSupplierOffers, useSupplierProfile } from '../../hooks/useApiResources';

export const AeroProcurementView: React.FC = () => {
  const [activeMailbox, setActiveMailbox] = useState<'sales' | 'purchasing'>(() => apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES']) ? 'sales' : 'purchasing');
  const [selectedMailboxMessageId, setSelectedMailboxMessageId] = useState('');
  const [mailboxRecipient, setMailboxRecipient] = useState('');
  const [mailboxSubject, setMailboxSubject] = useState('');
  const [mailboxBody, setMailboxBody] = useState('');
  const [mailboxReplyTo, setMailboxReplyTo] = useState('');
  const [mailboxNotice, setMailboxNotice] = useState<string | null>(null);
  const [mailboxNoticeType, setMailboxNoticeType] = useState<'success' | 'error'>('success');
  const [catalogTab, setCatalogTab] = useState<'inventory' | 'suppliers'>('inventory');
  const [selectedOfferId, setSelectedOfferId] = useState('');
  const [selectedRfqId, setSelectedRfqId] = useState('');
  const [selectedSupplierId, setSelectedSupplierId] = useState('');
  const [automationReason, setAutomationReason] = useState('');
  const [intakeResetReason, setIntakeResetReason] = useState('');
  const [freightOrigin, setFreightOrigin] = useState('');
  const [freightDestination, setFreightDestination] = useState('');
  const [freightWeightKg, setFreightWeightKg] = useState('');
  const [freightPackages, setFreightPackages] = useState('1');
  const [freightServiceLevel, setFreightServiceLevel] = useState('standard');
  const [freightResult, setFreightResult] = useState<FreightQuoteResponse | null>(null);
  const [freightError, setFreightError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [commandPending, setCommandPending] = useState<InternalCommand | null>(null);
  const [noticeType, setNoticeType] = useState<RfqProcessingNotice['type']>('info');
  const rfqQuery = useRFQs();
  const rfqs = rfqQuery.data || [];
  const loading = rfqQuery.isLoading;
  const loadError = rfqQuery.error?.message || null;
  const usingFallbackData = rfqQuery.isSampleData;
  const canViewInternalCatalog = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING']);
  const canAccessSalesMailbox = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES']);
  const canAccessPurchasingMailbox = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING']);
  const canAccessActiveMailbox = activeMailbox === 'sales' ? canAccessSalesMailbox : canAccessPurchasingMailbox;
  const inventoryQuery = useInventoryDirectory(canViewInternalCatalog);
  const supplierDirectoryQuery = useSupplierDirectory(canViewInternalCatalog);
  const supplierProfileQuery = useSupplierProfile(selectedSupplierId);
  const mailboxInboxQuery = useMailboxInbox(activeMailbox, canAccessActiveMailbox);
  const mailboxSendMutation = useSendMailboxMessage();
  const inventory = inventoryQuery.data || [];
  const suppliers = supplierDirectoryQuery.data || [];
  const mailboxMessages = mailboxInboxQuery.data?.messages || [];
  const selectedMailboxMessage: MailboxMessageSummary | undefined = mailboxMessages.find(message => message.message_id === selectedMailboxMessageId);
  const commandMutation = useExecuteInternalCommand();
  const processMutation = useProcessRFQ();
  const intakeResetMutation = useResetFailedIntake();
  const automationMutation = useSetAutomationPause();
  const freightQuoteMutation = useFreightQuote();
  const selectedRfq = rfqs.find(rfq => rfq.id === selectedRfqId);
  const selectedPartNumber = selectedRfq?.part_number?.trim() || '';
  const actionsBlocked = loading || Boolean(loadError) || usingFallbackData || !selectedRfq || isFailedRfq(selectedRfq);
  const canProcessSelectedRfq = selectedRfq?.status === 'Intake'
    && !loading
    && !loadError
    && !usingFallbackData
    && apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING']);
  const canResetFailedIntake = selectedRfq?.status === 'Intake_Failed'
    && !loading
    && !loadError
    && !usingFallbackData
    && apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER']);
  const canManageAutomation = Boolean(selectedRfq)
    && !loading
    && !loadError
    && !usingFallbackData
    && apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER']);
  const canQuoteFreight = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_SALES']);
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
    if (mailboxMessages.length > 0 && !mailboxMessages.some(message => message.message_id === selectedMailboxMessageId)) {
      setSelectedMailboxMessageId(mailboxMessages[0].message_id);
    } else if (mailboxMessages.length === 0) {
      setSelectedMailboxMessageId('');
    }
  }, [activeMailbox, mailboxMessages, selectedMailboxMessageId]);

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
      const notice = describeRfqProcessingResult(selectedRfq.id, result);
      setNoticeType(notice.type);
      setNotice(notice.message);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, 'Unable to process this RFQ.'));
    }
  };

  const resetSelectedFailedIntake = async () => {
    if (!selectedRfq || !canResetFailedIntake || intakeResetMutation.isPending) return;
    const reason = intakeResetReason.trim();
    if (!reason || !window.confirm(`Reset failed intake for RFQ ${selectedRfq.id}? Processing remains a separate action.`)) return;
    setNotice(null);
    try {
      const result = await intakeResetMutation.mutateAsync({ rfqId: selectedRfq.id, body: { reason } });
      if (!result) return;
      setIntakeResetReason('');
      setNoticeType('success');
      setNotice('RFQ reset to Intake. Select Process RFQ to continue.');
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, 'Unable to reset this failed intake.'));
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

  const requestFreightQuote = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canQuoteFreight || freightQuoteMutation.isPending) return;
    const request: FreightQuoteBody = {
      origin: freightOrigin.trim(),
      destination: freightDestination.trim(),
      weight_kg: Number(freightWeightKg),
      packages: Number(freightPackages),
      service_level: freightServiceLevel,
    };
    if (!request.origin || !request.destination || !Number.isFinite(request.weight_kg) || request.weight_kg <= 0 || !Number.isInteger(request.packages) || request.packages < 1) return;
    setFreightError(null);
    setFreightResult(null);
    try {
      const result = await freightQuoteMutation.mutateAsync(request);
      if (result) setFreightResult(result);
    } catch (error) {
      setFreightError(getApiErrorMessage(error, 'Unable to request freight rates.'));
    }
  };

  const sendMailboxMessage = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const recipient = mailboxRecipient.trim();
    const subject = mailboxSubject.trim();
    const body = mailboxBody.trim();
    if (!canAccessActiveMailbox || !recipient || !subject || !body || mailboxSendMutation.isPending) return;
    if (!window.confirm(`Send this message from the ${activeMailbox} mailbox to ${recipient}?`)) return;
    setMailboxNotice(null);
    try {
      const result = await mailboxSendMutation.mutateAsync({
        mailbox: activeMailbox,
        message: { recipient, subject, body, reply_to: mailboxReplyTo.trim() || undefined },
      });
      if (!result) return;
      setMailboxNotice(`Message sent from the ${activeMailbox} mailbox.`);
      setMailboxNoticeType('success');
      setMailboxSubject('');
      setMailboxBody('');
      setMailboxReplyTo('');
    } catch (error) {
      setMailboxNotice(getApiErrorMessage(error, `Unable to send from the ${activeMailbox} mailbox.`));
      setMailboxNoticeType('error');
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
            <button type="button" disabled={automationMutation.isPending || (!automationPaused && !automationReason.trim())} aria-busy={automationMutation.isPending} onClick={() => void toggleAutomationPause()} className={`inline-flex min-h-11 items-center gap-1.5 rounded-md px-3 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50 ${automationPaused ? 'bg-emerald-700 text-white hover:bg-emerald-600' : 'bg-amber-600 text-white hover:bg-amber-500'}`}>
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
          {isFailedRfq(selectedRfq) && <div role="alert" className="space-y-2 rounded-xl border border-red-300 bg-red-50 p-3 text-xs font-semibold text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300">
            <p>{selectedRfq?.status.trim().toUpperCase() === 'NEEDS_HUMAN_REVIEW' ? 'Operator review required. Complete the review before processing.' : 'Intake failed. An authorized admin or manager must reset it here before processing.'} Sourcing and order actions are disabled.</p>
            {canResetFailedIntake && <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-[220px] flex-1 space-y-1">
                <span>Reason for intake reset</span>
                <input aria-label="Reason for intake reset" value={intakeResetReason} onChange={event => setIntakeResetReason(event.target.value)} maxLength={1000} className="w-full rounded-md border border-red-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 dark:border-red-500/40 dark:bg-slate-950 dark:text-slate-100" />
              </label>
              <button type="button" disabled={!intakeResetReason.trim() || intakeResetMutation.isPending} aria-busy={intakeResetMutation.isPending} onClick={() => void resetSelectedFailedIntake()} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg bg-red-700 px-3 font-bold text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50">
                {intakeResetMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />}
                <span>{intakeResetMutation.isPending ? 'RESETTING...' : 'RESET INTAKE'}</span>
              </button>
            </div>}
          </div>}
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
            </div>
            <p role="status" className="text-xs text-slate-600 dark:text-slate-300">Live certificate verification records are not available from the current API.</p>
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

      {canQuoteFreight && <section aria-labelledby="freight-quote-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="freight-quote-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">FREIGHT RATE QUOTE</h2>
          <p className="text-[11px] text-slate-500">Rate inquiry only. No shipment is booked and no customer quote is changed.</p>
        </div>
        <form onSubmit={event => void requestFreightQuote(event)} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Origin</span><input aria-label="Freight origin" value={freightOrigin} onChange={event => setFreightOrigin(event.target.value)} required maxLength={120} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Destination</span><input aria-label="Freight destination" value={freightDestination} onChange={event => setFreightDestination(event.target.value)} required maxLength={120} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Weight (kg)</span><input aria-label="Freight weight (kg)" type="number" value={freightWeightKg} onChange={event => setFreightWeightKg(event.target.value)} min="0.01" step="0.01" required className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Packages</span><input aria-label="Package count" type="number" value={freightPackages} onChange={event => setFreightPackages(event.target.value)} min="1" step="1" required className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Service level</span><select aria-label="Service level" value={freightServiceLevel} onChange={event => setFreightServiceLevel(event.target.value)} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"><option value="standard">Standard</option><option value="express">Express</option><option value="overnight">Overnight</option></select></label>
          <button type="submit" disabled={freightQuoteMutation.isPending || !freightOrigin.trim() || !freightDestination.trim() || !freightWeightKg || Number(freightWeightKg) <= 0 || !Number.isInteger(Number(freightPackages)) || Number(freightPackages) < 1} aria-busy={freightQuoteMutation.isPending} className="inline-flex min-h-11 items-center justify-center gap-1.5 self-end rounded-md bg-aero-blue px-3 text-xs font-bold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50">
            {freightQuoteMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            <span>{freightQuoteMutation.isPending ? 'REQUESTING...' : 'GET FREIGHT QUOTE'}</span>
          </button>
        </form>
        {freightError && <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200">{freightError}</div>}
        {freightResult && <div role="status" aria-live="polite" className={`space-y-2 rounded-md border p-3 text-xs ${freightResult.status === 'DRY_RUN' ? 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200' : 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200'}`}>
          <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{freightResult.status}</Badge><span>Provider: {freightResult.provider}</span></div>
          {freightResult.message && <p>{freightResult.message}</p>}
          {freightResult.rates.length === 0 && <p>{freightResult.status === 'DRY_RUN' ? 'No live rates returned.' : 'The provider returned no rates for this request.'}</p>}
          {freightResult.rates.length > 0 && <div className="overflow-x-auto"><table className="w-full min-w-[420px] text-left"><thead><tr><th className="py-1 pr-3">Service</th><th className="py-1 pr-3">Carrier</th><th className="py-1 pr-3 text-right">Rate</th><th className="py-1 text-right">Estimated days</th></tr></thead><tbody>{freightResult.rates.map((rate, index) => <tr key={`${rate.service}-${rate.carrier || 'carrier'}-${index}`} className="border-t border-current/20"><td className="py-1 pr-3">{rate.service}</td><td className="py-1 pr-3">{rate.carrier || 'Not provided'}</td><td className="py-1 pr-3 text-right">{rate.currency} {rate.amount.toLocaleString()}</td><td className="py-1 text-right">{rate.estimated_days ?? 'Not provided'}</td></tr>)}</tbody></table></div>}
        </div>}
      </section>}

      {canViewInternalCatalog && <section aria-labelledby="inventory-supplier-directory-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="inventory-supplier-directory-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">INVENTORY & SUPPLIER DIRECTORY</h2>
          <div role="tablist" aria-label="Internal catalog views" className="inline-flex border border-slate-300 dark:border-slate-700">
            <button type="button" role="tab" aria-selected={catalogTab === 'inventory'} onClick={() => setCatalogTab('inventory')} className={`min-h-11 px-3 text-xs font-semibold ${catalogTab === 'inventory' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>Inventory</button>
            <button type="button" role="tab" aria-selected={catalogTab === 'suppliers'} onClick={() => setCatalogTab('suppliers')} className={`min-h-11 px-3 text-xs font-semibold ${catalogTab === 'suppliers' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>Suppliers</button>
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

      {(canAccessSalesMailbox || canAccessPurchasingMailbox) && <section aria-labelledby="mailbox-operations-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h2 id="mailbox-operations-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">MAILBOX OPERATIONS</h2><p className="mt-1 text-[11px] text-slate-500">Messages are sent from the selected shared mailbox after confirmation.</p></div>
          <div role="tablist" aria-label="Mailbox selection" className="inline-flex border border-slate-300 dark:border-slate-700">
            {canAccessSalesMailbox && <button type="button" role="tab" aria-selected={activeMailbox === 'sales'} aria-label="Sales mailbox" onClick={() => { setActiveMailbox('sales'); setMailboxNotice(null); }} className={`min-h-11 px-3 text-xs font-semibold ${activeMailbox === 'sales' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>Sales</button>}
            {canAccessPurchasingMailbox && <button type="button" role="tab" aria-selected={activeMailbox === 'purchasing'} aria-label="Purchasing mailbox" onClick={() => { setActiveMailbox('purchasing'); setMailboxNotice(null); }} className={`min-h-11 px-3 text-xs font-semibold ${activeMailbox === 'purchasing' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>Purchasing</button>}
          </div>
        </div>
        {mailboxNotice && <div role={mailboxNoticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-md border p-3 text-xs ${mailboxNoticeType === 'error' ? 'border-red-300 bg-red-50 text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200' : 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200'}`}>{mailboxNotice}</div>}
        {mailboxInboxQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{mailboxInboxQuery.error.message}</span><button type="button" onClick={() => void mailboxInboxQuery.refetch()} className="font-bold underline">Retry inbox</button></div>}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.4fr)_minmax(280px,1fr)]">
          <div className="space-y-1" aria-label={`${activeMailbox} inbox`}>
            <div className="mb-2 flex items-center justify-between gap-2"><h3 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Recent messages</h3><button type="button" aria-label={`Refresh ${activeMailbox} inbox`} onClick={() => void mailboxInboxQuery.refetch()} className="text-[10px] font-semibold text-aero-blue underline">Refresh</button></div>
            {mailboxInboxQuery.isLoading && <p role="status" className="py-3 text-xs text-slate-500">Loading inbox...</p>}
            {!mailboxInboxQuery.isLoading && !mailboxInboxQuery.error && mailboxMessages.length === 0 && <p role="status" className="py-3 text-xs text-slate-500">No messages returned for this mailbox.</p>}
            {mailboxMessages.map(message => <button key={message.message_id} type="button" aria-pressed={selectedMailboxMessageId === message.message_id} onClick={() => setSelectedMailboxMessageId(message.message_id)} className={`w-full rounded-md border px-3 py-2.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${selectedMailboxMessageId === message.message_id ? 'border-aero-blue bg-blue-50 dark:bg-aero-blue/10' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900'}`}>
              <span className="block truncate text-xs font-bold text-slate-900 dark:text-slate-100">{message.subject || '(No subject)'}</span><span className="mt-1 block truncate text-[11px] text-slate-600 dark:text-slate-400">{message.from}</span><span className="mt-1 block text-[10px] text-slate-500">{message.date}</span>
            </button>)}
          </div>
          <div className="min-w-0 border-l border-slate-200 pl-4 dark:border-slate-800">
            {selectedMailboxMessage ? <div className="space-y-2">
              <h3 className="break-words text-sm font-bold text-slate-900 dark:text-slate-100">{selectedMailboxMessage.subject || '(No subject)'}</h3><p className="break-words text-[11px] text-slate-500">From: {selectedMailboxMessage.from}</p><p className="text-[11px] text-slate-500">Received: {selectedMailboxMessage.date}</p>
              {selectedMailboxMessage.body && <p className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-y border-slate-200 py-3 text-xs text-slate-800 dark:border-slate-800 dark:text-slate-200">{selectedMailboxMessage.body}</p>}
              {(selectedMailboxMessage.attachments || []).length > 0 && <ul aria-label="Attachment names" className="space-y-1 text-[11px] text-slate-600 dark:text-slate-400">{selectedMailboxMessage.attachments?.map((attachment, index) => <li key={`${attachment.filename}-${index}`}>{attachment.filename} · {attachment.content_type}</li>)}</ul>}
            </div> : <p role="status" className="py-4 text-xs text-slate-500">Select a message to preview its text.</p>}
          </div>
          <form onSubmit={event => void sendMailboxMessage(event)} className="space-y-2 border-l border-slate-200 pl-4 dark:border-slate-800">
            <h3 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">New message</h3>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Recipient</span><input aria-label="Mailbox recipient" type="email" value={mailboxRecipient} onChange={event => setMailboxRecipient(event.target.value)} required maxLength={254} disabled={mailboxSendMutation.isPending} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Subject</span><input aria-label="Mailbox subject" value={mailboxSubject} onChange={event => setMailboxSubject(event.target.value)} required maxLength={200} disabled={mailboxSendMutation.isPending} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Reply-to message ID (optional)</span><input aria-label="Mailbox reply-to" value={mailboxReplyTo} onChange={event => setMailboxReplyTo(event.target.value)} maxLength={500} disabled={mailboxSendMutation.isPending} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Message</span><textarea aria-label="Mailbox message" value={mailboxBody} onChange={event => setMailboxBody(event.target.value)} rows={4} maxLength={10000} required disabled={mailboxSendMutation.isPending} className="w-full resize-y rounded-md border border-slate-300 bg-white p-2 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <button type="submit" disabled={mailboxSendMutation.isPending || !mailboxRecipient.trim() || !mailboxSubject.trim() || !mailboxBody.trim()} aria-busy={mailboxSendMutation.isPending} className="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-md bg-aero-blue px-3 text-xs font-bold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50">{mailboxSendMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}<span>{mailboxSendMutation.isPending ? 'SENDING...' : 'SEND MESSAGE'}</span></button>
          </form>
        </div>
      </section>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div role="status" className="flex min-h-32 items-center border border-slate-200 bg-white p-5 text-sm text-slate-600 dark:border-slate-800 dark:bg-card-dark dark:text-slate-300">
          Live AOG workload and lead-time analytics are unavailable because no reporting API is connected.
        </div>
        <WorldMapTelemetry />
      </div>
    </div>
  );
};
