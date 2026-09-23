import React, { useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, Clock3, FileSearch, LogOut, Plane, Search, ShieldCheck } from 'lucide-react';
import { apiService } from '../../services/api';
import { BrandMark } from '../common/BrandMark';
import { normalizeQuantityInput } from '../../utils/quantity';

type CatalogResult = Awaited<ReturnType<typeof apiService.searchCatalog>>[number];

export const CustomerPortal: React.FC = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogResult[]>([]);
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
  const [shipment, setShipment] = useState<import('../../types').Shipment | null>(null);
  const [isTracking, setIsTracking] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const searchCatalog = async (value: string) => {
    if (!value.trim()) {
      setResults([]);
      setNotice('Enter a part number to search availability.');
      return;
    }
    setIsSearching(true);
    try {
      setResults(await apiService.searchCatalog(value, condition || undefined));
      setNotice(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Catalog search failed. Please retry.');
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
    if (!agreementSigned) {
      setNotice('Sign the compliance agreement before submitting your RFQ.');
      return;
    }
    setIsSubmitting(true);
    try {
      const attachmentIds = partsListFile ? [(await apiService.uploadAttachment(partsListFile)).attachment_id] : [];
      const response = await apiService.submitCustomerRFQ(
        `Customer request for P/N ${partNumber}, quantity ${quantity}, condition ${condition}. ${details}`,
        customerName,
        customerEmail,
        attachmentIds,
      );
      setNotice(response.message || `Request ${response.rfq_id} received.`);
      setTrackingStatus('Processing Autonomous Fulfillment');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'RFQ submission failed. Please retry.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePurchaseOrder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!exportCertificate || !kycForm || !poDocument) {
      setNotice('Upload the signed export certification, signed KYC form, and purchase order document before submitting.');
      return;
    }
    setIsSubmittingPo(true);
    try {
      const uploaded = await Promise.all([exportCertificate, kycForm, poDocument].map(file => apiService.uploadAttachment(file)));
      await apiService.submitPurchaseOrder(quoteId, poNumber, customerEmail, uploaded.map(item => item.attachment_id));
      setNotice(`Purchase order ${poNumber} received. Our purchasing team will confirm the order by email.`);
      setQuoteId('');
      setPoNumber('');
      setExportCertificate(null);
      setKycForm(null);
      setPoDocument(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Purchase order submission failed. Please retry.');
    } finally {
      setIsSubmittingPo(false);
    }
  };

  const handleTrackShipment = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsTracking(true);
    try {
      setShipment(await apiService.trackShipment(trackingToken));
      setNotice(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Shipment tracking failed. Please retry.');
    } finally {
      setIsTracking(false);
    }
  };

  useEffect(() => {
    if (!trackingToken || !shipment) return;
    const refresh = window.setInterval(() => {
      void apiService.trackShipment(trackingToken).then(setShipment).catch(() => undefined);
    }, 60000);
    return () => window.clearInterval(refresh);
  }, [trackingToken, shipment]);

  return (
    <div className="customer-portal-light min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white/95">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <a href="/" className="flex items-center gap-3">
            <BrandMark />
            <span className="font-display text-lg font-bold tracking-wide">WINGED TYCOONS</span>
          </a>
          <div className="flex items-center gap-4"><a href="mailto:parts@wingedtycoons.com" className="text-sm text-slate-600 hover:text-slate-900">Need help? Contact parts desk</a><button type="button" onClick={() => { void apiService.signOut().finally(() => { window.location.href = '/'; }); }} className="flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"><LogOut className="h-4 w-4" /> Sign out</button></div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-12 px-6 py-12">
        <section className="max-w-3xl">
          <p className="mb-3 text-xs font-bold uppercase tracking-[0.25em] text-cyan-400">Customer parts portal</p>
          <h1 className="font-display text-4xl font-bold leading-tight md:text-6xl">Find aircraft parts faster.</h1>
          <p className="mt-5 text-lg text-slate-400">Search current availability, review traceability options, and send a request to our aerospace parts team in minutes.</p>
        </section>

        <section className="grid gap-5 md:grid-cols-3">
          {[
            [Search, 'Search by part number', 'Start with a manufacturer or customer part number.'],
            [ShieldCheck, 'Traceable options', 'See available condition and certification information.'],
            [Clock3, 'Fast RFQ response', 'Our team validates sourcing and sends a quote by email.']
          ].map(([Icon, title, description]) => (
            <div key={title as string} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <Icon className="mb-4 h-5 w-5 text-cyan-400" />
              <h2 className="font-display font-bold">{title as string}</h2>
              <p className="mt-2 text-sm text-slate-400">{description as string}</p>
            </div>
          ))}
        </section>

        <section className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="font-display text-xl font-bold">Parts availability</h2>
                <p className="mt-1 text-sm text-slate-400">Customer-safe results; final availability is confirmed by our team.</p>
              </div>
              <Plane className="h-6 w-6 text-cyan-400" />
            </div>
            <form onSubmit={handleSearch} className="flex gap-3">
              <label htmlFor="catalog-search" className="sr-only">Search aircraft parts</label>
              <input id="catalog-search" name="catalog-search" autoComplete="off" aria-label="Search aircraft parts" value={query} onChange={event => setQuery(event.target.value)} placeholder="e.g., 060-1234-00" className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <button className="rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 hover:bg-cyan-300" aria-label="Search parts"><Search className="h-4 w-4" /></button>
            </form>
            <div className="mt-5 space-y-3">
              {isSearching && <p className="text-sm text-slate-400">Searching catalog...</p>}
              {!isSearching && results.length === 0 && <p className="text-sm text-slate-400">No matching parts found. Submit a request and we will source it.</p>}
              {results.map((item, index) => (
                <button key={`${item.part_number}-${item.condition_code}-${index}`} onClick={() => setPartNumber(item.part_number)} className="w-full rounded-2xl border border-slate-200 bg-slate-50 p-4 text-left hover:border-cyan-400/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                  <div className="flex items-center justify-between"><span className="font-mono font-bold">{item.part_number}</span><span className="text-xs text-emerald-400">{item.quantity_available} available</span></div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400"><span>{item.condition_code}</span><span>•</span><span>{item.certificate_type}</span><span>•</span><span>{item.has_full_trace ? 'Full trace available' : 'Trace review required'}</span></div>
                </button>
              ))}
            </div>
          </div>

          <form aria-label="Request a quote form" onSubmit={handleRequest} className="rounded-3xl border border-cyan-400/30 bg-cyan-400/10 p-6">
            <h2 className="font-display text-xl font-bold">Request a quote</h2>
            <p className="mt-1 text-sm text-slate-300">Can’t find the exact part? Tell us what you need.</p>
            <div className="mt-5 space-y-3">
              <label htmlFor="customer-name" className="sr-only">Company or contact name</label>
              <input id="customer-name" name="customer-name" autoComplete="organization" required value={customerName} onChange={event => setCustomerName(event.target.value)} placeholder="e.g., Global Airlines" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <label htmlFor="customer-email" className="sr-only">Work email</label>
              <input id="customer-email" name="customer-email" autoComplete="email" required type="email" value={customerEmail} onChange={event => setCustomerEmail(event.target.value)} placeholder="e.g., buyer@airline.com" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <div className="flex gap-3">
                <label htmlFor="rfq-part-number" className="sr-only">Part number</label>
                  <input id="rfq-part-number" name="part-number" autoComplete="off" required value={partNumber} onChange={event => setPartNumber(event.target.value)} placeholder="e.g., BACB30LU-4" className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
                <label htmlFor="rfq-quantity" className="sr-only">Quantity</label>
                <input
                  id="rfq-quantity"
                  name="quantity"
                  required
                  type="number"
                  min="1"
                  value={quantity}
                  onChange={event => setQuantity(normalizeQuantityInput(event.target.value))}
                  className="w-24 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none"
                />
              </div>
                <label htmlFor="rfq-condition" className="sr-only">Target condition</label>
                <select id="rfq-condition" name="condition" required value={condition} onChange={event => setCondition(event.target.value)} className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 focus:ring-2 focus:ring-cyan-400 focus:outline-none"><option value="">Select target condition</option><option value="NE">NE - New</option><option value="FN">FN - Factory New</option><option value="NS">NS - New Surplus</option><option value="OH">OH - Overhauled</option><option value="SVC">SVC - Serviceable</option><option value="RP">RP - Repaired</option><option value="AR">AR - As Removed</option><option value="IN">IN - Inspected</option></select>
              <label htmlFor="rfq-details" className="sr-only">RFQ details</label>
              <textarea id="rfq-details" name="details" autoComplete="off" value={details} onChange={event => setDetails(event.target.value)} placeholder="Condition, aircraft type, certification, and delivery location" rows={4} className="w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <label className="block rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-700">
                Parts list or sourcing spreadsheet (optional)
                <input
                  id="compliance-file"
                  name="parts-list-file"
                  type="file"
                  accept=".csv,.xlsx,.pdf,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf"
                  onChange={event => setPartsListFile(event.target.files?.[0] ?? null)}
                  className="mt-2 block w-full text-xs text-slate-500"
                />
                {partsListFile && <span className="mt-2 block text-xs text-emerald-700">Ready to upload: {partsListFile.name}</span>}
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  id="agreement-signed"
                  name="agreement-signed"
                  type="checkbox"
                  checked={agreementSigned}
                  onChange={event => setAgreementSigned(event.target.checked)}
                />
                I confirm this request contains accurate part and quantity information.
              </label>
              <button disabled={isSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 hover:bg-cyan-300 disabled:opacity-60">{isSubmitting ? 'Submitting RFQ...' : 'Send request'} <ArrowRight className="h-4 w-4" /></button>
            </div>
            {notice && <p role="status" aria-live="polite" className="mt-4 flex gap-2 rounded-xl bg-emerald-400/10 p-3 text-sm text-emerald-300"><CheckCircle2 className="h-5 w-5 shrink-0" />{notice}</p>}
            {trackingStatus && (
              <p className="mt-3 rounded-xl border border-cyan-400/40 bg-cyan-400/10 p-3 text-xs font-semibold text-cyan-300">
                Tracking status: {trackingStatus}
              </p>
            )}
          </form>

          <form aria-label="Purchase order form" onSubmit={handlePurchaseOrder} className="rounded-3xl border border-emerald-400/30 bg-emerald-400/10 p-6">
            <h2 className="font-display text-xl font-bold">Send a purchase order</h2>
            <p className="mt-1 text-sm text-slate-300">Use the quote reference from our email. Supplier details remain confidential.</p>
            <div className="mt-5 space-y-3">
              <label htmlFor="quote-id" className="sr-only">Quote reference</label>
              <input id="quote-id" name="quote-id" autoComplete="off" required value={quoteId} onChange={event => setQuoteId(event.target.value)} placeholder="e.g., QTE-123456" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none" />
              <label htmlFor="po-number" className="sr-only">Purchase order number</label>
              <input id="po-number" name="po-number" autoComplete="off" required value={poNumber} onChange={event => setPoNumber(event.target.value)} placeholder="e.g., PO-1001" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none" />
              <label htmlFor="po-email" className="sr-only">Purchase order work email</label>
              <input id="po-email" name="po-email" autoComplete="email" required type="email" value={customerEmail} onChange={event => setCustomerEmail(event.target.value)} placeholder="e.g., buyer@airline.com" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:outline-none" />
              <div className="rounded-xl border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300"><p className="font-semibold">Required compliance documents</p><div className="mt-2 flex flex-wrap gap-3"><a className="text-emerald-300 underline" href="/documents/WingedTycoons-Export-Compliance-Certification.pdf" download>Download export certification</a><a className="text-emerald-300 underline" href="/documents/WingedTycoons-KYC-Form.pdf" download>Download KYC form</a></div></div>
              <label htmlFor="po-export" className="block text-xs text-slate-300">Signed export certification<input id="po-export" name="po-export" required type="file" accept=".pdf,application/pdf" onChange={event => setExportCertificate(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs" /></label>
              <label htmlFor="po-kyc" className="block text-xs text-slate-300">Signed KYC form<input id="po-kyc" name="po-kyc" required type="file" accept=".pdf,application/pdf" onChange={event => setKycForm(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs" /></label>
              <label htmlFor="po-document" className="block text-xs text-slate-300">Purchase order document<input id="po-document" name="po-document" required type="file" accept=".pdf,application/pdf" onChange={event => setPoDocument(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs" /></label>
              <button disabled={isSubmittingPo || !exportCertificate || !kycForm || !poDocument} className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 px-4 py-3 font-bold text-slate-950 hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-60">{isSubmittingPo ? 'Uploading documents and submitting...' : 'Submit purchase order'} <ArrowRight className="h-4 w-4" /></button>
            </div>
          </form>

          <form onSubmit={handleTrackShipment} className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
            <h2 className="font-display text-xl font-bold">Track a shipment</h2>
            <p className="mt-1 text-sm text-slate-400">Enter the private tracking token from our shipment email.</p>
            <div className="mt-5 flex gap-3">
              <label htmlFor="tracking-token" className="sr-only">Tracking token</label>
              <input id="tracking-token" name="tracking-token" autoComplete="off" required value={trackingToken} onChange={event => setTrackingToken(event.target.value)} placeholder="Enter your tracking token" className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-cyan-400 focus:outline-none" />
              <button disabled={isTracking} className="rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 disabled:opacity-60" aria-label="Track shipment">{isTracking ? '...' : 'Track'}</button>
            </div>
            {shipment && (
              <div className="mt-4 rounded-xl border border-slate-700 bg-slate-950 p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-display text-lg font-bold text-cyan-300">{shipment.status}</div>
                  <span className="rounded-full border border-emerald-400/40 bg-emerald-400/10 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-emerald-300">Live status</span>
                </div>
                <div className="mt-3 grid gap-2 text-slate-400 sm:grid-cols-2">
                  <div>Carrier: <span className="text-slate-200">{shipment.carrier || 'Preparing'}</span></div>
                  <div>Tracking: <span className="font-mono text-slate-200">{shipment.tracking_number || 'Pending'}</span></div>
                  <div>Latest location: <span className="text-slate-200">{shipment.events?.[shipment.events.length - 1]?.location || 'Pending update'}</span></div>
                  <div>Estimated delivery: <span className="text-slate-200">{shipment.estimated_delivery || 'To be confirmed'}</span></div>
                </div>
                <div className="mt-5 border-l border-slate-700 pl-4">
                  {(shipment.events || []).slice().reverse().map((event, index: number) => (
                    <div key={`${event.id}-${index}`} className="relative pb-4 last:pb-0">
                      <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-cyan-400 ring-4 ring-slate-950" />
                      <div className="font-semibold text-slate-200">{event.status}</div>
                      <div className="text-xs text-slate-400">{event.description}</div>
                      {event.location && <div className="mt-1 text-xs text-cyan-300">{event.location}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </form>
        </section>

        <footer className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-800 pt-6 text-xs text-slate-500">
          <span>Winged Tycoons customer portal</span>
          <span>Availability and certification are confirmed before quoting.</span>
          <a href="/internal" className="flex items-center gap-1 hover:text-slate-300"><FileSearch className="h-3.5 w-3.5" /> Team sign-in</a>
        </footer>
      </main>
    </div>
  );
};
