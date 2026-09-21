"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

const conditions = ["New", "Overhauled", "Serviceable", "As Removed"];
const certifications = ["FAA Form 8130-3", "EASA Form 1", "CoC"];

export default function CustomerRFQForm() {
  const [submitted, setSubmitted] = useState(false);
  const [aog, setAog] = useState(false);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") || "");
    const quantity = Number(form.get("quantity") || 0);
    if (!email.includes("@")) return setError("Enter a valid work email.");
    if (quantity < 1) return setError("Quantity must be at least 1.");
    setError("");
    setSubmitted(true);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <Link href="/" className="brand" aria-label="Winged Tycoons home"><img src="/WingedTycoons.png" alt="Winged Tycoons Logo" /><span>WINGED TYCOONS</span></Link>
        <div className="mobile-nav"><button data-testid="mobile-menu-button" aria-label="Open navigation" onClick={() => setMenuOpen(value => !value)}>☰</button>{menuOpen && <nav><Link href="/rfq">New RFQ</Link><Link href="/quotes/QTE-9921">Quotes</Link></nav>}</div><span className="secure">CUSTOMER RFQ PORTAL <b>● SECURE</b></span>
      </header>
      <section className="rfq-wrap">
        <div className="intro"><p className="eyebrow">Aviation parts desk</p><h1>Source the right part, without the runway.</h1><p>Send a structured request to our MRO team. We validate availability, traceability, and commercial terms before we quote.</p><div className="trust"><span>01 / Qualified sourcing</span><span>02 / Traceable offers</span><span>03 / Human-reviewed quote</span></div></div>
        <form className="rfq-card" onSubmit={submit} noValidate>
          <div className="card-head"><div><p className="eyebrow">New request</p><h2>Request a quotation</h2></div><label className={`urgency ${aog ? "active" : ""}`}><input type="checkbox" checked={aog} onChange={e => setAog(e.target.checked)} /> AOG / Critical</label></div>
          <div className="field-grid">
            <label htmlFor="customer-name">Customer name<input id="customer-name" name="name" required placeholder="Maria Buyer" /></label>
            <label htmlFor="company">Company<input id="company" name="company" required placeholder="Global Airlines" /></label>
            <label htmlFor="email">Email<input id="email" name="email" type="email" required placeholder="buyer@airline.com" /></label>
            <label htmlFor="phone">Phone<input id="phone" name="phone" type="tel" placeholder="+1 305 555 0100" /></label>
            <label htmlFor="aircraft">Aircraft platform<input id="aircraft" name="aircraft" required placeholder="B737-800" /></label>
            <label htmlFor="part-number">Part number<input id="part-number" name="partNumber" required placeholder="XYZ123" /></label>
            <label htmlFor="quantity">Quantity<input id="quantity" name="quantity" type="number" min="1" defaultValue="1" required /></label>
            <label htmlFor="required-date">Required date<input id="required-date" name="requiredDate" type="date" required /></label>
            <label htmlFor="condition">Condition requested<select id="condition" name="condition" defaultValue="Serviceable">{conditions.map(value => <option key={value}>{value}</option>)}</select></label>
            <label htmlFor="certification">Certification<select id="certification" name="certification" defaultValue="FAA Form 8130-3">{certifications.map(value => <option key={value}>{value}</option>)}</select></label>
            <label className="wide" htmlFor="destination">Destination<input id="destination" name="destination" required placeholder="Miami, FL / MIA" /></label>
            <label className="wide">Supporting documents<input type="file" accept="application/pdf,image/png,image/jpeg" onChange={e => setFileName(e.target.files?.[0]?.name || "")} />{fileName && <small>Attached: {fileName}</small>}</label>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" type="submit">Send RFQ <span>→</span></button>
          <p className="fineprint">By submitting, you confirm the request is for legitimate aviation procurement and agree to export-control screening.</p>
        </form>
      </section>
      {submitted && <div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="success-title"><span className="success-icon">✓</span><p className="eyebrow">Request received</p><h2 id="success-title">Your sourcing desk is on it.</h2><p>We have received your RFQ and will reply with availability, traceability, and pricing after review.</p><Link className="primary" href="/quotes/QTE-9921">View sample quote →</Link><button className="text-button" onClick={() => setSubmitted(false)}>Close</button></div></div>}
    </main>
  );
}
