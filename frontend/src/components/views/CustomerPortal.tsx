import React, { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Clock3, FileSearch, Globe2, Headphones, Loader2, LogOut, Mail, Plane, Search, ShieldCheck, X } from 'lucide-react';
import { apiService, getApiErrorMessage } from '../../services/api';
import { Badge } from '../common/Badge';
import { BrandMark } from '../common/BrandMark';
import { CustomerVoiceContact } from './CustomerVoiceContact';
import { FloatingQa } from '../common/FloatingQa';
import { normalizeQuantityInput } from '../../utils/quantity';
import { customerLanguages, CustomerLanguage, getCustomerLanguagePreference, setCustomerLanguagePreference, translateCustomerPortal } from '../../i18n/customerPortal';
import { useCreatePurchaseOrder, useCreateRFQ, useShipmentTrace } from '../../hooks/useApiResources';
import { CatalogItem, StockHold } from '../../types';

function formatHoldTime(totalSecs: number): string {
  const clamped = Math.max(0, totalSecs);
  const hrs = Math.floor(clamped / 3600);
  const mins = Math.floor((clamped % 3600) / 60);
  const secs = clamped % 60;
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${pad(hrs)}:${pad(mins)}:${pad(secs)}`;
}

type CatalogResult = CatalogItem;

const PO_FILE_EXTENSIONS = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'];
const PO_FILE_ACCEPT = '.pdf,.doc,.docx,.jpg,.jpeg,.png,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png';
const PO_MAX_BYTES = 25 * 1024 * 1024;

export const CustomerPortal: React.FC = () => {
  const [language, setLanguage] = useState<CustomerLanguage>(getCustomerLanguagePreference);
  const [isContactMenuOpen, setIsContactMenuOpen] = useState(false);
  const [isVoiceContactOpen, setIsVoiceContactOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogResult[]>([]);
  const [usingFallbackCatalog, setUsingFallbackCatalog] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [loginEmail, setLoginEmail] = useState(() => apiService.getUserEmail() || '');
  const [customerEmail, setCustomerEmail] = useState(loginEmail);
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
  const [poNotice, setPoNotice] = useState('');
  const [poNoticeType, setPoNoticeType] = useState<'success' | 'error'>('success');
  const [poFormKey, setPoFormKey] = useState(0);
  const [trackingToken, setTrackingToken] = useState('');
  const [requestedTrackingToken, setRequestedTrackingToken] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [requestFormKey, setRequestFormKey] = useState(0);
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
    let active = true;
    apiService.validateSession().then(() => {
      const email = apiService.getUserEmail() || '';
      if (active && email) {
        setLoginEmail(email);
        setCustomerEmail(email);
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
  }, [language]);

  // Stock Hold & Slide-Out Drawer State
  const [isBuyDrawerOpen, setIsBuyDrawerOpen] = useState(false);
  const [activeHold, setActiveHold] = useState<StockHold | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [drawerPoNumber, setDrawerPoNumber] = useState('');
  const [drawerPoFile, setDrawerPoFile] = useState<File | null>(null);
  const [drawerExportFile, setDrawerExportFile] = useState<File | null>(null);
  const [drawerKycFile, setDrawerKycFile] = useState<File | null>(null);
  const [drawerAgreementSigned, setDrawerAgreementSigned] = useState(false);
  const [drawerCarrierNotes, setDrawerCarrierNotes] = useState('');
  const [isSubmittingDrawerPo, setIsSubmittingDrawerPo] = useState(false);
  const [drawerNotice, setDrawerNotice] = useState<string | null>(null);
  const [drawerNoticeType, setDrawerNoticeType] = useState<'success' | 'error'>('success');
  const [drawerFormKey, setDrawerFormKey] = useState(0);

  // Check for active stock hold on mount
  useEffect(() => {
    let active = true;
    apiService.getActiveStockHold().then((hold) => {
      if (active && hold && hold.remaining_seconds > 0) {
        setActiveHold(hold);
        setRemainingSeconds(hold.remaining_seconds);
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  // Real-time ticking countdown timer
  useEffect(() => {
    if (!activeHold || remainingSeconds <= 0) return;
    const interval = window.setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev <= 1) {
          window.clearInterval(interval);
          setActiveHold(null);
          setIsBuyDrawerOpen(false);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(interval);
  }, [activeHold, remainingSeconds]);

  const handleOpenBuyDrawer = async (item: CatalogItem) => {
    try {
      const hold = await apiService.createStockHold({
        part_number: item.part_number,
        quote_number: item.today_quote_reference || '',
        unit_price: item.today_quoted_price || 0,
        quantity: 1,
        condition: item.today_condition || item.condition_code,
        certification: item.today_certification || item.certificate_type,
        lead_time: item.today_lead_time || 'Stock',
        company_name: customerName || '',
        rfq_id: item.rfq_id,
      });
      setActiveHold(hold);
      setRemainingSeconds(hold.remaining_seconds);
      setDrawerNotice(null);
      setIsBuyDrawerOpen(true);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, 'Could not reserve stock. Please try again.'));
    }
  };

  const handleDrawerPoSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmittingDrawerPo || !activeHold) return;
    setDrawerNotice(null);

    if (!drawerAgreementSigned) {
      setDrawerNoticeType('error');
      setDrawerNotice('Please confirm the compliance and export control agreement before submitting.');
      return;
    }
    if (!drawerPoNumber.trim()) {
      setDrawerNoticeType('error');
      setDrawerNotice('Purchase order number is required.');
      return;
    }
    if (!drawerPoFile) {
      setDrawerNoticeType('error');
      setDrawerNotice('Please attach your official purchase order document (PDF, Word, or image).');
      return;
    }
    if (!drawerExportFile) {
      setDrawerNoticeType('error');
      setDrawerNotice('Please upload the signed Export Compliance certification.');
      return;
    }
    if (!drawerKycFile) {
      setDrawerNoticeType('error');
      setDrawerNotice('Please upload the completed KYC form.');
      return;
    }

    setIsSubmittingDrawerPo(true);
    try {
      const uploadedIds: string[] = [];
      for (const file of [drawerPoFile, drawerExportFile, drawerKycFile]) {
        const res = await apiService.uploadAttachment(file);
        uploadedIds.push(res.attachment_id);
      }

      await purchaseOrderMutation.mutateAsync({
        quoteId: activeHold.quote_number,
        poNumber: drawerPoNumber.trim(),
        customerEmail: customerEmail.trim() || loginEmail,
        attachmentIds: uploadedIds,
      });

      setDrawerNoticeType('success');
      setDrawerNotice(`PO Received — Order #${drawerPoNumber.trim()} Confirmed. Stock locked and procurement notified.`);
      setActiveHold(null);
      setRemainingSeconds(0);
      setDrawerPoNumber('');
      setDrawerPoFile(null);
      setDrawerExportFile(null);
      setDrawerKycFile(null);
      setDrawerAgreementSigned(false);
      setDrawerCarrierNotes('');
      setDrawerFormKey((k) => k + 1);
    } catch (error) {
      setDrawerNoticeType('error');
      setDrawerNotice(getApiErrorMessage(error, 'Could not submit purchase order. Please verify required files and try again.'));
    } finally {
      setIsSubmittingDrawerPo(false);
    }
  };

  const searchCatalog = async (value: string) => {
    if (!value.trim()) {
      setResults([]);
      setUsingFallbackCatalog(false);
      setNoticeType('info');
      setNotice(t('enterPartNumber'));
      return;
    }
    setIsSearching(true);
    setHasSearched(true);
    try {
      const result = await apiService.searchCatalogWithSource(value);
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
    if (!customerName.trim() || !customerEmail.trim()) {
      setNoticeType('error');
      setNotice('Company name and email are required.');
      return;
    }
    if (!partNumber.trim() && !partsListFile) {
      setNoticeType('error');
      setNotice('Enter a part number or upload a parts list.');
      return;
    }
    setIsSubmitting(true);
    try {
      let attachmentIds: string[] = [];
      if (partsListFile) {
        try {
          attachmentIds = [(await apiService.uploadAttachment(partsListFile)).attachment_id];
        } catch (error) {
          setNoticeType('error');
          setNotice(getApiErrorMessage(error, 'The file could not be uploaded. Please use a CSV or Excel file under 25 MB.'));
          return;
        }
      }
      const partText = partNumber.trim()
        ? `Customer request for P/N ${partNumber.trim()}, quantity ${quantity}, condition ${condition || 'any'}.`
        : `Customer parts list attached (${partsListFile?.name}).${condition ? ` Target condition ${condition}.` : ''}`;
      const response = await createRfqMutation.mutateAsync({
        raw_text: `${partText} ${details}`.trim(),
        customer_name: customerName.trim(),
        customer_email: customerEmail.trim(),
        attachment_ids: attachmentIds,
      });
      if (!response) return;
      setNotice(response.message || `Request ${response.rfq_id} received.`);
      setNoticeType('success');
      setTrackingStatus(t('processingFulfillment'));
      setPartNumber('');
      setQuantity(1);
      setCondition('');
      setDetails('');
      setPartsListFile(null);
      setCustomerName('');
      setCustomerEmail(loginEmail);
      setAgreementSigned(false);
      setRequestFormKey(key => key + 1);
    } catch (error) {
      setNoticeType('error');
      setNotice(getApiErrorMessage(error, t('rfqSubmissionFailed')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const pickPoFile = (event: React.ChangeEvent<HTMLInputElement>, setFile: (file: File | null) => void) => {
    const file = event.target.files?.[0] ?? null;
    if (file) {
      const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
      const problem = !PO_FILE_EXTENSIONS.includes(extension)
        ? `"${file.name}" is not supported. Please attach a PDF, Word (.docx/.doc), JPG or PNG file.`
        : file.size > PO_MAX_BYTES
          ? `"${file.name}" is larger than 25 MB. Please attach a smaller file.`
          : file.size === 0 ? `"${file.name}" is empty. Please attach the signed document.` : '';
      if (problem) {
        event.target.value = '';
        setFile(null);
        setPoNoticeType('error');
        setPoNotice(problem);
        return;
      }
    }
    setPoNotice('');
    setFile(file);
  };

  const handlePurchaseOrder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmittingPo) return;
    setPoNotice('');
    if (!poDocument) {
      setPoNoticeType('error');
      setPoNotice('Please attach your purchase order document (PDF, Word, JPG or PNG).');
      return;
    }
    setIsSubmittingPo(true);
    try {
      const uploaded = [];
      for (const file of [poDocument, exportCertificate, kycForm].filter((item): item is File => Boolean(item))) {
        try {
          uploaded.push(await apiService.uploadAttachment(file));
        } catch (uploadError) {
          throw new Error(`Could not upload "${file.name}": ${getApiErrorMessage(uploadError, 'please try again.')}`);
        }
      }
      const poResponse = await purchaseOrderMutation.mutateAsync({
        quoteId,
        poNumber,
        customerEmail,
        attachmentIds: uploaded.map(item => item.attachment_id),
      });
      if (!poResponse) return;
      setPoNoticeType('success');
      setPoNotice(t('poReceived', { number: poNumber }));
      setQuoteId('');
      setPoNumber('');
      setExportCertificate(null);
      setKycForm(null);
      setPoDocument(null);
      setPoFormKey(key => key + 1);
    } catch (error) {
      setPoNoticeType('error');
      setPoNotice(error instanceof Error && !('isAxiosError' in error) ? error.message : getApiErrorMessage(error, t('purchaseOrderFailed')));
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
              <button disabled={isSearching || !query.trim()} aria-busy={isSearching} className="rounded-xl bg-cyan-700 px-4 py-3 font-bold text-white hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60" aria-label={t('searchParts')}>{isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}</button>
            </form>
            {usingFallbackCatalog && <div role="status" className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900"><Badge variant="outline">SAMPLE / DEMO DATA</Badge><span>Catalog results are local samples and are not confirmed availability.</span></div>}
            <div className="mt-5 space-y-3">
              {isSearching && <p className="text-sm text-slate-600">{t('searching')}</p>}
              {!isSearching && results.length === 0 && <p className="text-sm text-slate-600">{hasSearched ? t('noMatches') : t('welcomeSearch')}</p>}
              {results.map((item, index) => (
                <div
                  key={`${item.part_number}-${item.condition_code}-${index}`}
                  onClick={() => setPartNumber(item.part_number)}
                  className="w-full rounded-2xl border border-slate-200 bg-slate-50 p-4 text-left hover:border-cyan-400/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 cursor-pointer transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <span className="font-mono text-base font-bold text-slate-900">{item.part_number}</span>
                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-600">
                        <span>{item.condition_code}</span>
                        <span>•</span>
                        <span>{item.certificate_type}</span>
                        <span>•</span>
                        <span>{item.has_full_trace ? t('fullTrace') : t('traceReview')}</span>
                      </div>
                    </div>
                    <div className="flex flex-col items-end shrink-0">
                      <span className="text-xs font-semibold text-emerald-700">{item.quantity_available} {t('available')}</span>
                      {item.quoted_today && (
                        <div className="mt-1.5 flex flex-col items-end w-full">
                          <button
                            type="button"
                            id={`buy-btn-${item.part_number}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleOpenBuyDrawer(item);
                            }}
                            className="w-full rounded-lg border-b-2 border-emerald-800 bg-gradient-to-b from-emerald-500 to-emerald-600 px-3 py-1 text-center font-display text-xs font-bold text-white shadow-sm transition-all hover:brightness-110 active:translate-y-0.5 active:border-b-0"
                          >
                            Buy — ${Number(item.today_quoted_price || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </button>
                          <span className="mt-1 text-[10px] font-medium tracking-tight text-slate-500 whitespace-nowrap">
                            Quoted Today • Ref: {item.today_quote_reference}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <form aria-label={t('requestQuote')} onSubmit={handleRequest} className="min-w-0 rounded-3xl border border-cyan-400/30 bg-cyan-400/10 p-6">
            <h2 className="font-display text-xl font-bold">{t('requestQuote')}</h2>
            <p className="mt-1 text-sm text-slate-700">{t('requestPrompt')}</p>
            <div className="mt-5 space-y-3">
              <label htmlFor="customer-name" className="block text-xs font-semibold text-slate-700">{t('companyName')} <span className="text-red-600" aria-hidden="true">*</span></label>
              <input id="customer-name" name="customer-name" autoComplete="organization" aria-label={t('companyName')} aria-required="true" required value={customerName} onChange={event => setCustomerName(event.target.value)} placeholder="e.g., Global Airlines" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <label htmlFor="customer-email" className="block text-xs font-semibold text-slate-700">{t('workEmail')} <span className="text-red-600" aria-hidden="true">*</span></label>
              <input id="customer-email" name="customer-email" autoComplete="email" aria-label={t('workEmail')} aria-required="true" required type="email" value={customerEmail} readOnly={Boolean(loginEmail)} title={loginEmail ? 'Signed-in email' : undefined} onChange={event => { if (!loginEmail) setCustomerEmail(event.target.value); }} placeholder="e.g., buyer@airline.com" className={`w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none ${loginEmail ? 'cursor-not-allowed text-slate-400' : ''}`} />
              <div className="flex gap-3">
                <label htmlFor="rfq-part-number" className="sr-only">{t('partNumber')}</label>
                  <input id="rfq-part-number" name="part-number" aria-label={t('partNumber')} autoComplete="off" required={!partsListFile} value={partNumber} onChange={event => setPartNumber(event.target.value)} placeholder="e.g., BACB30LU-4" className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
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
                <select id="rfq-condition" name="condition" aria-label={t('targetCondition')} required={!partsListFile} value={condition} onChange={event => setCondition(event.target.value)} className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 focus:ring-2 focus:ring-cyan-400 focus:outline-none"><option value="">{t('selectCondition')}</option><option value="NE">{t('newCondition')}</option><option value="FN">{t('factoryNew')}</option><option value="NS">{t('newSurplus')}</option><option value="OH">{t('overhauled')}</option><option value="SVC">{t('serviceable')}</option><option value="RP">{t('repaired')}</option><option value="AR">{t('asRemoved')}</option><option value="IN">{t('inspected')}</option></select>
              <label htmlFor="rfq-details" className="sr-only">{t('rfqDetails')}</label>
              <textarea id="rfq-details" name="details" aria-label={t('rfqDetails')} autoComplete="off" value={details} onChange={event => setDetails(event.target.value)} placeholder={t('detailsPlaceholder')} rows={4} className="w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <label className="block rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-700">
                {t('partsList')}
                <input
                  key={requestFormKey}
                  id="compliance-file"
                  name="parts-list-file"
                  type="file"
                  accept=".csv,.xlsx,.xls,.pdf,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf"
                  onChange={event => {
                    const file = event.target.files?.[0] ?? null;
                    if (file && (!/\.(csv|xlsx|xls|pdf)$/i.test(file.name) || file.size > 25 * 1024 * 1024)) {
                      setNoticeType('error');
                      setNotice('Please upload a CSV, Excel (.xlsx/.xls) or PDF file under 25 MB.');
                      event.target.value = '';
                      setPartsListFile(null);
                      return;
                    }
                    setPartsListFile(file);
                  }}
                  className="mt-2 block w-full text-xs text-slate-500"
                />
                <span className="mt-1 block text-xs text-slate-500">CSV or Excel (.xlsx, .xls), max 25 MB</span>
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
              <input id="quote-id" name="quote-id" autoComplete="off" required disabled={isSubmittingPo} value={quoteId} onChange={event => setQuoteId(event.target.value)} placeholder="Quote or RFQ number, e.g., RFQ-75478E" className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none disabled:opacity-60" />
              <label htmlFor="po-number" className="sr-only">{t('poNumber')}</label>
              <input id="po-number" name="po-number" autoComplete="off" required disabled={isSubmittingPo} value={poNumber} onChange={event => setPoNumber(event.target.value)} placeholder="e.g., PO-1001" className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none disabled:opacity-60" />
              <label htmlFor="po-email" className="sr-only">{t('poEmail')}</label>
              <input id="po-email" name="po-email" autoComplete="email" required disabled={isSubmittingPo} type="email" value={customerEmail} readOnly={Boolean(loginEmail)} title={loginEmail ? 'Signed-in email' : undefined} onChange={event => { if (!loginEmail) setCustomerEmail(event.target.value); }} placeholder="e.g., buyer@airline.com" className={`w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none disabled:opacity-60 ${loginEmail ? 'cursor-not-allowed text-slate-500' : ''}`} />
              <div className="rounded-xl border border-slate-300 bg-white p-3 text-xs text-slate-700"><p className="font-semibold">{t('requiredDocuments')}</p><div className="mt-2 flex flex-wrap gap-3"><a className="text-emerald-800 underline" href="/documents/WingedTycoons-Export-Compliance-Certification.pdf" download>{t('downloadExport')}</a><a className="text-emerald-800 underline" href="/documents/WingedTycoons-KYC-Form.pdf" download>{t('downloadKyc')}</a></div></div>
              <div key={poFormKey} className="space-y-3">
                <label htmlFor="po-document" className="block text-xs text-slate-700">{t('poDocument')} <span className="text-red-600" aria-hidden="true">*</span><input id="po-document" name="po-document" disabled={isSubmittingPo} type="file" accept={PO_FILE_ACCEPT} onChange={event => pickPoFile(event, setPoDocument)} className="mt-1 block w-full text-xs disabled:opacity-60" />{poDocument && <span className="mt-1 block text-emerald-800">✓ {poDocument.name}</span>}</label>
                <label htmlFor="po-export" className="block text-xs text-slate-700">{t('signedExport')} (optional)<input id="po-export" name="po-export" disabled={isSubmittingPo} type="file" accept={PO_FILE_ACCEPT} onChange={event => pickPoFile(event, setExportCertificate)} className="mt-1 block w-full text-xs disabled:opacity-60" />{exportCertificate && <span className="mt-1 block text-emerald-800">✓ {exportCertificate.name}</span>}</label>
                <label htmlFor="po-kyc" className="block text-xs text-slate-700">{t('signedKyc')} (optional)<input id="po-kyc" name="po-kyc" disabled={isSubmittingPo} type="file" accept={PO_FILE_ACCEPT} onChange={event => pickPoFile(event, setKycForm)} className="mt-1 block w-full text-xs disabled:opacity-60" />{kycForm && <span className="mt-1 block text-emerald-800">✓ {kycForm.name}</span>}</label>
              </div>
              <button disabled={isSubmittingPo} aria-busy={isSubmittingPo} className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60">{isSubmittingPo ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowRight className="h-4 w-4" />} {isSubmittingPo ? t('sendingPo') : t('submitPo')}</button>
            </div>
            {poNotice && <p role={poNoticeType === 'error' ? 'alert' : 'status'} aria-live="polite" className={`mt-4 flex gap-2 rounded-xl p-3 text-sm ${poNoticeType === 'error' ? 'bg-red-50 text-red-800' : 'bg-emerald-50 text-emerald-800'}`}>{poNoticeType === 'error' ? <AlertTriangle className="h-5 w-5 shrink-0" /> : <CheckCircle2 className="h-5 w-5 shrink-0" />}{poNotice}</p>}
          </form>

          <form aria-label={t('trackShipment')} onSubmit={handleTrackShipment} className="min-w-0 rounded-3xl border border-slate-200 bg-white p-6">
            <h2 className="font-display text-xl font-bold">{t('trackShipment')}</h2>
            <p className="mt-1 text-sm text-slate-600">{t('trackingTokenPlaceholder')}</p>
            <div className="mt-5 flex gap-3">
              <label htmlFor="tracking-token" className="sr-only">{t('trackingToken')}</label>
              <input id="tracking-token" name="tracking-token" autoComplete="off" aria-label={t('trackingToken')} required value={trackingToken} onChange={event => setTrackingToken(event.target.value)} placeholder={t('trackingTokenPlaceholder')} className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <button disabled={isTracking || !trackingToken.trim()} className="rounded-xl bg-cyan-700 px-4 py-3 font-bold text-white disabled:opacity-60" aria-label={t('trackShipment')}>{isTracking ? '...' : t('track')}</button>
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
                {shipment.tracking_url && (
                  <a href={shipment.tracking_url} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex rounded-xl bg-cyan-700 px-4 py-2 text-sm font-bold text-white hover:bg-cyan-800">View live status on {shipment.carrier} →</a>
                )}
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

      {/* Floating Timer Pill (Edge Case: Drawer closed with active hold) */}
      {activeHold && !isBuyDrawerOpen && remainingSeconds > 0 && (
        <aside
          aria-label="Active Stock Hold"
          className="fixed bottom-6 right-6 z-40 flex items-center gap-3 rounded-full border border-emerald-300 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-950 shadow-xl backdrop-blur transition-all"
        >
          <span>Hold active for {activeHold.part_number}: {formatHoldTime(remainingSeconds)}</span>
          <button
            type="button"
            onClick={() => setIsBuyDrawerOpen(true)}
            className="rounded-full bg-emerald-700 px-3 py-1 text-xs font-bold text-white hover:bg-emerald-800 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          >
            Resume PO
          </button>
        </aside>
      )}

      {/* Slide-Out Drawer for Instant Purchase Order Checkout */}
      {isBuyDrawerOpen && activeHold && (
        <div className="fixed inset-0 z-50 overflow-hidden" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity"
            onClick={() => setIsBuyDrawerOpen(false)}
            aria-hidden="true"
          />
          <div className="fixed inset-y-0 right-0 flex max-w-full pl-6 sm:pl-10">
            <div className="w-screen max-w-xl bg-white shadow-2xl flex flex-col">
              {/* Drawer Header */}
              <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-5 w-5 text-emerald-600" />
                  <h2 id="drawer-title" className="font-display text-lg font-bold text-slate-900">Purchase Order Checkout</h2>
                </div>
                <button
                  type="button"
                  onClick={() => setIsBuyDrawerOpen(false)}
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none"
                  aria-label="Close drawer"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Drawer Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {/* Section 1: Live Stock Reservation Banner */}
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-display text-sm font-bold text-emerald-950">
                      Stock Reserved for {activeHold.company_name || customerName || 'Your Company'} — {formatHoldTime(remainingSeconds)} remaining
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-emerald-800">
                    This unit is held exclusively for your team at today’s quoted price.
                  </p>
                  <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-emerald-200/60">
                    <div
                      className="h-full rounded-full bg-emerald-600 transition-all duration-1000"
                      style={{ width: `${Math.min(100, Math.max(0, (remainingSeconds / 7200) * 100))}%` }}
                    />
                  </div>
                </div>

                {/* Section 2: Locked Quote Summary */}
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Quote Reference</span>
                    <span className="font-mono text-sm font-bold text-slate-900">{activeHold.quote_number}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <span className="text-slate-500">Part Number</span>
                      <p className="font-mono font-bold text-slate-900">{activeHold.part_number}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Condition & Certification</span>
                      <p className="font-semibold text-slate-900">{activeHold.condition} • {activeHold.certification}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Locked Price</span>
                      <p className="font-bold text-emerald-700">
                        ${Number(activeHold.unit_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
                        <span className="text-slate-500 font-normal"> (Qty: {activeHold.quantity} EA)</span>
                      </p>
                    </div>
                    <div>
                      <span className="text-slate-500">Quoted Lead Time</span>
                      <p className="font-semibold text-slate-900">{activeHold.lead_time}</p>
                    </div>
                  </div>
                </div>

                {/* Section 3: Fast PO Submission & Compliance */}
                <form key={drawerFormKey} onSubmit={handleDrawerPoSubmit} className="space-y-4">
                  <h3 className="font-display text-sm font-bold text-slate-900 uppercase tracking-wider">Purchase Order & Compliance</h3>

                  <div>
                    <label htmlFor="drawer-po-number" className="block text-xs font-semibold text-slate-700">
                      Customer Purchase Order Number <span className="text-red-600">*</span>
                    </label>
                    <input
                      id="drawer-po-number"
                      name="drawer-po-number"
                      required
                      disabled={isSubmittingDrawerPo}
                      value={drawerPoNumber}
                      onChange={(e) => setDrawerPoNumber(e.target.value)}
                      placeholder="e.g., PO-2026-9810"
                      className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500"
                    />
                  </div>

                  <div>
                    <label htmlFor="drawer-po-email" className="block text-xs font-semibold text-slate-700">
                      Work Email <span className="text-red-600">*</span>
                    </label>
                    <input
                      id="drawer-po-email"
                      name="drawer-po-email"
                      type="email"
                      required
                      disabled={isSubmittingDrawerPo || Boolean(loginEmail)}
                      value={customerEmail}
                      onChange={(e) => { if (!loginEmail) setCustomerEmail(e.target.value); }}
                      className={`mt-1 w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500 ${loginEmail ? 'cursor-not-allowed bg-slate-100 text-slate-500' : ''}`}
                    />
                  </div>

                  {/* Mandatory Compliance Document Uploads */}
                  <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div>
                      <label htmlFor="drawer-po-file" className="block text-xs font-semibold text-slate-700">
                        Purchase Order Document (PDF, Word, Image) <span className="text-red-600">*</span>
                      </label>
                      <input
                        id="drawer-po-file"
                        name="drawer-po-file"
                        type="file"
                        required
                        accept={PO_FILE_ACCEPT}
                        disabled={isSubmittingDrawerPo}
                        onChange={(e) => pickPoFile(e, setDrawerPoFile)}
                        className="mt-1 block w-full text-xs text-slate-600"
                      />
                      {drawerPoFile && <span className="mt-1 block text-xs font-semibold text-emerald-700">Uploaded: {drawerPoFile.name}</span>}
                    </div>

                    <div className="border-t border-slate-200 pt-3">
                      <div className="flex items-center justify-between">
                        <label htmlFor="drawer-export-file" className="text-xs font-semibold text-slate-700">
                          Signed Export Compliance Certification <span className="text-red-600">*</span>
                        </label>
                        <a
                          href="/documents/WingedTycoons-Export-Compliance-Certification.pdf"
                          download
                          className="text-xs font-medium text-emerald-700 underline hover:text-emerald-800"
                        >
                          Download Template
                        </a>
                      </div>
                      <input
                        id="drawer-export-file"
                        name="drawer-export-file"
                        type="file"
                        required
                        accept={PO_FILE_ACCEPT}
                        disabled={isSubmittingDrawerPo}
                        onChange={(e) => pickPoFile(e, setDrawerExportFile)}
                        className="mt-1 block w-full text-xs text-slate-600"
                      />
                      {drawerExportFile && <span className="mt-1 block text-xs font-semibold text-emerald-700">Uploaded: {drawerExportFile.name}</span>}
                    </div>

                    <div className="border-t border-slate-200 pt-3">
                      <div className="flex items-center justify-between">
                        <label htmlFor="drawer-kyc-file" className="text-xs font-semibold text-slate-700">
                          Signed KYC Form <span className="text-red-600">*</span>
                        </label>
                        <a
                          href="/documents/WingedTycoons-KYC-Form.pdf"
                          download
                          className="text-xs font-medium text-emerald-700 underline hover:text-emerald-800"
                        >
                          Download Form
                        </a>
                      </div>
                      <input
                        id="drawer-kyc-file"
                        name="drawer-kyc-file"
                        type="file"
                        required
                        accept={PO_FILE_ACCEPT}
                        disabled={isSubmittingDrawerPo}
                        onChange={(e) => pickPoFile(e, setDrawerKycFile)}
                        className="mt-1 block w-full text-xs text-slate-600"
                      />
                      {drawerKycFile && <span className="mt-1 block text-xs font-semibold text-emerald-700">Uploaded: {drawerKycFile.name}</span>}
                    </div>
                  </div>

                  <div>
                    <label htmlFor="drawer-shipping" className="block text-xs font-semibold text-slate-700">
                      Shipping / Carrier Preference (Optional)
                    </label>
                    <input
                      id="drawer-shipping"
                      name="drawer-shipping"
                      disabled={isSubmittingDrawerPo}
                      value={drawerCarrierNotes}
                      onChange={(e) => setDrawerCarrierNotes(e.target.value)}
                      placeholder="e.g., FedEx Account #123456 or prepay freight"
                      className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs outline-none focus:ring-2 focus:ring-emerald-500"
                    />
                  </div>

                  <label className="flex items-start gap-2.5 text-xs text-slate-700 cursor-pointer pt-1">
                    <input
                      id="drawer-agreement"
                      name="drawer-agreement"
                      type="checkbox"
                      required
                      disabled={isSubmittingDrawerPo}
                      checked={drawerAgreementSigned}
                      onChange={(e) => setDrawerAgreementSigned(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                    />
                    <span>
                      I confirm export compliance, authorized end-user destination, and accuracy of purchase order details.
                    </span>
                  </label>

                  {drawerNotice && (
                    <div
                      role="status"
                      className={`rounded-xl p-3 text-xs font-semibold ${
                        drawerNoticeType === 'error' ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                      }`}
                    >
                      {drawerNotice}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={isSubmittingDrawerPo}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-3 font-display text-sm font-bold text-white shadow-md transition-all hover:bg-emerald-800 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isSubmittingDrawerPo ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>Submitting Purchase Order...</span>
                      </>
                    ) : (
                      <>
                        <span>Confirm & Lock Order</span>
                        <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
