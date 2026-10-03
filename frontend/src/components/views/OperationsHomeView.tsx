import React, { useMemo, useState } from 'react';
import axios from 'axios';
import { AlertTriangle, CheckCircle2, Inbox, Loader2, Package, RefreshCw, Search, Send } from 'lucide-react';
import { API_BASE } from '../../services/api';
import { ViewMode, RFQ } from '../../types';
import { useProcessRFQ, useRFQs, useShipments } from '../../hooks/useApiResources';
import { OperationsControlRoom } from './OperationsControlRoom';

const NEEDS_ACTION = ['PENDING_INTERNAL_REVIEW', 'NEEDS_HUMAN_REVIEW', 'INTAKE_FAILED', 'FAILED', 'PENDING_APPROVAL', 'QUOTE_DISPATCH_PENDING', 'INTAKE'];
const QUOTED = ['QUOTE_SENT', 'QUOTED', 'NEGOTIATING', 'FOLLOW_UP'];
const WON = ['PO_RECEIVED', 'WON', 'ORDERED', 'CLOSED_WON'];

const statusLabel = (status: string) => {
  const key = status.toUpperCase();
  const labels: Record<string, string> = {
    PENDING_INTERNAL_REVIEW: 'Waiting for team review',
    NEEDS_HUMAN_REVIEW: 'Needs a person',
    INTAKE_FAILED: 'Could not read email',
    FAILED: 'Automation failed',
    PENDING_APPROVAL: 'Quote ready to approve',
    QUOTE_DISPATCH_PENDING: 'Quote sending',
    QUOTE_SENT: 'Quote sent',
    SUPPLIER_SOURCING: 'Asking suppliers',
    PRICING: 'Pricing',
    VALIDATING: 'Reading request',
    INTAKE: 'New',
    REJECTED: 'Declined',
    NO_QUOTE: 'No Quote',
  };
  return labels[key] || status.replace(/_/g, ' ').toLowerCase().replace(/^\w/, c => c.toUpperCase());
};

const ageLabel = (iso: string) => {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
};

export const OperationsHomeView: React.FC<{ onSelectView: (view: ViewMode) => void }> = ({ onSelectView }) => {
  const rfqs = useRFQs();
  const shipments = useShipments();
  const processRfq = useProcessRFQ();
  const [message, setMessage] = useState('');
  const [busyId, setBusyId] = useState('');

  const all = rfqs.data || [];
  const needsAction = useMemo(
    () => all.filter(r => NEEDS_ACTION.includes(r.status.toUpperCase()) || r.automation_paused)
      .sort((a, b) => (a.urgency === 'AOG' ? -1 : 0) - (b.urgency === 'AOG' ? -1 : 0) || +new Date(b.created_at) - +new Date(a.created_at)),
    [all],
  );
  const quoted = all.filter(r => QUOTED.includes(r.status.toUpperCase())).length;
  const won = all.filter(r => WON.includes(r.status.toUpperCase())).length;
  const activeShipments = (shipments.data || []).length;

  const handleProcess = async (rfq: RFQ) => {
    setBusyId(rfq.id);
    setMessage('');
    try {
      await processRfq.mutateAsync(rfq.id);
      setMessage(`${rfq.id} is being processed. Suppliers and the customer will be contacted automatically.`);
      void rfqs.refetch();
    } catch (error) {
      setMessage(`${rfq.id} could not be processed: ${error instanceof Error ? error.message : 'unknown error'}`);
    } finally {
      setBusyId('');
    }
  };

  const handlePartsBase = async (rfq: RFQ) => {
    const entered = window.prompt('Part numbers to request on PartsBase (up to 20, separated by commas):', rfq.part_number || '');
    if (!entered || !entered.trim()) return;
    setBusyId(`pb-${rfq.id}`);
    setMessage(`Requesting quotes on PartsBase for ${rfq.id}…`);
    try {
      const { data: job } = await axios.post(`${API_BASE}/internal/rfqs/${encodeURIComponent(rfq.id)}/partsbase-quote`, { part_numbers: entered });
      let status = job.status;
      for (let i = 0; i < 60 && (status === 'queued' || status === 'running'); i += 1) {
        await new Promise(resolve => setTimeout(resolve, 5000));
        const { data } = await axios.get(`${API_BASE}/internal/partsbase-jobs/${job.job_id}`);
        status = data.status;
        if (status === 'failed') throw new Error(data.error || 'PartsBase request failed');
      }
      setMessage(status === 'sent'
        ? `PartsBase RFQ sent for ${job.part_numbers.join(', ')}. Supplier answers will arrive by email.`
        : `PartsBase request for ${rfq.id} is still running. Check again in a few minutes.`);
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
      setMessage(`PartsBase request for ${rfq.id} failed: ${detail || (error instanceof Error ? error.message : 'unknown error')}`);
    } finally {
      setBusyId('');
    }
  };

  const cards = [
    { label: 'Need your action', value: needsAction.length, icon: AlertTriangle, tone: needsAction.length ? 'text-amber-500' : 'text-emerald-500', view: null },
    { label: 'Quotes sent', value: quoted, icon: Send, tone: 'text-sky-500', view: 'sales' as ViewMode },
    { label: 'Purchase orders', value: won, icon: CheckCircle2, tone: 'text-emerald-500', view: 'sales' as ViewMode },
    { label: 'Shipments', value: activeShipments, icon: Package, tone: 'text-violet-500', view: 'fulfillment' as ViewMode },
  ];

  return (
    <>
    <OperationsControlRoom
      rfqs={all}
      rfqLoading={rfqs.isLoading}
      rfqError={rfqs.error}
      onRefreshRfqs={rfqs.refetch}
    />
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Today</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Customer requests that need a person, and where everything stands.</p>
        </div>
        <button type="button" onClick={() => { void rfqs.refetch(); void shipments.refetch(); }} className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
          <RefreshCw className={`h-4 w-4 ${rfqs.isLoading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </header>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {cards.map(card => {
          const Icon = card.icon;
          return (
            <button key={card.label} type="button" disabled={!card.view} onClick={() => card.view && onSelectView(card.view)}
              className="rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm enabled:hover:border-aero-blue dark:border-slate-800 dark:bg-card-dark">
              <Icon className={`h-5 w-5 ${card.tone}`} />
              <div className="mt-3 text-3xl font-bold text-slate-900 dark:text-white">{rfqs.isLoading ? '…' : card.value}</div>
              <div className="text-sm text-slate-500 dark:text-slate-400">{card.label}</div>
            </button>
          );
        })}
      </section>

      {message && <div role="status" className="rounded-xl border border-sky-300 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200">{message}</div>}

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-card-dark">
        <div className="flex items-center gap-2 border-b border-slate-200 p-4 dark:border-slate-800">
          <Inbox className="h-5 w-5 text-aero-blue" />
          <h2 className="text-base font-bold text-slate-900 dark:text-white">Requests that need you</h2>
        </div>
        {rfqs.error && <p className="p-4 text-sm text-red-500">Could not load requests. Press Refresh.</p>}
        {!rfqs.isLoading && !rfqs.error && needsAction.length === 0 && (
          <p className="p-6 text-sm text-slate-500 dark:text-slate-400">All caught up. Every customer request is moving automatically.</p>
        )}
        <ul className="divide-y divide-slate-200 dark:divide-slate-800">
          {needsAction.map(rfq => (
            <li key={rfq.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-bold text-slate-900 dark:text-white">{rfq.id}</span>
                  {rfq.urgency === 'AOG' && <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-bold text-red-500">AOG</span>}
                  <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-600 dark:text-amber-400">{statusLabel(rfq.status)}</span>
                </div>
                <div className="mt-1 truncate text-sm text-slate-600 dark:text-slate-300">
                  {rfq.customer_name || rfq.customer_email}
                  {rfq.part_number ? ` · P/N ${rfq.part_number}` : ''}
                  {rfq.quantity ? ` · Qty ${rfq.quantity}` : ''}
                  {` · ${ageLabel(rfq.created_at)}`}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busyId === `pb-${rfq.id}`} onClick={() => void handlePartsBase(rfq)} className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
                  {busyId === `pb-${rfq.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} PartsBase
                </button>
                <button type="button" onClick={() => onSelectView('sales')} className="min-h-11 rounded-xl border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">Open</button>
                <button type="button" disabled={busyId === rfq.id} onClick={() => void handleProcess(rfq)} className="flex min-h-11 items-center gap-2 rounded-xl bg-aero-blue px-4 text-sm font-bold text-white hover:opacity-90 disabled:opacity-60">
                  {busyId === rfq.id && <Loader2 className="h-4 w-4 animate-spin" />} Process
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
    </>
  );
};
