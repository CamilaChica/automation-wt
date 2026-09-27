import React, { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Clock3, FileSearch, Globe2, Headphones, Loader2, LogOut, Mail, Plane, Search, ShieldCheck } from 'lucide-react';
import { apiService, getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { BrandMark } from '../common/BrandMark';
import { CustomerVoiceContact } from './CustomerVoiceContact';
import { FloatingQa } from '../common/FloatingQa';
import { normalizeQuantityInput } from '../../utils/quantity';
import { customerLanguages, CustomerLanguage, getCustomerLanguagePreference, setCustomerLanguagePreference, translateCustomerPortal } from '../../i18n/customerPortal';
import { useCreatePurchaseOrder, useCreateRFQ, useShipmentTrace } from '../../hooks/useApiResources';

type CatalogResult = Awaited<ReturnType<typeof apiService.searchCatalog>>[number];

export const CustomerPortal: React.FC = () => {
  const [language, setLanguage] = useState<CustomerLanguage>(getCustomerLanguagePreference);
  const [isContactMenuOpen, setIsContactMenuOpen] = useState(false);
  const [isVoiceContactOpen, setIsVoiceContactOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogResult[]>([]);
  const [usingFallbackCatalog, setUsingFallbackCatalog] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');
  const [partNumber, setPartNumber] = useState('');
  const [condition, setCondition] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [details, setDetails] = useState('');
  const [agreementSigned, setAgreementSigned] = useState(false);
  const [partsListFile, setPartsListFile] = useState<File | null>(null);
  const [trackingStatus, setTrackingStatus] = useState<string | null>(null);
  const [quoteId, setQuoteId] = useState('');
  const [poNumber, setPoNumber] = useState('');
  const [exportCertificate, setExportCertificate] = useState<File | null>(null);
  const [kycForm, setKycForm] = useState<File | null>(null);
  const [poDocument, setPoDocument] = useState<File | null>(null);
  const [isSubmittingPo, setIsSubmittingPo] = useState(false);
  const [trackingToken, setTrackingToken] = useState('');
  const [requestedTrackingToken, setRequestedTrackingToken] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [noticeType, setNoticeType] = useState<'success' | 'error' | 'info'>('info');
  const createRfqMutation = useCreateRFQ();
  const purchaseOrderMutation = useCreatePurchaseOrder();
  const shipmentTraceQuery = useShipmentTrace(requestedTrackingToken);
  const shipment = shipmentTraceQuery.data;
  const isTracking = shipmentTraceQuery.isLoading;
  const t = (phrase: Parameters<typeof translateCustomerPortal>[1], values?: Record<string, string | number>) => translateCustomerPortal(language, phrase, values);

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
  }, [language]);

  const searchCatalog = async (value: string) => {
    if (!value.trim()) {
      setResults([]);
      setUsingFallbackCatalog(false);
      setNoticeType('info');
      setNotice(t('enterPartNumber'));
      return;
    }
    setIsSearching(true);
    try {
      const result = await apiService.searchCatalogWithSource(value, condition || undefined);
      setResults(result.results);
      setUsingFallbackCatalog(result.isFallback);
      setNotice(null);
    } catch (error) {
      setUsingFallbackCatalog(false);
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, t('catalogSearchFailed')));
    } finally {
      setIsSearching(false);
    }
  };

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault();
    void searchCatalog(query);
  };

  const handleRequest = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    if (!agreementSigned) {
      setNoticeType('error');
      setNotice(t('agreementRequired'));
      return;
    }
    setIsSubmitting(true);
    try {
      const attachmentIds = partsListFile ? [(await apiService.uploadAttachment(partsListFile)).attachment_id] : [];
      const response = await createRfqMutation.mutateAsync({
        raw_text: `Customer request for P/N ${partNumber}, quantity ${quantity}, condition ${condition}. ${details}`,
        customer_name: customerName,
        customer_email: customerEmail,
        attachment_ids: attachmentIds,
      });
      if (!response) return;
      setNotice(response.message || `Request ${response.rfq_id} received.`);
      setNoticeType('success');
      setTrackingStatus(t('processingFulfillment'));
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, t('rfqSubmissionFailed')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePurchaseOrder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmittingPo) return;
    if (!exportCertificate || !kycForm || !poDocument) {
      setNoticeType('error');
      setNotice('Upload the signed export certification, signed KYC form, and purchase order document before submitting.');
      return;
    }
    setIsSubmittingPo(true);
    try {
      const uploaded = await Promise.all([exportCertificate, kycForm, poDocument].map(file => apiService.uploadAttachment(file)));
      const poResponse = await purchaseOrderMutation.mutateAsync({
        quoteId,
        poNumber,
        customerEmail,
        attachmentIds: uploaded.map(item => item.attachment_id),
      });
      if (!poResponse) return;
      setNoticeType('success');
      setNotice(t('poReceived', { number: poNumber }));
      setQuoteId('');
      setPoNumber('');
      setExportCertificate(null);
      setKycForm(null);
      setPoDocument(null);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, t('purchaseOrderFailed')));
    } finally {
      setIsSubmittingPo(false);
    }
  };

  const handleTrackShipment = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!trackingToken.trim()) return;
    setNotice(null);
    if (requestedTrackingToken === trackingToken.trim()) void shipmentTraceQuery.refetch();
    else setRequestedTrackingToken(trackingToken.trim());
  };

  useEffect(() => {
    if (!requestedTrackingToken || !shipment) return;
    const refresh = window.setInterval(() => {
      void shipmentTraceQuery.refetch();
    }, 60000);
    return () => window.clearInterval(refresh);
  }, [requestedTrackingToken, shipment, shipmentTraceQuery.refetch]);

  return (
    <div lang={language} dir={language === 'ar' ? 'rtl' : 'ltr'} className="customer-portal-light min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white/95">
        <div className="mx-auto flex min-w-0 max-w-6xl items-center justify-between gap-2 px-3 py-3 sm:px-6 sm:py-5">
          <a href="/" className="flex min-w-0 shrink-0 items-center gap-2 sm:gap-3">
            <span className="shrink-0"><BrandMark /></span>
            <span className="hidden whitespace-nowrap font-display text-lg font-bold tracking-wide text-aero-blue md:inline">WINGED TYCOONS</span>
          </a>
          <div className="flex items-center gap-3 sm:gap-4">
            <label className="sr-only" htmlFor="customer-language">{t('language')}</label>
            <div className="relative flex shrink-0 items-center">
              <Globe2 aria-hidden="true" className="pointer-events-none absolute left-2.5 h-4 w-4 text-slate-500" />
              <select id="customer-language" aria-label={`${t('language')}: ${customerLanguages.find(option => option.code === language)?.label ?? language}`} title={`${t('language')}: ${customerLanguages.find(option => option.code === language)?.label ?? language}`} value={language} onChange={event => {
                const selectedLanguage = event.target.value as CustomerLanguage;
                setLanguage(selectedLanguage);
                setCustomerLanguagePreference(selectedLanguage);
              }} className="min-h-11 w-11 appearance-none border border-slate-300 bg-white py-2 pl-8 pr-1 text-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
                {customerLanguages.map(option => <option className="text-sm text-slate-900" key={option.code} value={option.code}>{option.label}</option>)}
              </select>
            </div>
            <div className="relative">
              <button
                type="button"
                aria-expanded={isContactMenuOpen}
                aria-haspopup="menu"
                onClick={() => setIsContactMenuOpen(open => !open)}
                className="inline-flex min-h-11 items-center gap-2 border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 hover:border-cyan-700 hover:text-cyan-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
              >
                {t('contactUs')} <ChevronDown className={`h-4 w-4 transition-transform ${isContactMenuOpen ? 'rotate-180' : ''}`} />
              </button>
              {isContactMenuOpen && <div role="menu" aria-label={t('contactUs')} className="absolute right-0 top-full z-30 mt-2 w-60 border border-slate-200 bg-white p-1 shadow-xl">
                <a role="menuitem" href="mailto:parts@wingedtycoons.com" onClick={() => setIsContactMenuOpen(false)} className="flex min-h-11 items-center gap-3 px-3 text-sm text-slate-700 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none">
                  <Mail className="h-4 w-4 text-cyan-800" /> {t('sendEmail')}
                </a>
                <button role="menuitem" type="button" onClick={() => { setIsContactMenuOpen(false); setIsVoiceContactOpen(true); }} className="flex min-h-11 w-full items-center gap-3 px-3 text-left text-sm text-slate-700 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none">
                  <Headphones className="h-4 w-4 text-cyan-800" /> {t('voiceContact')}
                </button>
              </div>}
            </div>
            <button type="button" aria-label={t('signOut')} title={t('signOut')} onClick={() => { void apiService.signOut().finally(() => { window.location.href = '/'; }); }} className="flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"><LogOut className="h-4 w-4" /><span className="hidden sm:inline">{t('signOut')}</span></button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-12 px-6 py-12">
        <section className="max-w-3xl">
          <p className="mb-3 text-xs font-bold uppercase tracking-[0.25em] text-cyan-700">{t('portalEyebrow')}</p>
          <h1 className="font-display text-4xl font-bold leading-tight md:text-6xl">{t('heroTitle')}</h1>
          <p className="mt-5 text-lg text-slate-600">{t('heroDescription')}</p>
        </section>

        <section className="grid gap-5 md:grid-cols-3">
          {[
            [Search, t('featureSearch'), t('featureSearchDescription')],
            [ShieldCheck, t('featureTrace'), t('featureTraceDescription')],
            [Clock3, t('featureFast'), t('featureFastDescription')]
          ].map(([Icon, title, description]) => (
            <div key={title as string} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <Icon className="mb-4 h-5 w-5 text-cyan-400" />
              <h2 className="font-display font-bold">{title as string}</h2>
              <p className="mt-2 text-sm text-slate-600">{description as string}</p>
            </div>
          ))}
        </section>

        <section className="grid min-w-0 gap-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
          <div className="min-w-0 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="font-display text-xl font-bold">{t('availability')}</h2>
                <p className="mt-1 text-sm text-slate-600">{t('availabilityNote')}</p>
              </div>
              <Plane className="h-6 w-6 text-cyan-400" />
            </div>
            <form onSubmit={handleSearch} className="flex gap-3">
              <label htmlFor="catalog-search" className="sr-only">{t('searchAircraftParts')}</label>
              <input id="catalog-search" name="catalog-search" autoComplete="off" aria-label={t('searchAircraftParts')} value={query} onChange={event => setQuery(event.target.value)} placeholder="e.g., 060-1234-00" className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <button disabled={isSearching} aria-busy={isSearching} className="rounded-xl bg-cyan-700 px-4 py-3 font-bold text-white hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60" aria-label={t('searchParts')}>{isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}</button>
            </form>
            {usingFallbackCatalog && <div role="status" className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900"><Badge variant="outline">SAMPLE / DEMO DATA</Badge><span>Catalog results are local samples and are not confirmed availability.</span></div>}
            <div className="mt-5 space-y-3">
              {isSearching && <p className="text-sm text-slate-600">{t('searching')}</p>}
              {!isSearching && results.length === 0 && <p className="text-sm text-slate-600">{t('noMatches')}</p>}
              {results.map((item, index) => (
                <button key={`${item.part_number}-${item.condition_code}-${index}`} onClick={() => setPartNumber(item.part_number)} className="w-full rounded-2xl border border-slate-200 bg-slate-50 p-4 text-left hover:border-cyan-400/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                  <div className="flex items-center justify-between gap-2"><span className="font-mono font-bold">{item.part_number}</span><span className="text-xs text-emerald-700">{item.quantity_available} {t('available')}</span></div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600"><span>{item.condition_code}</span><span>•</span><span>{item.certificate_type}</span><span>•</span><span>{item.has_full_trace ? t('fullTrace') : t('traceReview')}</span></div>
                </button>
              ))}
            </div>
          </div>

          <form aria-label={t('requestQuote')} onSubmit={handleRequest} className="min-w-0 rounded-3xl border border-cyan-400/30 bg-cyan-400/10 p-6">
            <h2 className="font-display text-xl font-bold">{t('requestQuote')}</h2>
            <p className="mt-1 text-sm text-slate-700">{t('requestPrompt')}</p>
            <div className="mt-5 space-y-3">
              <label htmlFor="customer-name" className="sr-only">{t('companyName')}</label>
              <input id="customer-name" name="customer-name" autoComplete="organization" aria-label={t('companyName')} required value={customerName} onChange={event => setCustomerName(event.target.value)} placeholder="e.g., Global Airlines" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <label htmlFor="customer-email" className="sr-only">{t('workEmail')}</label>
              <input id="customer-email" name="customer-email" autoComplete="email" aria-label={t('workEmail')} required type="email" value={customerEmail} onChange={event => setCustomerEmail(event.target.value)} placeholder="e.g., buyer@airline.com" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <div className="flex gap-3">
                <label htmlFor="rfq-part-number" className="sr-only">{t('partNumber')}</label>
                  <input id="rfq-part-number" name="part-number" aria-label={t('partNumber')} autoComplete="off" required value={partNumber} onChange={event => setPartNumber(event.target.value)} placeholder="e.g., BACB30LU-4" className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
                <label htmlFor="rfq-quantity" className="sr-only">{t('quantity')}</label>
                <input
                  id="rfq-quantity"
                  name="quantity"
                  required
                  type="number"
                  aria-label={t('quantity')}
                  min="1"
                  value={quantity}
                  onChange={event => setQuantity(normalizeQuantityInput(event.target.value))}
                  className="w-24 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none"
                />
              </div>
                <label htmlFor="rfq-condition" className="sr-only">{t('targetCondition')}</label>
                <select id="rfq-condition" name="condition" aria-label={t('targetCondition')} required value={condition} onChange={event => setCondition(event.target.value)} className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 focus:ring-2 focus:ring-cyan-400 focus:outline-none"><option value="">{t('selectCondition')}</option><option value="NE">{t('newCondition')}</option><option value="FN">{t('factoryNew')}</option><option value="NS">{t('newSurplus')}</option><option value="OH">{t('overhauled')}</option><option value="SVC">{t('serviceable')}</option><option value="RP">{t('repaired')}</option><option value="AR">{t('asRemoved')}</option><option value="IN">{t('inspected')}</option></select>
              <label htmlFor="rfq-details" className="sr-only">{t('rfqDetails')}</label>
              <textarea id="rfq-details" name="details" aria-label={t('rfqDetails')} autoComplete="off" value={details} onChange={event => setDetails(event.target.value)} placeholder={t('detailsPlaceholder')} rows={4} className="w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <label className="block rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-700">
                {t('partsList')}
                <input
                  id="compliance-file"
                  name="parts-list-file"
                  type="file"
                  accept=".csv,.xlsx,.pdf,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf"
                  onChange={event => setPartsListFile(event.target.files?.[0] ?? null)}
                  className="mt-2 block w-full text-xs text-slate-500"
                />
                {partsListFile && <span className="mt-2 block text-xs text-emerald-700">{t('readyUpload', { name: partsListFile.name })}</span>}
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  id="agreement-signed"
                  name="agreement-signed"
                  type="checkbox"
                  className="h-4 w-4 min-h-0 min-w-0 shrink-0 accent-cyan-700"
                  checked={agreementSigned}
                  onChange={event => setAgreementSigned(event.target.checked)}
                />
                {t('agreement')}
              </label>
              <button disabled={isSubmitting} aria-busy={isSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-cyan-700 px-4 py-3 font-bold text-white hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60">{isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowRight className="h-4 w-4" />} {isSubmitting ? t('sendingRequest') : t('sendRequest')}</button>
            </div>
            {notice && <p role={noticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`mt-4 flex gap-2 rounded-xl p-3 text-sm ${noticeType === 'error' ? 'bg-red-50 text-red-800' : 'bg-emerald-50 text-emerald-800'}`}>{noticeType === 'error' ? <AlertTriangle className="h-5 w-5 shrink-0" /> : <CheckCircle2 className="h-5 w-5 shrink-0" />}{notice}</p>}
            {trackingStatus && (
              <p className="mt-3 rounded-xl border border-cyan-400/40 bg-cyan-400/10 p-3 text-xs font-semibold text-cyan-300">
                {t('tracking')}: {trackingStatus}
              </p>
            )}
          </form>

          <form aria-label={t('purchaseOrder')} onSubmit={handlePurchaseOrder} className="min-w-0 rounded-3xl border border-emerald-400/30 bg-emerald-400/10 p-6">
            <h2 className="font-display text-xl font-bold">{t('purchaseOrder')}</h2>
            <p className="mt-1 text-sm text-slate-700">{t('purchaseOrderDescription')}</p>
            <div className="mt-5 space-y-3">
              <label htmlFor="quote-id" className="sr-only">{t('quoteReference')}</label>
              <input id="quote-id" name="quote-id" autoComplete="off" required disabled={isSubmittingPo} value={quoteId} onChange={event => setQuoteId(event.target.value)} placeholder="e.g., QTE-123456" className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none disabled:opacity-60" />
              <label htmlFor="po-number" className="sr-only">{t('poNumber')}</label>
              <input id="po-number" name="po-number" autoComplete="off" required disabled={isSubmittingPo} value={poNumber} onChange={event => setPoNumber(event.target.value)} placeholder="e.g., PO-1001" className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none disabled:opacity-60" />
              <label htmlFor="po-email" className="sr-only">{t('poEmail')}</label>
              <input id="po-email" name="po-email" autoComplete="email" required disabled={isSubmittingPo} type="email" value={customerEmail} onChange={event => setCustomerEmail(event.target.value)} placeholder="e.g., buyer@airline.com" className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none disabled:opacity-60" />
              <div className="rounded-xl border border-slate-300 bg-white p-3 text-xs text-slate-700"><p className="font-semibold">{t('requiredDocuments')}</p><div className="mt-2 flex flex-wrap gap-3"><a className="text-emerald-800 underline" href="/documents/WingedTycoons-Export-Compliance-Certification.pdf" download>{t('downloadExport')}</a><a className="text-emerald-800 underline" href="/documents/WingedTycoons-KYC-Form.pdf" download>{t('downloadKyc')}</a></div></div>
              <label htmlFor="po-export" className="block text-xs text-slate-700">{t('signedExport')}<input id="po-export" name="po-export" required disabled={isSubmittingPo} type="file" accept=".pdf,application/pdf" onChange={event => setExportCertificate(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs disabled:opacity-60" /></label>
              <label htmlFor="po-kyc" className="block text-xs text-slate-700">{t('signedKyc')}<input id="po-kyc" name="po-kyc" required disabled={isSubmittingPo} type="file" accept=".pdf,application/pdf" onChange={event => setKycForm(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs disabled:opacity-60" /></label>
              <label htmlFor="po-document" className="block text-xs text-slate-700">{t('poDocument')}<input id="po-document" name="po-document" required disabled={isSubmittingPo} type="file" accept=".pdf,application/pdf" onChange={event => setPoDocument(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs disabled:opacity-60" /></label>
              <button disabled={isSubmittingPo} aria-busy={isSubmittingPo} className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60">{isSubmittingPo ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowRight className="h-4 w-4" />} {isSubmittingPo ? t('sendingPo') : t('submitPo')}</button>
            </div>
          </form>

          <form aria-label={t('trackShipment')} onSubmit={handleTrackShipment} className="min-w-0 rounded-3xl border border-slate-200 bg-white p-6">
            <h2 className="font-display text-xl font-bold">{t('trackShipment')}</h2>
            <p className="mt-1 text-sm text-slate-600">{t('trackingTokenPlaceholder')}</p>
            <div className="mt-5 flex gap-3">
              <label htmlFor="tracking-token" className="sr-only">{t('trackingToken')}</label>
              <input id="tracking-token" name="tracking-token" autoComplete="off" aria-label={t('trackingToken')} required value={trackingToken} onChange={event => setTrackingToken(event.target.value)} placeholder={t('trackingTokenPlaceholder')} className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <button disabled={isTracking} className="rounded-xl bg-cyan-700 px-4 py-3 font-bold text-white disabled:opacity-60" aria-label={t('trackShipment')}>{isTracking ? '...' : t('track')}</button>
            </div>
            {shipmentTraceQuery.error && <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">{getApiErrorMessage(shipmentTraceQuery.error, t('trackingFailed'))}<button type="button" onClick={() => void shipmentTraceQuery.refetch()} className="ml-2 font-bold underline">Retry</button></div>}
            {shipment && (
              <div className="mt-4 rounded-xl border border-slate-700 bg-slate-950 p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-display text-lg font-bold text-cyan-700">{shipment.status}</div>
                  <span className="rounded-full border border-emerald-700/40 bg-emerald-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-emerald-800">{t('liveStatus')}</span>
                </div>
                <div className="mt-3 grid gap-2 text-slate-600 sm:grid-cols-2">
                  <div>{t('carrier')}: <span className="text-slate-900">{shipment.carrier || t('preparing')}</span></div>
                  <div>{t('tracking')}: <span className="font-mono text-slate-900">{shipment.tracking_number || t('pending')}</span></div>
                  <div>{t('latestLocation')}: <span className="text-slate-900">{shipment.events?.[shipment.events.length - 1]?.location || t('pendingUpdate')}</span></div>
                  <div>{t('estimatedDelivery')}: <span className="text-slate-900">{shipment.estimated_delivery || t('toBeConfirmed')}</span></div>
                </div>
                <div className="mt-5 border-l border-slate-300 pl-4">
                  {(shipment.events || []).slice().reverse().map((event, index: number) => (
                    <div key={`${event.id}-${index}`} className="relative pb-4 last:pb-0">
                      <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-cyan-700 ring-4 ring-white" />
                      <div className="font-semibold text-slate-900">{event.status}</div>
                      <div className="text-xs text-slate-600">{event.description}</div>
                      {event.location && <div className="mt-1 text-xs text-cyan-800">{event.location}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </form>
        </section>

        <footer className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-800 pt-6 text-xs text-slate-500">
          <span>{t('portalFooter')}</span>
          <span>{t('availabilityConfirmed')}</span>
          <a href="/internal" className="flex items-center gap-1 hover:text-slate-900"><FileSearch className="h-3.5 w-3.5" /> {t('teamSignIn')}</a>
        </footer>
      </main>
      <CustomerVoiceContact uiLanguage={language} isOpen={isVoiceContactOpen} onClose={() => setIsVoiceContactOpen(false)} />
      <FloatingQa audience="client" language={language} />
    </div>
  );
};
