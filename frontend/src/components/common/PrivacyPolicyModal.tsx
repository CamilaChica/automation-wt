import React, { useState } from 'react';
import { ShieldCheck, FileText, Lock, CheckCircle2, X, Download, AlertCircle, Building2 } from 'lucide-react';
import { BrandMark } from './BrandMark';

interface PrivacyPolicyModalProps {
  isOpen: boolean;
  onClose?: () => void;
  onAccept?: () => Promise<void> | void;
  onDecline?: () => void;
  isReadOnly?: boolean;
  companyOrEmail?: string;
}

export const PrivacyPolicyModal: React.FC<PrivacyPolicyModalProps> = ({
  isOpen,
  onClose,
  onAccept,
  onDecline,
  isReadOnly = false,
  companyOrEmail = '',
}) => {
  const [hasAgreed, setHasAgreed] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleAccept = async () => {
    if (!hasAgreed && !isReadOnly) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      if (onAccept) {
        await onAccept();
      }
    } catch {
      setErrorMessage('Unable to record your policy acceptance. Please retry.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const downloadCopy = () => {
    const policyText = `WINGED TYCOONS INC. - CUSTOMER PRIVACY POLICY & DATA GOVERNANCE
Version: 1.0
Effective Date: October 2026
Applicability: Commercial Aviation Procurement, RFQ Processing & Airworthiness Trace

1. SCOPE AND AVIATION SERVICES
Winged Tycoons Inc. operates an aerospace procurement, quotation, airworthiness trace, and component fulfillment network. This Privacy Policy governs the collection, processing, protection, and retention of commercial aerospace customer data when accessing the Winged Tycoons Customer Portal.

2. INFORMATION WE COLLECT
- Account & Corporate Identity: Authorized buyer work email, company name, corporate address, billing contact details, and account credentials.
- RFQ & Transaction Information: Part numbers, descriptions, target quantities, desired condition codes, formal RFQs, quotation histories, purchase orders, delivery destinations, and commercial invoices.
- Airworthiness & Regulatory Documentation: FAA 8130-3 airworthiness tags, EASA Form 1 certificates, dual-release documentation, Certificates of Conformity (CoC), trace chain-of-custody records, non-incident statements (NIS), and export-control classifications (ITAR / EAR).
- Security & Authentication Telemetry: One-time verification challenges, cryptographic session tokens, IP metadata, and tamper-resistant audit logs for regulatory accountability.

3. PURPOSES AND LAWFUL BASES FOR PROCESSING
- Aviation Order Execution: To quote, fulfill, package, trace, and deliver flight-critical aerospace inventory requested by your organization.
- Regulatory Airworthiness Compliance: To satisfy Federal Aviation Administration (FAA AC 00-56), European Union Aviation Safety Agency (EASA), and international civil aviation authority standards regarding serialized aircraft part traceability.
- Export Control & Trade Compliance: To screen against international denied-parties lists, verify end-user certifications, and prevent unauthorized diversion under US EAR and ITAR regulations.
- Fraud & Counterfeit Prevention: To maintain cryptographic trace verification, preventing unapproved parts (SUP) from entering the aviation supply chain.

4. DATA SHARING & THIRD-PARTY DISCLOSURE
- Certified Aerospace Suppliers: Transaction details are shared only to the extent required for inventory procurement and physical fulfillment.
- Licensed Aviation Carriers: Shipping addresses and export customs documents are transmitted to bonded aerospace logistics partners (e.g., FedEx Aerospace, DHL Express, specialized freight forwarders).
- No Sale of Customer Data: Winged Tycoons NEVER sells, rents, monetizes, or trades customer contact information, quote intelligence, or purchasing habits to third parties.

5. DATA RETENTION & ARCHIVAL MANDATES
In accordance with FAA Advisory Circular AC 00-56 and civil aviation records retention standards:
- Airworthiness trace certificates and serialized transaction logs are retained for a minimum of seven (7) years or for the operational service life of the airframe/engine component.
- Session logs and authentication security telemetry are retained for 365 days for audit defense.

6. INFORMATION SECURITY & SAFEGUARDS
All customer data in transit is protected using TLS 1.3 encryption. At rest, sensitive documents and customer quote repositories are safeguarded with AES-256 encryption, isolated access controls, and rate-limiting safeguards.

7. CLIENT RIGHTS & PRIVACY OFFICER
Authorized corporate representatives may request a complete export of their RFQ and PO history, request correction of account information, or submit compliance inquiries by contacting:
- Data Protection & Compliance Officer: privacy@wingedtycoons.com
- Operations Command: support@wingedtycoons.com

8. ACCEPTANCE & CORPORATE BINDING
By checking the acknowledgment box and entering the portal, you confirm that you are an authorized representative of your enterprise and that your organization agrees to these privacy and aerospace data handling terms.`;

    const blob = new Blob([policyText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'Winged_Tycoons_Customer_Privacy_Policy_v1.0.txt';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-modal-title"
      className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-md animate-in fade-in duration-200"
    >
      <div className="relative flex max-h-[92vh] w-full max-w-3xl flex-col rounded-3xl border border-slate-700 bg-slate-900 text-slate-100 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 id="privacy-modal-title" className="font-display text-lg font-bold text-white">
                  Customer Privacy Policy &amp; Data Governance
                </h2>
                <span className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] font-semibold text-cyan-400 border border-cyan-500/30">
                  Version 1.0
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Winged Tycoons Aerospace • Commercial Aviation Data Handling Standards
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={downloadCopy}
              title="Download text copy"
              className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:border-slate-600 hover:bg-slate-700 hover:text-white transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Download</span>
            </button>
            {isReadOnly && onClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="rounded-xl border border-slate-700 p-2 text-slate-400 hover:border-slate-600 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* First-time onboarding banner if mandatory */}
        {!isReadOnly && (
          <div className="border-b border-amber-500/20 bg-amber-500/10 px-6 py-3 text-xs text-amber-200 flex items-center gap-2.5">
            <AlertCircle className="h-4 w-4 shrink-0 text-amber-400" />
            <span>
              <strong>First-Time Sign-In Requirement:</strong> To maintain strict FAA/EASA traceability and protect proprietary quotation data, please review and accept our customer privacy terms before continuing.
            </span>
          </div>
        )}

        {/* Scrollable Policy Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 text-sm leading-relaxed text-slate-300 space-y-6">
          {/* Section 1 */}
          <section className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="font-semibold text-white flex items-center gap-2 mb-2 text-sm">
              <Building2 className="h-4 w-4 text-cyan-400" />
              1. Scope &amp; Commercial Aviation Procurement
            </h3>
            <p className="text-xs text-slate-400">
              Winged Tycoons Inc. operates an advanced aerospace procurement platform connecting commercial airlines, MRO facilities, and defense contractors with certified aviation suppliers. This Privacy Policy governs all information processed through our digital portal, quotation systems, and parts fulfillment network.
            </p>
          </section>

          {/* Section 2 */}
          <section className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="font-semibold text-white flex items-center gap-2 mb-2 text-sm">
              <FileText className="h-4 w-4 text-cyan-400" />
              2. Information We Collect
            </h3>
            <p className="text-xs text-slate-400 mb-2">
              To process your inquiries and fulfill commercial aviation orders, we collect the following categories of data:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-xs text-slate-300">
              <li>
                <strong className="text-slate-200">Account Credentials &amp; Contact:</strong> Work email address, company affiliation, buyer name, billing address, and phone numbers.
              </li>
              <li>
                <strong className="text-slate-200">RFQ &amp; Procurement Specifications:</strong> Requested part numbers, quantities, condition codes (FN, NE, OH, SV, AR), target pricing, quotation references, and purchase order documents.
              </li>
              <li>
                <strong className="text-slate-200">Regulatory &amp; Airworthiness Compliance:</strong> FAA 8130-3 forms, EASA Form 1 certificates, Certificates of Conformity (CoC), Non-Incident Statements (NIS), and export control classifications (EAR / ITAR).
              </li>
              <li>
                <strong className="text-slate-200">Security Telemetry:</strong> One-time code authentication verification, cryptographic session tokens, IP metadata, and audit event records.
              </li>
            </ul>
          </section>

          {/* Section 3 */}
          <section className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="font-semibold text-white flex items-center gap-2 mb-2 text-sm">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              3. Regulatory Compliance &amp; Anti-Counterfeit Protections
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              In accordance with <strong className="text-slate-200">FAA Advisory Circular AC 00-56</strong>, civil aviation traceability standards, and US export control laws (EAR/ITAR), processing of quote and trace data is required to prevent Suspected Unapproved Parts (SUP) and ensure uninterrupted chain-of-custody verification from accredited sources to installation.
            </p>
          </section>

          {/* Section 4 */}
          <section className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="font-semibold text-white flex items-center gap-2 mb-2 text-sm">
              <Lock className="h-4 w-4 text-cyan-400" />
              4. Strict Third-Party Disclosure Rules — No Data Selling
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed mb-2">
              Winged Tycoons does <strong className="text-slate-200">NOT</strong> sell, rent, license, or monetize customer procurement data, contact information, or quotation history to advertisers or third-party brokers.
            </p>
            <p className="text-xs text-slate-400 leading-relaxed">
              Data is disclosed strictly on a need-to-know basis to:
            </p>
            <ul className="list-disc pl-5 mt-1.5 space-y-1 text-xs text-slate-300">
              <li>Verified aerospace suppliers holding physical inventory to confirm availability and fulfill your order.</li>
              <li>Licensed bonded logistics providers (FedEx Aerospace, DHL Express) for air cargo delivery and customs clearance.</li>
              <li>Regulatory aviation authorities when mandated under lawful subpoena or aviation safety directives.</li>
            </ul>
          </section>

          {/* Section 5 */}
          <section className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="font-semibold text-white flex items-center gap-2 mb-2 text-sm">
              <FileText className="h-4 w-4 text-purple-400" />
              5. Mandatory Aerospace Document Retention
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Airworthiness tags, serialized parts history, and signed purchase orders are archived for a minimum period of <strong className="text-slate-200">seven (7) years</strong> or the operational service life of the relevant aircraft component, in direct adherence with international aviation recordkeeping requirements.
            </p>
          </section>

          {/* Section 6 */}
          <section className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
            <h3 className="font-semibold text-white flex items-center gap-2 mb-2 text-sm">
              <Lock className="h-4 w-4 text-amber-400" />
              6. Security Safeguards &amp; Data Subject Rights
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              All communications and vault documents are encrypted with TLS 1.3 and AES-256. Authorized client representatives may request records access, corrections, or inquiries by contacting our dedicated data privacy office at <span className="font-mono text-cyan-400">privacy@wingedtycoons.com</span>.
            </p>
          </section>
        </div>

        {/* Footer with Acceptance or Close */}
        <div className="border-t border-slate-800 bg-slate-950/80 px-6 py-4 rounded-b-3xl">
          {errorMessage && (
            <p className="mb-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {errorMessage}
            </p>
          )}

          {isReadOnly ? (
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">
                Winged Tycoons Customer Privacy Policy • Active Version 1.0
              </span>
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl border border-slate-700 bg-slate-800 px-5 py-2.5 text-xs font-semibold text-white hover:bg-slate-700 transition-colors"
              >
                Close
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <label className="flex items-start gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  id="agree-privacy-policy"
                  checked={hasAgreed}
                  onChange={(e) => setHasAgreed(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-slate-900"
                />
                <span className="text-xs text-slate-300 leading-normal">
                  I confirm that I am authorized to represent {companyOrEmail ? <strong className="text-white">{companyOrEmail}</strong> : 'my organization'}, and I accept the Winged Tycoons Customer Privacy Policy and commercial aerospace data processing standards.
                </span>
              </label>

              <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-1">
                {onDecline ? (
                  <button
                    type="button"
                    onClick={onDecline}
                    disabled={isSubmitting}
                    className="w-full sm:w-auto rounded-xl border border-slate-700 px-4 py-2.5 text-xs font-medium text-slate-400 hover:border-slate-600 hover:text-white transition-colors"
                  >
                    Decline &amp; Sign Out
                  </button>
                ) : <div />}

                <button
                  type="button"
                  onClick={handleAccept}
                  disabled={!hasAgreed || isSubmitting}
                  className="w-full sm:w-auto flex items-center justify-center gap-2 rounded-xl bg-cyan-500 px-6 py-2.5 text-xs font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-cyan-500/20 transition-all"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  <span>{isSubmitting ? 'Recording Acceptance...' : 'Accept & Enter Portal'}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
