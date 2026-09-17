import React, { useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, Clock3, FileSearch, Plane, Search, ShieldCheck } from 'lucide-react';
import { apiService } from '../../services/api';
import { BrandMark } from '../common/BrandMark';

type CatalogResult = Awaited<ReturnType<typeof apiService.searchCatalog>>[number];

export const CustomerPortal: React.FC = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogResult[]>([]);
  const [customerName, setCustomerName] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');
  const [partNumber, setPartNumber] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [details, setDetails] = useState('');
  const [agreementSigned, setAgreementSigned] = useState(false);
  const [complianceFileName, setComplianceFileName] = useState<string | null>(null);
  const [trackingStatus, setTrackingStatus] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void searchCatalog('');
  }, []);

  const searchCatalog = async (value: string) => {
    setIsSearching(true);
    setResults(await apiService.searchCatalog(value));
    setIsSearching(false);
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
    const response = await apiService.submitCustomerRFQ(
      `Customer request for P/N ${partNumber}, quantity ${quantity}. ${details}`,
      customerName,
      customerEmail
    );
    setNotice(`Request ${response.rfq_id} received. Our parts team will email ${customerEmail} with availability and pricing.`);
    setTrackingStatus('Processing Autonomous Fulfillment');
    setIsSubmitting(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/95">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <a href="/" className="flex items-center gap-3">
            <BrandMark />
            <span className="font-display text-lg font-bold tracking-wide">WINGED TYCOONS</span>
          </a>
          <a href="mailto:parts@wingedtycoons.com" className="text-sm text-slate-300 hover:text-white">Need help? Contact parts desk</a>
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
            <div key={title as string} className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
              <Icon className="mb-4 h-5 w-5 text-cyan-400" />
              <h2 className="font-display font-bold">{title as string}</h2>
              <p className="mt-2 text-sm text-slate-400">{description as string}</p>
            </div>
          ))}
        </section>

        <section className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="font-display text-xl font-bold">Parts availability</h2>
                <p className="mt-1 text-sm text-slate-400">Customer-safe results; final availability is confirmed by our team.</p>
              </div>
              <Plane className="h-6 w-6 text-cyan-400" />
            </div>
            <form onSubmit={handleSearch} className="flex gap-3">
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search part number, e.g. 060-1234-00" className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:border-cyan-400" />
              <button className="rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 hover:bg-cyan-300" aria-label="Search parts"><Search className="h-4 w-4" /></button>
            </form>
            <div className="mt-5 space-y-3">
              {isSearching && <p className="text-sm text-slate-400">Searching catalog...</p>}
              {!isSearching && results.length === 0 && <p className="text-sm text-slate-400">No matching parts found. Submit a request and we will source it.</p>}
              {results.map((item, index) => (
                <button key={`${item.part_number}-${item.condition_code}-${index}`} onClick={() => setPartNumber(item.part_number)} className="w-full rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-left hover:border-cyan-400/70">
                  <div className="flex items-center justify-between"><span className="font-mono font-bold">{item.part_number}</span><span className="text-xs text-emerald-400">{item.quantity_available} available</span></div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400"><span>{item.condition_code}</span><span>•</span><span>{item.certificate_type}</span><span>•</span><span>{item.has_full_trace ? 'Full trace available' : 'Trace review required'}</span></div>
                </button>
              ))}
            </div>
          </div>

          <form onSubmit={handleRequest} className="rounded-3xl border border-cyan-400/30 bg-cyan-400/10 p-6">
            <h2 className="font-display text-xl font-bold">Request a quote</h2>
            <p className="mt-1 text-sm text-slate-300">Can’t find the exact part? Tell us what you need.</p>
            <div className="mt-5 space-y-3">
              <input required value={customerName} onChange={event => setCustomerName(event.target.value)} placeholder="Company or contact name" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:border-cyan-400" />
              <input required type="email" value={customerEmail} onChange={event => setCustomerEmail(event.target.value)} placeholder="Work email" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:border-cyan-400" />
              <div className="flex gap-3">
                <input required value={partNumber} onChange={event => setPartNumber(event.target.value)} placeholder="Part number" className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:border-cyan-400" />
                <input required type="number" min="1" value={quantity} onChange={event => setQuantity(Number(event.target.value))} className="w-24 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:border-cyan-400" aria-label="Quantity" />
              </div>
              <textarea value={details} onChange={event => setDetails(event.target.value)} placeholder="Condition, aircraft type, certification, delivery location..." rows={4} className="w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm outline-none focus:border-cyan-400" />
              <label className="block rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-300">
                End-user compliance PDF (EUC)
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={event => setComplianceFileName(event.target.files?.[0]?.name ?? null)}
                  className="mt-2 block w-full text-xs text-slate-400"
                />
                {complianceFileName && <span className="mt-2 block text-xs text-emerald-300">Uploaded: {complianceFileName}</span>}
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={agreementSigned}
                  onChange={event => setAgreementSigned(event.target.checked)}
                />
                I confirm this order and compliance documentation are valid for export screening.
              </label>
              <button disabled={isSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 hover:bg-cyan-300 disabled:opacity-60">{isSubmitting ? 'Sending request...' : 'Send request'} <ArrowRight className="h-4 w-4" /></button>
            </div>
            {notice && <p className="mt-4 flex gap-2 rounded-xl bg-emerald-400/10 p-3 text-sm text-emerald-300"><CheckCircle2 className="h-5 w-5 shrink-0" />{notice}</p>}
            {trackingStatus && (
              <p className="mt-3 rounded-xl border border-cyan-400/40 bg-cyan-400/10 p-3 text-xs font-semibold text-cyan-300">
                Tracking status: {trackingStatus}
              </p>
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
