import React, { useEffect, useState } from 'react';
import { apiService, getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { FallbackDataBanner } from '../common/FallbackDataBanner';
import { isFailedRfq, rfqStatusLabel } from '../../utils/rfqState';
import { useAutomationEvents, useDecideExtractionReview, useExtractionReview, useExtractionReviews, useLlmHealth, useLlmTelemetry, useRFQs, useTraceDecision } from '../../hooks/useApiResources';
import type { ExtractionReviewResponse, LlmConnectionTestResponse } from '../../types/api';
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
  Eye,
  Loader2,
  RefreshCw,
} from 'lucide-react';

const formatReviewValue = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (value === undefined) return '';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

export const TraceVaultView: React.FC = () => {
  const [activeTab, setActiveTab] = useState('');
  const [selectedReviewId, setSelectedReviewId] = useState('');
  const [reviewComments, setReviewComments] = useState('');
  const [verificationPassed, setVerificationPassed] = useState(false);
  const [hardFreezeEnabled, setHardFreezeEnabled] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);
  const [reviewNoticeType, setReviewNoticeType] = useState<'success' | 'error'>('success');
  const [llmConnectionTest, setLlmConnectionTest] = useState<LlmConnectionTestResponse | null>(null);
  const [llmConnectionTestError, setLlmConnectionTestError] = useState<string | null>(null);
  const [llmConnectionTestPending, setLlmConnectionTestPending] = useState(false);
  const [pendingDecision, setPendingDecision] = useState<'certify' | 'reject' | 'rescan' | 'freeze' | null>(null);
  const [reviewDecisionPending, setReviewDecisionPending] = useState<'approve' | 'reject' | null>(null);
  const rfqQuery = useRFQs();
  const eventsQuery = useAutomationEvents();
  const decisionMutation = useTraceDecision();
  const canReviewExtractions = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING']);
  const canViewLlm = apiService.hasAnyRole(['ROLE_ADMIN', 'ROLE_MANAGER']);
  const extractionReviewsQuery = useExtractionReviews(canReviewExtractions);
  const extractionReviewQuery = useExtractionReview(selectedReviewId);
  const extractionDecisionMutation = useDecideExtractionReview();
  const llmHealthQuery = useLlmHealth(canViewLlm);
  const llmTelemetryQuery = useLlmTelemetry(canViewLlm);
  const rfqs = rfqQuery.data || [];
  const loading = rfqQuery.isLoading;
  const usingFallbackData = rfqQuery.isSampleData;
  const loadError = rfqQuery.error?.message || null;
  const automationEvents = eventsQuery.data || [];
  const complianceLoadError = eventsQuery.error?.message || null;
  const loadingComplianceEvents = eventsQuery.isLoading;
  const extractionReviews = extractionReviewsQuery.data || [];
  const selectedExtractionReview: ExtractionReviewResponse | undefined = extractionReviewQuery.data;
  const selectedRfq = rfqs.find(rfq => rfq.id === activeTab);
  const actionsBlocked = loading || decisionMutation.isPending || usingFallbackData || !selectedRfq || isFailedRfq(selectedRfq);

  const recordDecision = async (decision: 'certify' | 'reject' | 'rescan' | 'freeze') => {
    if (decisionMutation.isPending || !selectedRfq || isFailedRfq(selectedRfq) || usingFallbackData) {
      setNotice(isFailedRfq(selectedRfq)
        ? selectedRfq?.status.trim().toUpperCase() === 'NEEDS_HUMAN_REVIEW'
          ? 'Operator review required. Trace decisions are disabled until intake operations resolves the review.'
          : 'Intake failed. Trace decisions are disabled. Contact intake operations to arrange retry or escalation.'
        : 'Select a live RFQ before recording a trace decision.');
      return;
    }
    const decisionLabel = decision === 'freeze' ? 'place a hard freeze on' : `${decision} trace documents for`;
    if (!window.confirm(`Confirm ${decisionLabel} RFQ ${activeTab}?`)) return;
    setPendingDecision(decision);
    try {
      await decisionMutation.mutateAsync({ rfqId: activeTab, decision });
      setVerificationPassed(decision === 'certify');
      setHardFreezeEnabled(decision === 'freeze');
      setNotice(`Trace decision ${decision} recorded for ${activeTab}.`);
    } catch (error) {
      setNotice(getApiErrorMessage(error, 'Unable to record trace decision.'));
    } finally {
      setPendingDecision(null);
    }
  };

  const complianceEvents = automationEvents.filter(event => /compliance|trace/i.test(`${event.event_type} ${event.entity_type}`));
  const flaggedRfqCount = rfqs.filter(rfq => isFailedRfq(rfq)).length;
  const latestComplianceEvent = complianceEvents[0];

  const testLlmConnections = async () => {
    if (llmConnectionTestPending) return;
    setLlmConnectionTestPending(true);
    setLlmConnectionTest(null);
    setLlmConnectionTestError(null);
    try {
      setLlmConnectionTest(await apiService.testLlmConnections());
    } catch (error) {
      setLlmConnectionTestError(getApiErrorMessage(error, 'Unable to test live LLM connections.'));
    } finally {
      setLlmConnectionTestPending(false);
    }
  };

  useEffect(() => {
    if (!activeTab && rfqs.length > 0) setActiveTab(rfqs[0].id);
  }, [activeTab, rfqs]);

  useEffect(() => {
    if (!selectedReviewId && extractionReviews.length > 0) setSelectedReviewId(extractionReviews[0].id);
  }, [selectedReviewId, extractionReviews]);

  useEffect(() => {
    setReviewComments('');
  }, [selectedReviewId]);

  const decideExtractionReview = async (decision: 'approve' | 'reject') => {
    const review = selectedExtractionReview;
    const comments = reviewComments.trim();
    if (!review || review.status !== 'PENDING' || extractionDecisionMutation.isPending) return;
    if (decision === 'approve' && !review.extraction) {
      setReviewNoticeType('error');
      setReviewNotice('The extraction payload is missing and cannot be approved.');
      return;
    }
    if (decision === 'reject' && !comments) {
      setReviewNoticeType('error');
      setReviewNotice('Add a reason before rejecting this extraction.');
      return;
    }
    if (!window.confirm(`${decision === 'approve' ? 'Approve' : 'Reject'} extraction review ${review.id}?`)) return;
    setReviewDecisionPending(decision);
    setReviewNotice(null);
    try {
      await extractionDecisionMutation.mutateAsync({
        reviewId: review.id,
        body: {
          decision,
          comments: comments || undefined,
          approved_extraction: decision === 'approve' ? review.extraction : undefined,
        },
      });
      setReviewNoticeType('success');
      setReviewNotice(`Extraction review ${decision === 'approve' ? 'approved' : 'rejected'}.`);
      setSelectedReviewId('');
      setReviewComments('');
    } catch (error) {
      setReviewNoticeType('error');
      setReviewNotice(getApiErrorMessage(error, `Unable to ${decision} the extraction review.`));
    } finally {
      setReviewDecisionPending(null);
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {loadError && <div role="alert" className="flex items-center justify-between rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700"><span>{loadError}</span><button type="button" aria-label="Retry loading trace records" onClick={() => void rfqQuery.refetch()} className="font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">Retry</button></div>}
      {notice && <div role="status" aria-live="polite" className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800 dark:border-blue-500/40 dark:bg-blue-500/10 dark:text-blue-200">{notice}</div>}
      {usingFallbackData && <FallbackDataBanner />}
      {canViewLlm && <section aria-labelledby="llm-operations-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="llm-operations-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">LLM PROVIDER HEALTH & TELEMETRY</h2>
          <div className="flex gap-2">
            <button type="button" onClick={() => void testLlmConnections()} disabled={llmConnectionTestPending} className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-aero-blue px-2.5 text-xs font-semibold text-aero-blue hover:bg-blue-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue disabled:cursor-wait disabled:opacity-60 dark:hover:bg-blue-500/10">
              {llmConnectionTestPending && <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}
              {llmConnectionTestPending ? 'Testing live connections...' : 'Test live connections'}
            </button>
            <button type="button" onClick={() => void llmHealthQuery.refetch()} className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-slate-300 px-2.5 text-xs font-semibold hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:hover:bg-slate-800">Refresh health</button>
            <button type="button" onClick={() => void llmTelemetryQuery.refetch()} className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-slate-300 px-2.5 text-xs font-semibold hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:hover:bg-slate-800">Refresh telemetry</button>
          </div>
        </div>
        <p className="text-xs text-slate-500">Sends one short test prompt to each configured provider. Provider usage charges may apply.</p>
        {llmConnectionTestError && <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200">{llmConnectionTestError}</div>}
        {llmConnectionTest && <div role="status" aria-live="polite" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {llmConnectionTest.results.map(result => <div key={result.provider} className="rounded-md border border-slate-200 p-3 text-xs dark:border-slate-800">
            <p className="font-bold capitalize">{result.provider}: <span className={result.status === 'connected' ? 'text-emerald-700 dark:text-emerald-300' : result.status === 'failed' ? 'text-red-700 dark:text-red-300' : 'text-slate-500'}>{result.status === 'connected' ? 'Connected' : result.status === 'failed' ? 'Failed' : 'Not configured'}</span></p>
            {result.model && <p className="mt-1 text-slate-600 dark:text-slate-400">Model: {result.model}</p>}
            {result.latency_ms !== undefined && <p className="mt-1 text-slate-600 dark:text-slate-400">Response time: {result.latency_ms.toLocaleString()} ms</p>}
            {result.message && <p className="mt-1 text-slate-600 dark:text-slate-400">{result.message}</p>}
          </div>)}
        </div>}
        {llmHealthQuery.error && <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200">{llmHealthQuery.error.message}</div>}
        {llmHealthQuery.isLoading && <p role="status" className="text-xs text-slate-500">Loading provider health...</p>}
        {llmHealthQuery.data && <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div className="min-w-0"><p className="text-[10px] font-semibold uppercase text-slate-500">Default provider</p><p className="mt-1 truncate text-sm font-bold text-slate-900 dark:text-slate-100">{llmHealthQuery.data.default_provider}</p></div>
          <div className="min-w-0"><p className="text-[10px] font-semibold uppercase text-slate-500">Customer communication</p><p className="mt-1 truncate text-sm font-bold text-slate-900 dark:text-slate-100">{llmHealthQuery.data.customer_communication_provider || 'Default'}</p></div>
          <div><p className="text-[10px] font-semibold uppercase text-slate-500">OpenAI</p><p className={`mt-1 text-sm font-bold ${llmHealthQuery.data.openai_configured ? 'text-emerald-700 dark:text-emerald-300' : 'text-slate-500'}`}>{llmHealthQuery.data.openai_configured ? 'Configured' : 'Not configured'}</p></div>
          <div><p className="text-[10px] font-semibold uppercase text-slate-500">Anthropic</p><p className={`mt-1 text-sm font-bold ${llmHealthQuery.data.anthropic_configured ? 'text-emerald-700 dark:text-emerald-300' : 'text-slate-500'}`}>{llmHealthQuery.data.anthropic_configured ? 'Configured' : 'Not configured'}</p></div>
          <div><p className="text-[10px] font-semibold uppercase text-slate-500">Gemini</p><p className={`mt-1 text-sm font-bold ${llmHealthQuery.data.gemini_configured ? 'text-emerald-700 dark:text-emerald-300' : 'text-slate-500'}`}>{llmHealthQuery.data.gemini_configured ? 'Configured' : 'Not configured'}</p></div>
          <div><p className="text-[10px] font-semibold uppercase text-slate-500">Template fallback</p><p className="mt-1 text-sm font-bold text-slate-900 dark:text-slate-100">{llmHealthQuery.data.fallback_enabled ? 'Enabled' : 'Disabled'}</p></div>
        </div>}
        {llmTelemetryQuery.error && <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200">{llmTelemetryQuery.error.message}</div>}
        {llmTelemetryQuery.isLoading && <p role="status" className="text-xs text-slate-500">Loading recent model telemetry...</p>}
        {!llmTelemetryQuery.isLoading && !llmTelemetryQuery.error && (llmTelemetryQuery.data?.length || 0) === 0 && <p role="status" className="text-xs text-slate-500">No model telemetry has been recorded.</p>}
        {(llmTelemetryQuery.data?.length || 0) > 0 && <div className="overflow-x-auto border-y border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[780px] text-left text-xs">
            <thead><tr className="text-[10px] font-semibold uppercase text-slate-500"><th className="py-2 pr-3">Task</th><th className="py-2 pr-3">Model</th><th className="py-2 pr-3">Result</th><th className="py-2 pr-3 text-right">Latency</th><th className="py-2 pr-3 text-right">Tokens in/out</th><th className="py-2 pr-3 text-right">Est. cost</th><th className="py-2 text-right">Recorded</th></tr></thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">{llmTelemetryQuery.data?.map(record => <tr key={record.id}>
              <td className="max-w-40 truncate py-2 pr-3 font-semibold" title={record.task}>{record.task}</td>
              <td className="max-w-40 truncate py-2 pr-3" title={`${record.model_id} (${record.prompt_version})`}>{record.model_id}</td>
              <td className="py-2 pr-3">{record.validation_result}{record.operator_review_outcome ? ` / ${record.operator_review_outcome}` : ''}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{record.latency_ms.toLocaleString()} ms</td>
              <td className="py-2 pr-3 text-right tabular-nums">{record.input_tokens.toLocaleString()} / {record.output_tokens.toLocaleString()}</td>
              <td className="py-2 pr-3 text-right tabular-nums">${record.estimated_cost_usd.toFixed(6)}</td>
              <td className="py-2 text-right whitespace-nowrap">{new Date(record.created_at).toLocaleString()}</td>
            </tr>)}</tbody>
          </table>
        </div>}
      </section>}
      {canReviewExtractions && <section aria-labelledby="operator-extraction-reviews-title" className="space-y-4 border-y border-slate-200 py-5 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="operator-extraction-reviews-title" className="font-display text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-slate-100">OPERATOR EXTRACTION REVIEWS</h2>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span>{extractionReviews.length} pending</span>
            <button type="button" aria-label="Refresh extraction reviews" onClick={() => void extractionReviewsQuery.refetch()} className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-slate-300 px-2.5 font-semibold hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:hover:bg-slate-800">
              {extractionReviewsQuery.isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
              <span>Refresh</span>
            </button>
          </div>
        </div>
        {reviewNotice && <div role={reviewNoticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-md border p-3 text-xs ${reviewNoticeType === 'error' ? 'border-red-300 bg-red-50 text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200' : 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200'}`}>{reviewNotice}</div>}
        {extractionReviewsQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{extractionReviewsQuery.error.message}</span><button type="button" onClick={() => void extractionReviewsQuery.refetch()} className="font-bold underline">Retry</button></div>}
        {extractionReviewsQuery.isLoading && <p role="status" className="py-4 text-center text-xs text-slate-500">Loading operator reviews...</p>}
        {!extractionReviewsQuery.isLoading && !extractionReviewsQuery.error && extractionReviews.length === 0 && <p role="status" className="py-4 text-center text-xs text-slate-500">No pending extraction reviews.</p>}
        {extractionReviews.length > 0 && <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.6fr)]">
          <nav aria-label="Pending extraction reviews" className="space-y-1">
            {extractionReviews.map(review => <button key={review.id} type="button" aria-pressed={selectedReviewId === review.id} onClick={() => setSelectedReviewId(review.id)} className={`w-full rounded-md border px-3 py-2.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${selectedReviewId === review.id ? 'border-aero-blue bg-blue-50 dark:bg-aero-blue/10' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900'}`}>
              <span className="flex items-center justify-between gap-2 text-xs font-bold text-slate-900 dark:text-slate-100"><span>{review.id}</span><span className="text-[10px] font-semibold uppercase text-amber-700 dark:text-amber-300">{review.task || 'Review'}</span></span>
              <span className="mt-1 block truncate text-[11px] text-slate-600 dark:text-slate-400">{review.entity_id || review.reason || 'Pending operator decision'}</span>
            </button>)}
          </nav>
          <div aria-live="polite" className="min-w-0 border-l border-slate-200 pl-4 dark:border-slate-800">
            {extractionReviewQuery.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200"><span>{extractionReviewQuery.error.message}</span><button type="button" onClick={() => void extractionReviewQuery.refetch()} className="font-bold underline">Retry</button></div>}
            {extractionReviewQuery.isLoading && <p role="status" className="py-4 text-xs text-slate-500">Loading selected review...</p>}
            {!extractionReviewQuery.isLoading && !extractionReviewQuery.error && !selectedExtractionReview && <p role="status" className="py-4 text-xs text-slate-500">Select a pending review to inspect its source and extraction.</p>}
            {selectedExtractionReview && <div className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div><h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">{selectedExtractionReview.id}</h3><p className="mt-1 text-[11px] text-slate-500">{selectedExtractionReview.entity_id || selectedExtractionReview.task || 'Extraction review'}</p></div>
                <Badge variant="outline">{selectedExtractionReview.status}</Badge>
              </div>
              {selectedExtractionReview.reason && <p className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">{selectedExtractionReview.reason}</p>}
              {(selectedExtractionReview.hold_flags || []).length > 0 && <div className="flex flex-wrap gap-1.5">{selectedExtractionReview.hold_flags?.map(flag => <Badge key={flag} variant="outline">{flag}</Badge>)}</div>}
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="min-w-0 space-y-1"><h4 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Source text</h4><p className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-800 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200">{selectedExtractionReview.source_text || 'No source text recorded.'}</p></div>
                <div className="min-w-0 space-y-1"><h4 className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Extracted fields</h4><dl className="max-h-48 space-y-2 overflow-auto rounded-md border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-950">{Object.entries(selectedExtractionReview.extraction || {}).map(([field, value]) => <div key={field} className="grid grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)] gap-2 text-xs"><dt className="break-words font-semibold text-slate-600 dark:text-slate-400">{field}</dt><dd className="break-words text-slate-900 dark:text-slate-200">{formatReviewValue(value)}</dd></div>)}</dl></div>
              </div>
              {selectedExtractionReview.status === 'PENDING' && <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
                <label className="block space-y-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300"><span>Decision comments</span><textarea aria-label="Extraction review comments" value={reviewComments} onChange={event => setReviewComments(event.target.value)} rows={2} maxLength={1000} disabled={Boolean(reviewDecisionPending)} className="w-full resize-y rounded-md border border-slate-300 bg-white p-2 text-xs font-normal text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" /></label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={Boolean(reviewDecisionPending) || !selectedExtractionReview.extraction} aria-busy={reviewDecisionPending === 'approve'} onClick={() => void decideExtractionReview('approve')} className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-emerald-700 px-3 text-xs font-bold text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50">{reviewDecisionPending === 'approve' ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Check className="h-3.5 w-3.5" aria-hidden="true" />}<span>APPROVE EXTRACTION</span></button>
                  <button type="button" disabled={Boolean(reviewDecisionPending) || !reviewComments.trim()} aria-busy={reviewDecisionPending === 'reject'} onClick={() => void decideExtractionReview('reject')} className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-red-700 px-3 text-xs font-bold text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50">{reviewDecisionPending === 'reject' ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <XCircle className="h-3.5 w-3.5" aria-hidden="true" />}<span>REJECT EXTRACTION</span></button>
                </div>
              </div>}
            </div>}
          </div>
        </div>}
      </section>}
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
            </div>

            <div className="overflow-x-auto font-mono text-[10px]">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800">
                    <th className="pb-2">Order ID</th>
                    <th className="pb-2">Part Number</th>
                    <th className="pb-2 text-right">Clearance Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                  {loading && <tr><td colSpan={3} className="py-8 text-center text-slate-400">Loading trace records...</td></tr>}
                  {!loading && rfqs.length === 0 && <tr><td colSpan={3} className="py-8 text-center text-slate-400">No RFQ documentation records available.</td></tr>}
                  {rfqs.map(rfq => (
                    <tr key={rfq.id} onClick={() => setActiveTab(rfq.id)} onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setActiveTab(rfq.id);
                      }
                    }} tabIndex={0} role="button" className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-200">
                      <td className="py-2.5 text-aero-blue font-bold">{rfq.id}</td>
                      <td className="py-2.5">{rfq.part_number || (isFailedRfq(rfq) ? 'Extraction failed' : 'Pending extraction')}</td>
                      <td className="py-2.5 text-right"><span className={`px-2 py-0.5 rounded-full border font-bold ${isFailedRfq(rfq) ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/40' : 'bg-slate-100 dark:bg-slate-800 text-slate-500 border-slate-200 dark:border-slate-700'}`}>{rfqStatusLabel(rfq)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Document Vault Checklist */}
          <p role="status" className="border border-slate-200 bg-white p-5 text-sm text-slate-600 dark:border-slate-800 dark:bg-card-dark dark:text-slate-300">Per-RFQ certificate status is unavailable because the API does not expose a document checklist.</p>
        </div>

        <section role="status" className="lg:col-span-8 flex min-h-48 items-center border border-slate-200 bg-white p-5 text-sm text-slate-600 dark:border-slate-800 dark:bg-card-dark dark:text-slate-300">
          Document OCR evidence is unavailable from the live API. Certification and freeze actions are not available in this panel.
        </section>
      </div>

      {/* Bottom Grid: live compliance metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div role="status" className="lg:col-span-7 flex min-h-32 items-center border border-slate-200 bg-white p-5 text-sm text-slate-600 dark:border-slate-800 dark:bg-card-dark dark:text-slate-300">
          Persisted traceability milestones are unavailable because no milestone-history endpoint is connected.
        </div>
        {/* Right Bottom (5 cols): COMPLIANCE DASHBOARD OVERVIEW METRICS */}
        <div className="lg:col-span-5 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
            COMPLIANCE DASHBOARD OVERVIEW
          </h2>
          {complianceLoadError && <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700"><span>{complianceLoadError}</span><button type="button" onClick={() => void eventsQuery.refetch()} className="font-bold underline">Retry</button></div>}

          <div className="grid grid-cols-3 gap-3 text-center font-mono">
            <div className="bg-slate-50 dark:bg-slate-900 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="text-emerald-600 dark:text-emerald-400 font-extrabold text-xl">{loading ? '…' : loadError ? '—' : flaggedRfqCount}</div>
              <div className="text-[9px] text-slate-500 mt-1 uppercase leading-tight font-semibold">
                RFQS REQUIRING REVIEW
              </div>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="text-aero-blue font-extrabold text-xl">{loadingComplianceEvents ? '…' : complianceLoadError ? '—' : complianceEvents.length}</div>
              <div className="text-[9px] text-slate-500 mt-1 uppercase leading-tight font-semibold">
                COMPLIANCE EVENTS
              </div>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="text-amber-600 dark:text-amber-400 font-extrabold text-xl">{loadingComplianceEvents ? '…' : complianceLoadError ? '—' : latestComplianceEvent?.status || '—'}</div>
              <div className="text-[9px] text-slate-500 mt-1 uppercase leading-tight font-semibold">
                LATEST COMPLIANCE EVENT
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
