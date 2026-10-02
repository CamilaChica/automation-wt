"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";

type QuoteDetails = {
  quote: {
    id: string;
    rfq_id: string;
    subtotal: number;
    shipping_cost: number;
    total_amount: number;
    status: string;
    lead_time_days?: number | null;
    valid_until?: string | null;
  };
  rfq_status?: string | null;
  items: Array<{
    part_number: string;
    quantity: number;
    unit_price: number;
    certificate_type: string;
    compliance_status: string;
    condition?: string | null;
  }>;
};

type DocumentKind = "export" | "kyc" | "po";
type DocumentFiles = Record<DocumentKind, File | null>;
type UploadedIds = Partial<Record<DocumentKind, string>>;

const documentLabels: Array<{ kind: DocumentKind; label: string }> = [
  { kind: "export", label: "Signed export certification" },
  { kind: "kyc", label: "Completed KYC form" },
  { kind: "po", label: "Purchase order" },
];

function amount(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function errorMessage(payload: unknown): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "We couldn’t complete that action. Please try again.";
}

export default function QuoteView({ quoteId }: { quoteId: string }) {
  const [quote, setQuote] = useState<QuoteDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [poNumber, setPoNumber] = useState("");
  const [files, setFiles] = useState<DocumentFiles>({ export: null, kyc: null, po: null });
  const [uploadedIds, setUploadedIds] = useState<UploadedIds>({});
  const [sending, setSending] = useState(false);
  const [poStatus, setPoStatus] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    async function loadQuote() {
      setLoading(true);
      setError("");
      try {
        const response = await fetch(`/api/customer/quotes/${encodeURIComponent(quoteId)}`, {
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(errorMessage(payload));
        setQuote(payload as QuoteDetails);
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : "We couldn’t load this quote.");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void loadQuote();
    return () => controller.abort();
  }, [quoteId]);

  async function uploadDocument(kind: DocumentKind, file: File): Promise<string> {
    if (uploadedIds[kind]) return uploadedIds[kind] as string;
    const form = new FormData();
    form.set("file", file);
    const response = await fetch("/api/customer/attachments", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload));
    const attachmentId = payload.attachment_id as string;
    setUploadedIds(current => ({ ...current, [kind]: attachmentId }));
    return attachmentId;
  }

  async function submitPurchaseOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!quote) return;
    const missingDocument = documentLabels.find(({ kind }) => !files[kind] && !uploadedIds[kind]);
    if (missingDocument) {
      setError(`Choose the ${missingDocument.label.toLowerCase()} PDF.`);
      return;
    }

    setError("");
    setSending(true);
    try {
      const attachmentIds: string[] = [];
      for (const { kind } of documentLabels) {
        const documentFile = files[kind];
        const attachmentId = uploadedIds[kind] || (documentFile ? await uploadDocument(kind, documentFile) : "");
        if (!attachmentId) throw new Error("All three signed documents are required.");
        attachmentIds.push(attachmentId);
      }
      const response = await fetch("/api/customer/purchase-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quote_id: quote.quote.id, po_number: poNumber.trim(), attachment_ids: attachmentIds }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload));
      setPoStatus(payload.status || "Pending_PO_Review");
      setDrawer(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "We couldn’t submit your purchase order.");
    } finally {
      setSending(false);
    }
  }

  if (loading) return <main className="shell quote-state" aria-live="polite">Loading your quote…</main>;
  if (error && !quote) {
    return <main className="shell quote-state"><p className="error" role="alert">{error}</p><Link className="secondary" href="/rfq">Return to the RFQ portal</Link></main>;
  }
  if (!quote) return null;

  const canAccept = quote.quote.status === "Sent" && !poStatus;
  const displayedStatus = poStatus || quote.quote.status;
  const formattedValidity = quote.quote.valid_until
    ? new Date(quote.quote.valid_until).toLocaleDateString()
    : null;

  return <main className="shell">
    <header className="topbar"><Link href="/" className="brand" aria-label="Winged Tycoons home"><img src="/WingedTycoons.png" alt="" /><span>WINGED TYCOONS</span></Link><div className="mobile-nav"><button data-testid="mobile-menu-button" aria-label="Open navigation" onClick={() => setMenuOpen(value => !value)}>☰</button>{menuOpen && <nav><Link href="/rfq">New RFQ</Link><Link href={`/quotes/${quoteId}`}>Quote</Link></nav>}</div><span className="secure">CUSTOMER QUOTE <b>{displayedStatus.replaceAll("_", " ")}</b></span></header>
    <section className="quote-wrap">
      <div className="quote-title"><div><p className="eyebrow">Commercial quotation</p><h1>Quote {quote.quote.id}</h1><p>For request {quote.quote.rfq_id}</p></div><span className="status-pill">{displayedStatus.replaceAll("_", " ")}</span></div>
      {error && <p className="error" role="alert">{error}</p>}
      {poStatus && <p className="success-message" role="status">Your documents were submitted. The purchase order is <strong>{poStatus.replaceAll("_", " ")}</strong> while our operations team reviews it.</p>}
      <div className="quote-grid">
        <article className="quote-card">
          <div className="quote-card-head"><div><span className="label">WINGED TYCOONS AVIATION</span><h2>Aircraft component quotation</h2></div><button className="secondary" onClick={() => window.print()}>Print quote</button></div>
          <div className="quote-meta">
            <div><span>Quote status</span><strong>{quote.quote.status}</strong></div>
            <div><span>Request status</span><strong>{quote.rfq_status || "In review"}</strong></div>
            {quote.quote.lead_time_days != null && <div><span>Lead time</span><strong>{quote.quote.lead_time_days} days</strong></div>}
            {formattedValidity && <div><span>Valid until</span><strong>{formattedValidity}</strong></div>}
          </div>
          {quote.items.map((item, index) => <div className="line-item" key={`${item.part_number}-${index}`}><div><span className="part-icon">✦</span><div><strong>{item.part_number}</strong><small>{item.quantity} EA · {item.condition || "Condition as quoted"} · {item.certificate_type}</small><small>Compliance: {item.compliance_status}</small></div></div><strong>{amount(item.unit_price * item.quantity)} <small>USD</small></strong></div>)}
          <div className="total"><span>Subtotal</span><strong>{amount(quote.quote.subtotal)} <small>USD</small></strong></div>
          <div className="quote-charge"><span>Shipping</span><strong>{amount(quote.quote.shipping_cost)} USD</strong></div>
          <div className="total"><span>Total proposal</span><strong>{amount(quote.quote.total_amount)} <small>USD</small></strong></div>
        </article>
        <aside className="side-card"><p className="eyebrow">Ready when you are</p><h2>{canAccept ? "Move this order forward." : "We’ll keep you updated."}</h2><p>{canAccept ? "Accept the sent quote and upload your signed documents. Our operations team will verify them before release." : "This quote is not currently available for acceptance. Contact our team if you need help."}</p>{canAccept && <button className="primary" onClick={() => setDrawer(true)}>Accept & upload documents <span>→</span></button>}</aside>
      </div>
    </section>
    {canAccept && <div className="mobile-sticky-cta"><button className="primary" onClick={() => setDrawer(true)}>Accept & upload documents <span>→</span></button></div>}
    {drawer && <div className="modal-backdrop"><form className="modal" role="dialog" aria-modal="true" aria-labelledby="po-title" onSubmit={submitPurchaseOrder}><button className="close" type="button" onClick={() => setDrawer(false)} aria-label="Close">×</button><p className="eyebrow">Purchase order</p><h2 id="po-title">Accept quotation</h2><p>Enter your PO number and upload all three signed documents as PDFs. Maximum 25 MB each.</p><label className="upload" htmlFor="po-number">Purchase order number<input id="po-number" required value={poNumber} onChange={event => setPoNumber(event.target.value)} /></label>{documentLabels.map(({ kind, label }) => <label className="upload" htmlFor={`document-${kind}`} key={kind}>{label}<input id={`document-${kind}`} type="file" accept="application/pdf" required={!uploadedIds[kind]} onChange={event => setFiles(current => ({ ...current, [kind]: event.target.files?.[0] ?? null }))} />{(files[kind] || uploadedIds[kind]) && <small>{files[kind]?.name || "Uploaded and ready"}</small>}</label>)}{error && <p className="error" role="alert">{error}</p>}<button className="primary" type="submit" disabled={sending}>{sending ? "Submitting…" : "Submit purchase order"} <span>→</span></button></form></div>}
  </main>;
}
