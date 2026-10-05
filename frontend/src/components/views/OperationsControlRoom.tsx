import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  Clock3,
  FileSearch,
  Inbox,
  Loader2,
  Mail,
  PackageCheck,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from 'lucide-react';
import type { AutomationEvent, RFQ } from '../../types';
import type { ExtractionReviewResponse, MailboxMessageSummary } from '../../types/api';
import { apiService } from '../../services/api';
import {
  useApprovePurchaseOrder,
  useAutomationEvents,
  useDecideExtractionReview,
  useExtractionReviews,
  useMailboxHealth,
  useMailboxInbox,
  useRFQDetail,
  useSendMailboxMessage,
  useSetAutomationPause,
} from '../../hooks/useApiResources';
import './OperationsControlRoom.css';

type ReviewTask = { kind: 'extraction'; review: ExtractionReviewResponse };
type EmailTask = { kind: 'email'; message: MailboxMessageSummary; mailbox: 'sales' | 'purchasing' };
type PurchaseOrderTask = { kind: 'purchase-order'; rfq: RFQ };
type ManualTask = ReviewTask | EmailTask | PurchaseOrderTask;

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const money = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });

function messageEmail(from: string): string {
  const bracketed = from.match(/<([^>]+)>/);
  return (bracketed?.[1] || from).trim();
}

function eventLabel(event: AutomationEvent): string {
  return event.error || event.result || event.event_type.replace(/[_-]+/g, ' ');
}

function humanize(value: string): string {
  return value.replace(/[_-]+/g, ' ').toLowerCase().replace(/^\w/, letter => letter.toUpperCase());
}

function DialogFrame({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    if (!dialog.open) dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="ops-dialog"
      aria-labelledby="ops-dialog-title"
      onCancel={event => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="ops-dialog-head">
        <div>
          <span className="ops-eyebrow">HUMAN-IN-THE-LOOP CONTROL</span>
          <h2 id="ops-dialog-title">{title}</h2>
        </div>
        <button className="ops-icon-button" type="button" aria-label="Close dialog" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      {children}
    </dialog>
  );
}

function ExtractionReviewDialog({
  review,
  onClose,
  onDone,
}: {
  review: ExtractionReviewResponse;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const decideReview = useDecideExtractionReview();
  const rawExtraction = (review.extraction || {}) as Record<string, unknown>;
  const [editorMode, setEditorMode] = useState<'form' | 'json'>('form');

  // Structured fields
  const [partNumber, setPartNumber] = useState(String(rawExtraction.part_number || rawExtraction.requested_part_number || ''));
  const [description, setDescription] = useState(String(rawExtraction.description || ''));
  const [quantity, setQuantity] = useState(Number(rawExtraction.quantity || 1));
  const [condition, setCondition] = useState(String(rawExtraction.condition_requested || rawExtraction.condition || 'NE'));
  const [certification, setCertification] = useState(String(rawExtraction.certification_requested || rawExtraction.certificate_type || 'FAA 8130-3'));
  const [targetPrice, setTargetPrice] = useState(String(rawExtraction.target_price || rawExtraction.unit_price || ''));
  const [urgency, setUrgency] = useState(String(rawExtraction.urgency || 'Standard'));

  const [extractionJson, setExtractionJson] = useState(() => JSON.stringify(review.extraction || {}, null, 2));
  const [comments, setComments] = useState('');
  const [error, setError] = useState('');

  const syncFormToJson = () => {
    try {
      const existing = JSON.parse(extractionJson || '{}') as Record<string, unknown>;
      const updated = {
        ...existing,
        part_number: partNumber.trim().toUpperCase(),
        description: description.trim(),
        quantity: Math.max(1, Number(quantity) || 1),
        condition_requested: condition.trim(),
        certification_requested: certification.trim(),
        ...(targetPrice ? { target_price: Number(targetPrice) || 0 } : {}),
        urgency: urgency.trim(),
      };
      setExtractionJson(JSON.stringify(updated, null, 2));
    } catch {
      // Keep existing json if parsing failed
    }
  };

  const handleFieldChange = (setter: (val: any) => void, val: any) => {
    setter(val);
    // sync to json
    try {
      const existing = JSON.parse(extractionJson || '{}') as Record<string, unknown>;
      const updated = {
        ...existing,
        part_number: partNumber.trim().toUpperCase(),
        description: description.trim(),
        quantity: Math.max(1, Number(quantity) || 1),
        condition_requested: condition.trim(),
        certification_requested: certification.trim(),
        ...(targetPrice ? { target_price: Number(targetPrice) || 0 } : {}),
        urgency: urgency.trim(),
      };
      setExtractionJson(JSON.stringify(updated, null, 2));
    } catch {
      // ignore
    }
  };

  const submit = async (decision: 'approve' | 'reject') => {
    setError('');
    let approvedExtraction: Record<string, unknown> | undefined;
    if (decision === 'approve') {
      try {
        if (editorMode === 'form') {
          syncFormToJson();
          approvedExtraction = {
            ...(typeof rawExtraction === 'object' ? rawExtraction : {}),
            part_number: partNumber.trim().toUpperCase(),
            description: description.trim() || undefined,
            quantity: Math.max(1, Number(quantity) || 1),
            condition_requested: condition.trim(),
            certification_requested: certification.trim(),
            ...(targetPrice ? { target_price: Number(targetPrice) || 0 } : {}),
            urgency: urgency.trim(),
          };
        } else {
          const parsed: unknown = JSON.parse(extractionJson);
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('Enter a JSON object to continue.');
          }
          approvedExtraction = parsed as Record<string, unknown>;
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Extraction must be valid JSON.');
        return;
      }
    }

    try {
      await decideReview.mutateAsync({
        reviewId: review.id,
        body: {
          decision,
          operator_name: apiService.getUserEmail() || 'Internal operator',
          comments: comments.trim() || undefined,
          approved_extraction: approvedExtraction,
        },
      });
      onDone(decision === 'approve' ? 'Extraction reviewed and approved.' : 'Extraction review rejected.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit the review. Retry or contact support.');
    }
  };

  return (
    <DialogFrame title="Review Parsed RFQ Request" onClose={onClose}>
      <div className="ops-dialog-body">
        <p className="ops-dialog-copy">{review.reason || 'Verify and confirm the extracted request fields before autonomous sourcing continues.'}</p>
        
        {review.source_text && (
          <div className="ops-source-text" style={{ maxHeight: '140px', overflowY: 'auto' }}>
            <span className="ops-field-label">SOURCE EMAIL / CONTEXT</span>
            <p style={{ whiteSpace: 'pre-wrap', margin: '4px 0' }}>{review.source_text}</p>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px' }}>
          <span className="ops-field-label">STRUCTURED RFQ FIELDS</span>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              type="button"
              className={`ops-button ${editorMode === 'form' ? 'ops-button-primary' : 'ops-button-muted'}`}
              style={{ padding: '3px 8px', fontSize: '11px' }}
              onClick={() => setEditorMode('form')}
            >
              Visual Form
            </button>
            <button
              type="button"
              className={`ops-button ${editorMode === 'json' ? 'ops-button-primary' : 'ops-button-muted'}`}
              style={{ padding: '3px 8px', fontSize: '11px' }}
              onClick={() => {
                syncFormToJson();
                setEditorMode('json');
              }}
            >
              Raw JSON
            </button>
          </div>
        </div>

        {editorMode === 'form' ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '6px' }}>
            <div>
              <label className="ops-field-label" htmlFor="ops-form-pn">Part Number (P/N)</label>
              <input
                id="ops-form-pn"
                className="ops-input"
                autoComplete="off"
                spellCheck={false}
                value={partNumber}
                onChange={e => handleFieldChange(setPartNumber, e.target.value)}
                placeholder="e.g. 060-0012-00"
              />
            </div>
            <div>
              <label className="ops-field-label" htmlFor="ops-form-qty">Quantity</label>
              <input
                id="ops-form-qty"
                type="number"
                min="1"
                className="ops-input"
                value={quantity}
                onChange={e => handleFieldChange(setQuantity, Number(e.target.value) || 1)}
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label className="ops-field-label" htmlFor="ops-form-desc">Description</label>
              <input
                id="ops-form-desc"
                className="ops-input"
                value={description}
                onChange={e => handleFieldChange(setDescription, e.target.value)}
                placeholder="e.g. Fuel Control Unit"
              />
            </div>
            <div>
              <label className="ops-field-label" htmlFor="ops-form-cond">Condition</label>
              <input
                id="ops-form-cond"
                className="ops-input"
                value={condition}
                onChange={e => handleFieldChange(setCondition, e.target.value)}
                placeholder="NE / OH / SV / AR"
              />
            </div>
            <div>
              <label className="ops-field-label" htmlFor="ops-form-cert">Certification</label>
              <input
                id="ops-form-cert"
                className="ops-input"
                value={certification}
                onChange={e => handleFieldChange(setCertification, e.target.value)}
                placeholder="FAA 8130-3 / EASA Dual"
              />
            </div>
            <div>
              <label className="ops-field-label" htmlFor="ops-form-target">Target Unit Price (USD, Optional)</label>
              <input
                id="ops-form-target"
                type="number"
                step="0.01"
                min="0"
                className="ops-input"
                value={targetPrice}
                onChange={e => handleFieldChange(setTargetPrice, e.target.value)}
                placeholder="e.g. 14500.00"
              />
            </div>
            <div>
              <label className="ops-field-label" htmlFor="ops-form-urgency">Urgency / Priority</label>
              <select
                id="ops-form-urgency"
                className="ops-input"
                value={urgency}
                onChange={e => handleFieldChange(setUrgency, e.target.value)}
              >
                <option value="Standard">Standard Routine</option>
                <option value="Expedited">Expedited (Critical)</option>
                <option value="AOG">AOG (Aircraft On Ground)</option>
              </select>
            </div>
          </div>
        ) : (
          <>
            <textarea
              id="ops-extraction-json"
              name="approved-extraction"
              autoComplete="off"
              spellCheck={false}
              value={extractionJson}
              onChange={event => setExtractionJson(event.target.value)}
              rows={8}
              className="ops-textarea ops-json-editor"
              style={{ marginTop: '6px' }}
            />
          </>
        )}

        <label className="ops-field-label" htmlFor="ops-review-comments" style={{ marginTop: '10px' }}>Review Notes & Audit Trail</label>
        <textarea
          id="ops-review-comments"
          name="review-comments"
          autoComplete="off"
          value={comments}
          onChange={event => setComments(event.target.value)}
          rows={2}
          placeholder="Add operator notes for the compliance audit trail…"
          className="ops-textarea"
        />
        {error && <p className="ops-form-error" role="alert">{error}</p>}
        <div className="ops-dialog-actions" style={{ marginTop: '14px' }}>
          <button type="button" className="ops-button ops-button-muted" disabled={decideReview.isPending} onClick={() => void submit('reject')}>
            Reject RFQ
          </button>
          <button type="button" className="ops-button ops-button-primary" disabled={decideReview.isPending} onClick={() => void submit('approve')}>
            {decideReview.isPending ? <Loader2 size={15} className="ops-spin" aria-hidden="true" /> : <CheckCircle2 size={15} aria-hidden="true" />}
            Confirm & Progress RFQ
          </button>
        </div>
      </div>
    </DialogFrame>
  );
}

function EmailReplyDialog({
  task,
  onClose,
  onDone,
}: {
  task: EmailTask;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const sendMessage = useSendMailboxMessage();
  const recipient = messageEmail(task.message.from);
  const [subject, setSubject] = useState(`Re: ${task.message.subject.replace(/^re:\s*/i, '')}`);
  const [body, setBody] = useState('');
  const [targetCost, setTargetCost] = useState('');
  const [error, setError] = useState('');
  const supplierMode = task.mailbox === 'purchasing';

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    const messageBody = [
      body.trim(),
      supplierMode && targetCost ? `\n\nTarget unit cost: ${money.format(Number(targetCost))}` : '',
    ].join('');
    if (!recipient || !body.trim()) {
      setError('Enter a valid recipient and message before sending.');
      return;
    }
    try {
      await sendMessage.mutateAsync({
        mailbox: task.mailbox,
        message: { recipient, subject: subject.trim(), body: messageBody, reply_to: task.message.message_id },
      });
      onDone(supplierMode ? 'Supplier counteroffer sent.' : 'Client reply sent.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to send the message. Retry or contact support.');
    }
  };

  return (
    <DialogFrame title={supplierMode ? 'Supplier Negotiation' : 'Take Over Client Thread'} onClose={onClose}>
      <form className="ops-dialog-body" onSubmit={event => void submit(event)}>
        <p className="ops-dialog-copy">{supplierMode
          ? 'Send a human counteroffer from the purchasing mailbox. The target cost is included in the email for supplier confirmation.'
          : 'Reply directly from the sales mailbox. Sending this reply is a human takeover of the client conversation.'}</p>
        <label className="ops-field-label" htmlFor="ops-email-recipient">To</label>
        <input id="ops-email-recipient" name="recipient" type="email" autoComplete="off" spellCheck={false} required value={recipient} readOnly className="ops-input" />
        <label className="ops-field-label" htmlFor="ops-email-subject">Subject</label>
        <input id="ops-email-subject" name="subject" autoComplete="off" required value={subject} onChange={event => setSubject(event.target.value)} className="ops-input" />
        {supplierMode && (
          <>
            <label className="ops-field-label" htmlFor="ops-target-cost">Target Unit Cost (USD, Optional)</label>
            <input
              id="ops-target-cost"
              name="target-unit-cost"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              autoComplete="off"
              value={targetCost}
              onChange={event => setTargetCost(event.target.value)}
              placeholder="e.g., 1250.00…"
              className="ops-input"
            />
          </>
        )}
        <label className="ops-field-label" htmlFor="ops-email-message">Message</label>
        <textarea id="ops-email-message" name="message" autoComplete="off" required value={body} onChange={event => setBody(event.target.value)} rows={5} placeholder="Write your reply… " className="ops-textarea" />
        {error && <p className="ops-form-error" role="alert">{error}</p>}
        <div className="ops-dialog-actions">
          <button type="button" className="ops-button ops-button-muted" onClick={onClose}>Cancel</button>
          <button type="submit" className="ops-button ops-button-primary" disabled={sendMessage.isPending || !body.trim()}>
            {sendMessage.isPending ? <Loader2 size={15} className="ops-spin" aria-hidden="true" /> : <Send size={15} aria-hidden="true" />}
            {supplierMode ? 'Send Counteroffer' : 'Send Reply'}
          </button>
        </div>
      </form>
    </DialogFrame>
  );
}

function PurchaseOrderDialog({
  rfq,
  onClose,
  onDone,
}: {
  rfq: RFQ;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const detail = useRFQDetail(rfq.id);
  const approvePurchaseOrder = useApprovePurchaseOrder();
  const [comments, setComments] = useState('');
  const [error, setError] = useState('');
  const quote = detail.data?.quote_details?.quote;

  const approve = async () => {
    if (!quote?.id) return;
    setError('');
    try {
      const result = await approvePurchaseOrder.mutateAsync({
        quoteId: quote.id,
        body: { operator_name: apiService.getUserEmail() || 'Internal operator', comments: comments.trim() || undefined },
      });
      if (result) onDone(`PO approval recorded for ${rfq.id}. Check the notification trail for dispatch status.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to approve this PO. Retry or contact support.');
    }
  };

  return (
    <DialogFrame title="Review Purchase Order" onClose={onClose}>
      <div className="ops-dialog-body">
        <p className="ops-dialog-copy">Verify the order context before approving the financial commitment.</p>
        <dl className="ops-order-details">
          <div><dt>RFQ</dt><dd>{rfq.id}</dd></div>
          <div><dt>Customer</dt><dd>{rfq.customer_name}</dd></div>
          <div><dt>Part / Qty</dt><dd>{rfq.part_number || 'Part details in request'} / {rfq.quantity ?? '—'}</dd></div>
          <div><dt>Quote Total</dt><dd>{quote ? money.format(quote.total_amount) : detail.isLoading ? 'Loading…' : 'Quote total unavailable'}</dd></div>
          <div><dt>Approval Status</dt><dd>{humanize(rfq.status)}</dd></div>
        </dl>
        <label className="ops-field-label" htmlFor="ops-po-comments">Approval Notes</label>
        <textarea id="ops-po-comments" name="po-approval-comments" autoComplete="off" value={comments} onChange={event => setComments(event.target.value)} rows={2} placeholder="Record the review context… " className="ops-textarea" />
        {detail.error && <p className="ops-form-error" role="alert">{detail.error.message}</p>}
        {error && <p className="ops-form-error" role="alert">{error}</p>}
        <div className="ops-dialog-actions">
          <button type="button" className="ops-button ops-button-muted" onClick={onClose}>Cancel</button>
          <button type="button" className="ops-button ops-button-primary" disabled={!quote?.id || detail.isLoading || approvePurchaseOrder.isPending} onClick={() => void approve()}>
            {approvePurchaseOrder.isPending ? <Loader2 size={15} className="ops-spin" aria-hidden="true" /> : <ShieldCheck size={15} aria-hidden="true" />}
            Approve PO
          </button>
        </div>
      </div>
    </DialogFrame>
  );
}

export const OperationsControlRoom: React.FC<{
  rfqs: RFQ[];
  rfqLoading: boolean;
  rfqError: Error | null;
  onRefreshRfqs: () => Promise<void>;
}> = ({ rfqs, rfqLoading, rfqError, onRefreshRfqs }) => {
  const events = useAutomationEvents();
  const reviews = useExtractionReviews();
  const salesInbox = useMailboxInbox('sales');
  const purchasingInbox = useMailboxInbox('purchasing');
  const mailboxHealth = useMailboxHealth();
  const pauseAutomation = useSetAutomationPause();
  const [manualTask, setManualTask] = useState<ManualTask | null>(null);
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');

  const eventList = events.data || [];
  const salesMessages = salesInbox.data?.messages || [];
  const supplierMessages = purchasingInbox.data?.messages || [];
  const pendingReviews = reviews.data || [];
  const poApprovals = useMemo(
    () => rfqs.filter(rfq => /pending.*po|po.*pending/i.test(rfq.status)),
    [rfqs],
  );
  const purchaseOrders = useMemo(
    () => rfqs.filter(rfq => !/pending.*po|po.*pending/i.test(rfq.status) && /po|order|won/i.test(rfq.status)),
    [rfqs],
  );
  const discountEvents = useMemo(
    () => eventList.filter(event => /discount|negotiat|counteroffer/i.test(`${event.event_type} ${event.result || ''} ${event.error || ''}`)),
    [eventList],
  );
  const catalogEvents = useMemo(
    () => eventList.filter(event => /catalog|inventory|ingest|supplier.feed/i.test(`${event.event_type} ${event.result || ''} ${event.error || ''}`)),
    [eventList],
  );
  const notificationEvents = useMemo(
    () => eventList.filter(event => /notification|purchase.order|po.received/i.test(`${event.event_type} ${event.result || ''} ${event.error || ''}`)),
    [eventList],
  );
  const clientFeed = useMemo(() => [
    ...salesMessages.map(message => ({ kind: 'email' as const, at: message.date, message })),
    ...eventList.map(event => ({ kind: 'event' as const, at: event.execution_time || event.created_at, event })),
  ].sort((a, b) => Date.parse(b.at) - Date.parse(a.at)).slice(0, 7), [eventList, salesMessages]);
  const purchasingStatus = mailboxHealth.data?.purchasing?.status;

  useEffect(() => {
    const refresh = () => {
      void onRefreshRfqs();
      void events.refetch();
      void reviews.refetch();
      void salesInbox.refetch();
      void purchasingInbox.refetch();
      void mailboxHealth.refetch();
    };
    const timer = window.setInterval(refresh, 15_000);
    return () => window.clearInterval(timer);
  }, [events.refetch, mailboxHealth.refetch, onRefreshRfqs, purchasingInbox.refetch, reviews.refetch, salesInbox.refetch]);

  const refreshAll = () => {
    void onRefreshRfqs();
    void events.refetch();
    void reviews.refetch();
    void salesInbox.refetch();
    void purchasingInbox.refetch();
    void mailboxHealth.refetch();
  };

  const onDone = (message: string) => {
    setManualTask(null);
    setNotice(message);
    setActionError('');
    refreshAll();
  };

  const handlePause = async (review: ExtractionReviewResponse) => {
    if (!review.entity_id) {
      setActionError(`Cannot pause automation: review ${review.id} is not linked to an RFQ.`);
      return;
    }
    setActionError('');
    setNotice('');
    try {
      await pauseAutomation.mutateAsync({
        rfqId: review.entity_id,
        paused: true,
        reason: `Paused from Operations Control Room for manual review ${review.id}.`,
      });
      setNotice(`Automation paused for ${review.entity_id}.`);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : 'Unable to pause automation. Retry or contact support.');
    }
  };

  const metricCards = [
    { label: 'Needs Human Review', value: reviews.isLoading || reviews.error ? '—' : pendingReviews.length, icon: FileSearch, tone: 'ops-tone-gold' },
    { label: 'Supplier Inbox', value: purchasingInbox.isLoading || purchasingInbox.error ? '—' : supplierMessages.length, icon: Inbox, tone: 'ops-tone-cyan' },
    { label: 'Negotiations', value: events.isLoading || events.error ? '—' : discountEvents.length, icon: Sparkles, tone: 'ops-tone-violet' },
    { label: 'POs In Pipeline', value: rfqLoading || rfqError ? '—' : purchaseOrders.length + poApprovals.length, icon: PackageCheck, tone: 'ops-tone-green' },
  ];

  return (
    <section className="ops-control-room" aria-labelledby="ops-control-heading">
      <header className="ops-control-header">
        <div>
          <div className="ops-eyebrow"><span className="ops-live-pip" /> AUTONOMOUS PROCUREMENT · HUMAN OVERSIGHT</div>
          <h1 id="ops-control-heading">Operations Control Room</h1>
          <p>Exceptions, supplier signals &amp; order commitments—one crew, one live picture.</p>
        </div>
        <button type="button" className="ops-refresh-button" onClick={() => { setNotice(''); setActionError(''); refreshAll(); }} aria-label="Refresh operations data">
          <RefreshCw size={15} className={rfqLoading ? 'ops-spin' : ''} aria-hidden="true" />
          <span>Refresh</span>
        </button>
      </header>

      {notice && <div className="ops-notice" role="status" aria-live="polite"><CheckCircle2 size={16} aria-hidden="true" />{notice}</div>}
      {actionError && <div className="ops-error" role="alert">{actionError}</div>}

      <div className="ops-metrics" aria-label="Operations summary">
        {metricCards.map(card => {
          const Icon = card.icon;
          return (
            <article className="ops-metric-card" key={card.label}>
              <div className={`ops-metric-icon ${card.tone}`}><Icon size={17} aria-hidden="true" /></div>
              <div className="ops-metric-value">{card.value}</div>
              <div className="ops-metric-label">{card.label}</div>
            </article>
          );
        })}
      </div>

      {rfqError && <p className="ops-error" role="alert">Could not load requests: {rfqError.message}</p>}

      <div className="ops-grid">
        <div className="ops-column">
          <section className="ops-panel ops-activity-panel" aria-labelledby="ops-activity-heading">
            <div className="ops-panel-head">
              <div className="ops-panel-title"><span className="ops-panel-icon ops-tone-cyan"><Activity size={17} aria-hidden="true" /></span><div><h2 id="ops-activity-heading">Live Email &amp; Agent Activity</h2><p>Client intake, parsing &amp; agent actions</p></div></div>
              <span className={`ops-live-label ${events.error || salesInbox.error ? 'is-degraded' : ''}`}>
                <span className="ops-live-pip" />{events.error || salesInbox.error ? 'DEGRADED' : 'LIVE'}
              </span>
            </div>
            {(events.error || salesInbox.error) && <p className="ops-inline-error" role="alert">{events.error?.message || salesInbox.error?.message}</p>}
            <ul className="ops-activity-list">
              {clientFeed.map((item, index) => {
                if (item.kind === 'email') {
                  return (
                    <li className="ops-activity-item" key={`mail-${item.message.message_id}`}>
                      <span className="ops-timeline-mark ops-mark-mail"><Mail size={13} aria-hidden="true" /></span>
                      <div className="ops-activity-copy">
                        <div className="ops-activity-meta"><span>INCOMING CLIENT EMAIL</span><time dateTime={item.at}>{dateTime.format(new Date(item.at))}</time></div>
                        <strong>{item.message.subject || '(No subject)'}</strong>
                        <p>{item.message.from} · {item.message.body || 'Email received. Open the thread to review details.'}</p>
                      </div>
                      <button className="ops-text-action" type="button" onClick={() => setManualTask({ kind: 'email', mailbox: 'sales', message: item.message })}>Take Over Thread</button>
                    </li>
                  );
                }
                return (
                  <li className="ops-activity-item" key={`event-${item.event.id}-${index}`}>
                    <span className={`ops-timeline-mark ${item.event.status.toUpperCase() === 'FAILED' ? 'ops-mark-alert' : 'ops-mark-agent'}`}>
                      {item.event.status.toUpperCase() === 'FAILED' ? <AlertTriangle size={13} aria-hidden="true" /> : <Zap size={13} aria-hidden="true" />}
                    </span>
                    <div className="ops-activity-copy">
                      <div className="ops-activity-meta"><span>{humanize(item.event.event_type)} · {humanize(item.event.status)}</span><time dateTime={item.at}>{dateTime.format(new Date(item.at))}</time></div>
                      <strong>{item.event.entity_id || 'Automation event'}</strong>
                      <p>{eventLabel(item.event)}</p>
                    </div>
                  </li>
                );
              })}
              {!clientFeed.length && (events.error || salesInbox.error) && (
                <li className="ops-empty"><AlertTriangle size={17} aria-hidden="true" />Activity unavailable. Check API connectivity and refresh.</li>
              )}
              {!clientFeed.length && !events.error && !salesInbox.error && !events.isLoading && !salesInbox.isLoading && (
                <li className="ops-empty"><Activity size={17} aria-hidden="true" />No recent client or agent activity.</li>
              )}
              {(events.isLoading || salesInbox.isLoading) && !events.error && !salesInbox.error && !clientFeed.length && <li className="ops-empty">Loading activity…</li>}
            </ul>
          </section>

          <section className="ops-panel" aria-labelledby="ops-purchasing-heading">
            <div className="ops-panel-head">
              <div className="ops-panel-title"><span className="ops-panel-icon ops-tone-gold"><Inbox size={17} aria-hidden="true" /></span><div><h2 id="ops-purchasing-heading">Supplier &amp; Purchasing Command Center</h2><p>purchasing@wingedtycoons.com · Catalog feed &amp; price discussions</p></div></div>
              <span className={`ops-status-pill ${/connected|healthy|ok/i.test(purchasingStatus || '') ? 'is-healthy' : 'is-unknown'}`}>
                <span className="ops-status-dot" />{purchasingStatus ? humanize(purchasingStatus) : mailboxHealth.error ? 'Unavailable' : 'Checking'}
              </span>
            </div>
            {(purchasingInbox.error || mailboxHealth.error) && <p className="ops-inline-error" role="alert">{purchasingInbox.error?.message || mailboxHealth.error?.message}</p>}
            <div className="ops-catalog-health">
              <span className="ops-mini-icon"><PackageCheck size={15} aria-hidden="true" /></span>
              <div><strong>Catalog &amp; inventory ingestion</strong><p>{catalogEvents.length ? `${catalogEvents.length} recent ingestion event${catalogEvents.length === 1 ? '' : 's'} in the audit feed` : events.error || events.isLoading ? 'Ingestion data unavailable' : 'No recent ingestion event recorded'}</p></div>
              <span className={`ops-health-text ${catalogEvents.some(event => event.status === 'FAILED') ? 'is-alert' : ''}`}>
                {catalogEvents.some(event => event.status.toUpperCase() === 'FAILED') ? 'Review needed' : catalogEvents.length ? 'Feed active' : events.error || events.isLoading ? 'Unavailable' : 'No signal'}
              </span>
            </div>
            <div className="ops-subsection-head"><h3>Supplier Inbox</h3><span>{purchasingInbox.error || purchasingInbox.isLoading ? 'Unavailable' : `${supplierMessages.length} messages`}</span></div>
            <ul className="ops-compact-list">
              {supplierMessages.slice(0, 4).map(message => (
                <li key={message.message_id}>
                  <div className="ops-compact-copy"><strong>{message.subject || '(No subject)'}</strong><span>{message.from} · {message.attachments?.length || 0} attachment{message.attachments?.length === 1 ? '' : 's'}</span></div>
                  <button type="button" className="ops-small-button" onClick={() => setManualTask({ kind: 'email', mailbox: 'purchasing', message })}>Counteroffer</button>
                </li>
              ))}
              {!supplierMessages.length && purchasingInbox.error && <li className="ops-empty ops-empty-small">Supplier inbox unavailable.</li>}
              {!supplierMessages.length && !purchasingInbox.error && !purchasingInbox.isLoading && <li className="ops-empty ops-empty-small">No supplier messages in the current inbox.</li>}
              {purchasingInbox.isLoading && !purchasingInbox.error && !supplierMessages.length && <li className="ops-empty ops-empty-small">Loading purchasing inbox…</li>}
            </ul>
            <div className="ops-subsection-head"><h3>Discount Negotiations</h3><span>{events.error || events.isLoading ? 'Unavailable' : `${discountEvents.length} audit events`}</span></div>
            {discountEvents.length ? (
              <ul className="ops-negotiation-list">
                {discountEvents.slice(0, 3).map(event => (
                  <li key={event.id}><Sparkles size={13} aria-hidden="true" /><span>{event.entity_id} · {eventLabel(event)}</span><b>{humanize(event.status)}</b></li>
                ))}
              </ul>
            ) : <p className="ops-empty ops-empty-small">{events.error || events.isLoading ? 'Negotiation activity unavailable.' : 'No discount or negotiation events recorded recently.'}</p>}
          </section>
        </div>

        <div className="ops-column">
          <section className="ops-panel" aria-labelledby="ops-review-heading">
            <div className="ops-panel-head">
              <div className="ops-panel-title"><span className="ops-panel-icon ops-tone-gold"><FileSearch size={17} aria-hidden="true" /></span><div><h2 id="ops-review-heading">Manual Exception Queue</h2><p>Low-confidence parsing &amp; workflow holds</p></div></div>
              <span className="ops-count-badge">{reviews.error || reviews.isLoading ? '—' : pendingReviews.length}</span>
            </div>
            {reviews.error && <p className="ops-inline-error" role="alert">{reviews.error.message}</p>}
            <ul className="ops-exception-list">
              {pendingReviews.slice(0, 5).map(review => (
                <li key={review.id}>
                  <div className="ops-exception-copy"><strong>{review.entity_id || review.id}</strong><span>{review.reason || humanize(review.task || 'Extraction review')}</span><small>{review.created_at ? dateTime.format(new Date(review.created_at)) : 'Review pending'}</small></div>
                  <div className="ops-exception-actions">
                    <button type="button" className="ops-small-button" onClick={() => setManualTask({ kind: 'extraction', review })}>Review</button>
                    {review.entity_id && <button type="button" className="ops-quiet-button" disabled={pauseAutomation.isPending} onClick={() => void handlePause(review)} aria-label={`Pause automation for ${review.entity_id}`}>Pause</button>}
                  </div>
                </li>
              ))}
              {!pendingReviews.length && reviews.error && <li className="ops-empty ops-empty-small">Review queue unavailable.</li>}
              {!pendingReviews.length && !reviews.error && !reviews.isLoading && <li className="ops-empty ops-empty-small">No pending extraction reviews.</li>}
              {reviews.isLoading && !reviews.error && !pendingReviews.length && <li className="ops-empty ops-empty-small">Checking review queue…</li>}
            </ul>
          </section>

          <section className="ops-panel" aria-labelledby="ops-po-heading">
            <div className="ops-panel-head">
              <div className="ops-panel-title"><span className="ops-panel-icon ops-tone-green"><Bell size={17} aria-hidden="true" /></span><div><h2 id="ops-po-heading">PO &amp; Notification Watchtower</h2><p>Order commitments &amp; dispatch trail</p></div></div>
              <span className="ops-count-badge ops-count-green">{rfqError || rfqLoading ? '—' : purchaseOrders.length}</span>
            </div>
            <div className="ops-notification-summary">
              <Bell size={14} aria-hidden="true" />
              <span>{notificationEvents.length ? `${notificationEvents.length} notification-related audit event${notificationEvents.length === 1 ? '' : 's'} recorded` : events.error || events.isLoading ? 'Notification activity unavailable' : 'No PO notification event found in the current audit feed'}</span>
            </div>
            {notificationEvents.slice(0, 2).map(event => (
              <div className="ops-notification-row" key={event.id}>
                <span className={event.status === 'FAILED' ? 'is-alert' : 'is-sent'}>{event.status === 'FAILED' ? 'Dispatch issue' : 'Dispatch event'}</span>
                <p>{event.entity_id} · {eventLabel(event)}</p>
                {`${event.result || ''} ${event.error || ''}`.toLowerCase().includes('camila@wingedtycoons.com') && <small>Recipient: camila@wingedtycoons.com</small>}
              </div>
            ))}
            <div className="ops-subsection-head"><h3>Awaiting PO Approval</h3><span>{rfqError || rfqLoading ? '—' : poApprovals.length}</span></div>
            <ul className="ops-compact-list">
              {poApprovals.slice(0, 4).map(rfq => (
                <li key={rfq.id}>
                  <div className="ops-compact-copy"><strong>{rfq.id} · {rfq.customer_name}</strong><span>{rfq.part_number || 'Part pending'} · {rfq.quantity ?? 'Qty pending'} units · {humanize(rfq.status)}</span></div>
                  <button type="button" className="ops-small-button" onClick={() => setManualTask({ kind: 'purchase-order', rfq })}>Review PO</button>
                </li>
              ))}
              {!poApprovals.length && rfqError && <li className="ops-empty ops-empty-small">Purchase-order data unavailable.</li>}
              {!poApprovals.length && !rfqError && !rfqLoading && <li className="ops-empty ops-empty-small">No purchase orders waiting for approval.</li>}
              {rfqLoading && !rfqError && !poApprovals.length && <li className="ops-empty ops-empty-small">Loading orders…</li>}
            </ul>
            <div className="ops-subsection-head"><h3>Issued / Received Orders</h3><span>{rfqError || rfqLoading ? '—' : purchaseOrders.length}</span></div>
            <ul className="ops-compact-list">
              {purchaseOrders.slice(0, 4).map(rfq => (
                <li key={rfq.id}>
                  <div className="ops-compact-copy"><strong>{rfq.id} · {rfq.customer_name}</strong><span>{rfq.part_number || 'Part details in request'} · {humanize(rfq.status)}</span></div>
                  <span className="ops-order-status"><CheckCircle2 size={12} aria-hidden="true" /> Logged</span>
                </li>
              ))}
              {!purchaseOrders.length && rfqError && <li className="ops-empty ops-empty-small">Purchase-order data unavailable.</li>}
              {!purchaseOrders.length && !rfqError && !rfqLoading && <li className="ops-empty ops-empty-small">No issued or received POs in the current RFQ list.</li>}
            </ul>
          </section>
        </div>
      </div>

      <footer className="ops-control-footer">
        <span><ShieldCheck size={13} aria-hidden="true" /> Human approval stays in control of high-impact decisions.</span>
        <span><Clock3 size={13} aria-hidden="true" /> Auto-refresh every 15 seconds</span>
      </footer>

      {manualTask?.kind === 'extraction' && <ExtractionReviewDialog review={manualTask.review} onClose={() => setManualTask(null)} onDone={onDone} />}
      {manualTask?.kind === 'email' && <EmailReplyDialog task={manualTask} onClose={() => setManualTask(null)} onDone={onDone} />}
      {manualTask?.kind === 'purchase-order' && <PurchaseOrderDialog rfq={manualTask.rfq} onClose={() => setManualTask(null)} onDone={onDone} />}
    </section>
  );
};
