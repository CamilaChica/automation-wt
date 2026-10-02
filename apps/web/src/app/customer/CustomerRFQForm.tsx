"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useCustomerSession } from "./CustomerPortalGate";

const conditions = ["New", "Overhauled", "Serviceable", "As Removed"];
const certifications = ["FAA Form 8130-3", "EASA Form 1", "CoC"];

function errorMessage(payload: unknown): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "We couldn’t submit your request. Please try again.";
}

export default function CustomerRFQForm() {
  const { email: customerEmail } = useCustomerSession();
  const [submittedId, setSubmittedId] = useState("");
  const [aog, setAog] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    if (!formElement.reportValidity()) return;
    const form = new FormData(formElement);
    const quantity = Number(form.get("quantity") || 0);
    if (quantity < 1) {
      setError("Quantity must be at least 1.");
      return;
    }

    setError("");
    setSending(true);
    try {
      const attachmentIds: string[] = [];
      if (file) {
        const upload = new FormData();
        upload.set("file", file);
        const uploadResponse = await fetch("/api/customer/attachments", { method: "POST", body: upload });
        const uploadPayload = await uploadResponse.json();
        if (!uploadResponse.ok) throw new Error(errorMessage(uploadPayload));
        attachmentIds.push(uploadPayload.attachment_id);
      }

      const details = [
        `Company: ${String(form.get("company")).trim()}`,
        `Contact: ${String(form.get("name")).trim()}`,
        `Part number: ${String(form.get("partNumber")).trim()}`,
        `Quantity: ${quantity}`,
        `Aircraft: ${String(form.get("aircraft")).trim()}`,
        `Condition requested: ${String(form.get("condition"))}`,
        `Certification requested: ${String(form.get("certification"))}`,
        `Required date: ${String(form.get("requiredDate"))}`,
        `Destination: ${String(form.get("destination")).trim()}`,
        `Urgency: ${aog ? "AOG / Critical" : "Standard"}`,
      ].join("\n");
      const response = await fetch("/api/customer/rfqs/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw_text: details,
          customer_name: String(form.get("company")).trim(),
          customer_email: customerEmail,
          attachment_ids: attachmentIds,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload));
      setSubmittedId(payload.rfq_id);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "We couldn’t submit your request. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <Link href="/" className="brand" aria-label="Winged Tycoons home"><img src="/WingedTycoons.png" alt="" /><span>WINGED TYCOONS</span></Link>
        <div className="mobile-nav"><button data-testid="mobile-menu-button" aria-label="Open navigation" onClick={() => setMenuOpen(value => !value)}>☰</button>{menuOpen && <nav><Link href="/rfq">New RFQ</Link></nav>}</div>
        <span className="secure">CUSTOMER RFQ PORTAL <b>● SECURE</b></span>
      </header>
      <section className="rfq-wrap">
        <div className="intro"><p className="eyebrow">Aviation parts desk</p><h1>Source the right part, without the runway.</h1><p>Send a structured request to our MRO team. We validate availability, traceability, and commercial terms before we quote.</p><div className="trust"><span>01 / Qualified sourcing</span><span>02 / Traceable offers</span><span>03 / Human-reviewed quote</span></div></div>
        <form className="rfq-card" onSubmit={submit}>
          <div className="card-head"><div><p className="eyebrow">New request</p><h2>Request a quotation</h2></div><label className={`urgency ${aog ? "active" : ""}`}><input type="checkbox" checked={aog} onChange={event => setAog(event.target.checked)} /> AOG / Critical</label></div>
          <div className="field-grid">
            <label htmlFor="customer-name">Contact name<input id="customer-name" name="name" required placeholder="Maria Buyer" /></label>
            <label htmlFor="company">Company<input id="company" name="company" required placeholder="Global Airlines" /></label>
            <label className="wide" htmlFor="customer-email">Verified email<input id="customer-email" type="email" value={customerEmail} readOnly /></label>
            <label htmlFor="aircraft">Aircraft platform<input id="aircraft" name="aircraft" required placeholder="B737-800" /></label>
            <label htmlFor="part-number">Part number<input id="part-number" name="partNumber" required placeholder="XYZ123" /></label>
            <label htmlFor="quantity">Quantity<input id="quantity" name="quantity" type="number" min="1" defaultValue="1" required /></label>
            <label htmlFor="required-date">Required date<input id="required-date" name="requiredDate" type="date" required /></label>
            <label htmlFor="condition">Condition requested<select id="condition" name="condition" defaultValue="Serviceable">{conditions.map(value => <option key={value}>{value}</option>)}</select></label>
            <label htmlFor="certification">Certification<select id="certification" name="certification" defaultValue="FAA Form 8130-3">{certifications.map(value => <option key={value}>{value}</option>)}</select></label>
            <label className="wide" htmlFor="destination">Destination<input id="destination" name="destination" required placeholder="Miami, FL / MIA" /></label>
            <label className="wide" htmlFor="supporting-document">Supporting document (optional)<input id="supporting-document" type="file" accept="application/pdf,image/png,image/jpeg" onChange={event => setFile(event.target.files?.[0] ?? null)} />{file && <small>Selected: {file.name} (maximum 25 MB)</small>}</label>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" type="submit" disabled={sending}>{sending ? "Sending request…" : "Send RFQ"} <span>→</span></button>
          <p className="fineprint">By submitting, you confirm the request is for legitimate aviation procurement and agree to export-control screening.</p>
        </form>
      </section>
      {submittedId && <div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="success-title"><span className="success-icon">✓</span><p className="eyebrow">Request received</p><h2 id="success-title">Your sourcing desk is on it.</h2><p>We’ve received request <strong>{submittedId}</strong>. Our team will review it and contact you at {customerEmail} when a quote is ready.</p><button className="primary" onClick={() => { setSubmittedId(""); setFile(null); }}>Create another RFQ</button></div></div>}
    </main>
  );
}
