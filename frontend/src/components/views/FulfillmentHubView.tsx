import React, { useState } from 'react';
import { useEffect } from 'react';
import { apiService, getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { InternalCommand } from '../../types';
import { useAddShipmentEvent, useCreateShipment, useExecuteInternalCommand, useFulfillmentStages, useRFQs, useRefreshCarrierTracking, useRegisterCarrierTracking, useSendShipmentSms } from '../../hooks/useApiResources';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import type { CreateShipmentBody } from '../../types/api';
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
  const canManageShipments = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING']);
  const canSendShipmentSms = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_SALES']);
  const shipmentsQuery = useFulfillmentStages(canManageShipments);
  const rfqQuery = useRFQs();
  const stages = shipmentsQuery.data || [];
  const shipments = stages;
  const loading = shipmentsQuery.isLoading;
  const error = shipmentsQuery.error?.message || null;
  const [notice, setNotice] = useState<string | null>(null);
  const [commandPending, setCommandPending] = useState<InternalCommand | null>(null);
  const [noticeType, setNoticeType] = useState<'success' | 'error'>('success');
  const [selectedShipmentId, setSelectedShipmentId] = useState('');
  const [createRfqId, setCreateRfqId] = useState('');
  const [createQuoteId, setCreateQuoteId] = useState('');
  const [createPartNumbers, setCreatePartNumbers] = useState('');
  const [createQuantity, setCreateQuantity] = useState('1');
  const [eventStatus, setEventStatus] = useState('');
  const [eventLocation, setEventLocation] = useState('');
  const [eventDescription, setEventDescription] = useState('');
  const [carrierName, setCarrierName] = useState('');
  const [trackingNumber, setTrackingNumber] = useState('');
  const [smsRecipient, setSmsRecipient] = useState('');
  const [smsStatus, setSmsStatus] = useState('');
  const [smsTrackingUrl, setSmsTrackingUrl] = useState('');
  const commandMutation = useExecuteInternalCommand();
  const createShipmentMutation = useCreateShipment();
  const shipmentEventMutation = useAddShipmentEvent();
  const carrierTrackingMutation = useRegisterCarrierTracking();
  const refreshTrackingMutation = useRefreshCarrierTracking();
  const smsMutation = useSendShipmentSms();
  const selectedShipment = shipments.find(shipment => shipment.shipment_id === selectedShipmentId);
  const actionsBlocked = !canManageShipments || loading || Boolean(error) || !selectedShipment;

  useEffect(() => {
    if (!selectedShipmentId && shipments.length > 0) setSelectedShipmentId(shipments[0].shipment_id);
  }, [selectedShipmentId, shipments]);

  useEffect(() => {
    if (!createRfqId && (rfqQuery.data || []).length > 0) setCreateRfqId(rfqQuery.data?.[0].id || '');
  }, [createRfqId, rfqQuery.data]);

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

  const createShipment = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManageShipments || createShipmentMutation.isPending || rfqQuery.isSampleData) return;
    const body: CreateShipmentBody = {
      rfq_id: createRfqId,
      quote_id: createQuoteId.trim() || undefined,
      part_numbers: createPartNumbers.split(',').map(part => part.trim()).filter(Boolean),
      quantity: Number(createQuantity),
    };
    if (!body.rfq_id || body.part_numbers.length === 0 || !Number.isInteger(body.quantity) || body.quantity < 1) return;
    if (!window.confirm(`Create a shipment for RFQ ${body.rfq_id}? A tracking link may be sent to the customer.`)) return;
    setNotice(null);
    try {
      const result = await createShipmentMutation.mutateAsync(body);
      if (!result) return;
      setNoticeType('success');
      setNotice(`Shipment ${result.shipment_id} created. Tracking notification: ${result.tracking_notification}.`);
      setSelectedShipmentId(result.shipment_id);
      setCreateQuoteId('');
      setCreatePartNumbers('');
      setCreateQuantity('1');
    } catch (requestError) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(requestError, 'Unable to create shipment.'));
    }
  };

  const addShipmentEvent = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManageShipments || !selectedShipment || shipmentEventMutation.isPending) return;
    const body = { status: eventStatus.trim(), location: eventLocation.trim() || undefined, description: eventDescription.trim() };
    if (!body.status || !body.description) return;
    if (!window.confirm(`Record shipment event “${body.status}” for ${selectedShipment.shipment_id}?`)) return;
    try {
      await shipmentEventMutation.mutateAsync({ shipmentId: selectedShipment.shipment_id, body });
      setNoticeType('success');
      setNotice('Shipment event recorded.');
      setEventStatus('');
      setEventLocation('');
      setEventDescription('');
    } catch (requestError) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(requestError, 'Unable to record shipment event.'));
    }
  };

  const registerTracking = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManageShipments || !selectedShipment || carrierTrackingMutation.isPending) return;
    const carrier = carrierName.trim();
    const tracking_number = trackingNumber.trim();
    if (!carrier || !tracking_number) return;
    if (!window.confirm(`Register ${carrier} tracking ${tracking_number} with the carrier service?`)) return;
    try {
      await carrierTrackingMutation.mutateAsync({ shipmentId: selectedShipment.shipment_id, body: { carrier, tracking_number } });
      setNoticeType('success');
      setNotice('Carrier tracking registered.');
    } catch (requestError) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(requestError, 'Unable to register carrier tracking.'));
    }
  };

  const refreshTracking = async () => {
    if (!canManageShipments || !selectedShipment || !selectedShipment.carrier || !selectedShipment.tracking_number || refreshTrackingMutation.isPending) return;
    if (!window.confirm(`Refresh carrier tracking for ${selectedShipment.shipment_id}?`)) return;
    try {
      await refreshTrackingMutation.mutateAsync(selectedShipment.shipment_id);
      setNoticeType('success');
      setNotice('Tracking refreshed.');
    } catch (requestError) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(requestError, 'Unable to refresh tracking.'));
    }
  };

  const sendShipmentSms = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSendShipmentSms || !selectedShipment || smsMutation.isPending) return;
    const recipient = smsRecipient.trim();
    const status = smsStatus.trim();
    if (!/^\+[1-9]\d{7,14}$/.test(recipient) || !status) return;
    if (!window.confirm(`Send this shipment update by SMS to ${recipient}?`)) return;
    try {
      await smsMutation.mutateAsync({ shipmentId: selectedShipment.shipment_id, body: { recipient, status, tracking_url: smsTrackingUrl.trim() || undefined } });
      setNoticeType('success');
      setNotice('Shipment update sent.');
      setSmsStatus('');
    } catch (requestError) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(requestError, 'Unable to send shipment update.'));
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
            <button key={shipment.shipment_id} type="button" aria-pressed={selectedShipmentId === shipment.shipment_id} onClick={() => setSelectedShipmentId(shipment.shipment_id)} className={`rounded-xl border p-3 text-left text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${selectedShipmentId === shipment.shipment_id ? 'border-aero-blue bg-blue-50 dark:bg-aero-blue/10' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900'}`}>
              <div className="font-mono font-bold text-aero-blue">{shipment.shipment_id}</div>
              <div className="mt-1 font-semibold">{shipment.stage}: {shipment.status}</div>
              <div className="mt-1 text-slate-500">{shipment.carrier || 'Carrier pending'} {shipment.tracking_number || ''}</div>
            </button>
          ))}
        </div>
      </div>

      {!canManageShipments && <p role="status" className="border-y border-slate-200 py-3 text-xs text-slate-500 dark:border-slate-800">Shipment records and internal fulfillment controls are available to purchasing, managers, and administrators.</p>}

      {canManageShipments && <section aria-labelledby="create-shipment-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="create-shipment-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">CREATE SHIPMENT</h2><p className="text-[11px] text-slate-500">Creation may send a tracking link to the customer.</p></div>
        {rfqQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{rfqQuery.error.message}</span><button type="button" onClick={() => void rfqQuery.refetch()} className="font-bold underline">Retry RFQs</button></div>}
        {rfqQuery.isSampleData && <div role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">Shipment creation is disabled for sample RFQ data.</div>}
        <form onSubmit={event => void createShipment(event)} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>RFQ</span><select aria-label="Shipment RFQ" value={createRfqId} onChange={event => setCreateRfqId(event.target.value)} required disabled={rfqQuery.isLoading || rfqQuery.isSampleData} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"><option value="">Select RFQ</option>{(rfqQuery.data || []).filter(rfq => !['Pending_PO_Review', 'Intake_Failed', 'NEEDS_HUMAN_REVIEW', 'Rejected'].includes(rfq.status.toUpperCase())).map(rfq => <option key={rfq.id} value={rfq.id}>{rfq.id} · {rfq.customer_name}</option>)}</select></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Quote ID (optional)</span><input aria-label="Shipment quote ID" value={createQuoteId} onChange={event => setCreateQuoteId(event.target.value)} maxLength={128} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Part numbers (comma-separated)</span><input aria-label="Shipment part numbers" value={createPartNumbers} onChange={event => setCreatePartNumbers(event.target.value)} required maxLength={1000} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Quantity</span><input aria-label="Shipment quantity" type="number" value={createQuantity} onChange={event => setCreateQuantity(event.target.value)} min="1" step="1" required className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
          <button type="submit" disabled={createShipmentMutation.isPending || rfqQuery.isLoading || rfqQuery.isSampleData || !createRfqId || !createPartNumbers.trim() || !Number.isInteger(Number(createQuantity)) || Number(createQuantity) < 1} aria-busy={createShipmentMutation.isPending} className="inline-flex min-h-10 items-center justify-center gap-1.5 self-end rounded-md bg-aero-blue px-3 text-xs font-bold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50">{createShipmentMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}<span>CREATE SHIPMENT</span></button>
        </form>
      </section>}

      {canManageShipments && selectedShipment && <section aria-labelledby="shipment-operations-title" className="space-y-4 border-b border-slate-200 pb-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="shipment-operations-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">SHIPMENT OPERATIONS</h2><span className="font-mono text-[10px] text-aero-blue">{selectedShipment.shipment_id}</span></div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <form onSubmit={event => void addShipmentEvent(event)} className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
            <h3 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Record shipment event</h3>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Status</span><input aria-label="Shipment event status" value={eventStatus} onChange={event => setEventStatus(event.target.value)} required maxLength={80} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Location (optional)</span><input aria-label="Shipment event location" value={eventLocation} onChange={event => setEventLocation(event.target.value)} maxLength={160} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Description</span><textarea aria-label="Shipment event description" value={eventDescription} onChange={event => setEventDescription(event.target.value)} required rows={2} maxLength={1000} className="w-full resize-y rounded-md border border-slate-300 bg-white p-2 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
            <button type="submit" disabled={shipmentEventMutation.isPending || !eventStatus.trim() || !eventDescription.trim()} aria-busy={shipmentEventMutation.isPending} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-slate-300 px-3 text-xs font-bold hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800">{shipmentEventMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}<span>ADD SHIPMENT EVENT</span></button>
          </form>
          <div className="space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800">
            <form onSubmit={event => void registerTracking(event)} className="space-y-2">
              <h3 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Carrier tracking</h3>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Carrier</span><input aria-label="Carrier name" value={carrierName} onChange={event => setCarrierName(event.target.value)} required maxLength={80} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
                <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Tracking number</span><input aria-label="Tracking number" value={trackingNumber} onChange={event => setTrackingNumber(event.target.value)} required maxLength={160} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
              </div>
              <div className="flex flex-wrap gap-2"><button type="submit" disabled={carrierTrackingMutation.isPending || !carrierName.trim() || !trackingNumber.trim()} aria-busy={carrierTrackingMutation.isPending} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md bg-slate-900 px-3 text-xs font-bold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">{carrierTrackingMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}<span>REGISTER TRACKING</span></button>
                <button type="button" disabled={refreshTrackingMutation.isPending || !selectedShipment.carrier || !selectedShipment.tracking_number} aria-busy={refreshTrackingMutation.isPending} onClick={() => void refreshTracking()} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-slate-300 px-3 text-xs font-bold hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800">{refreshTrackingMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}<span>REFRESH TRACKING</span></button></div>
            </form>
            {canSendShipmentSms && <form onSubmit={event => void sendShipmentSms(event)} className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
              <h3 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Customer SMS update</h3>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Recipient (E.164)</span><input aria-label="SMS recipient" type="tel" value={smsRecipient} onChange={event => setSmsRecipient(event.target.value)} pattern="\+[1-9][0-9]{7,14}" placeholder="+15550100100" required className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
                <label className="space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Shipment status</span><input aria-label="SMS shipment status" value={smsStatus} onChange={event => setSmsStatus(event.target.value)} maxLength={80} required className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
              </div>
              <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Tracking URL (optional)</span><input aria-label="SMS tracking URL" type="url" value={smsTrackingUrl} onChange={event => setSmsTrackingUrl(event.target.value)} className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
              <button type="submit" disabled={smsMutation.isPending || !/^\+[1-9]\d{7,14}$/.test(smsRecipient.trim()) || !smsStatus.trim()} aria-busy={smsMutation.isPending} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md bg-aero-blue px-3 text-xs font-bold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50">{smsMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}<span>SEND TRACKING SMS</span></button>
            </form>}
          </div>
        </div>
      </section>}

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
