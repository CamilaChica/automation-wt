# Production Architecture Decisions

Status: production integration release; live verification is performed against the existing Render services.

## Frontend

`apps/web` is the production customer frontend because it is the frontend selected by `render.yaml`. The Vite `frontend/` application remains an internal command-center/development surface until it is either retired or explicitly deployed as a separate internal service.

The selected frontend and remaining release checks are tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

## Persistence

Production shared state uses managed PostgreSQL. SQLite remains local/test-only because API and worker services cannot safely share independent local disks. The production `/ready` read-only check on 2026-10-04 confirmed healthy PostgreSQL, complete operational persistence, and current/expected migration `0012_supplier_offer_received_at`.

This release adds migration `0013_database_business_policies`, which creates and seeds an advisory-policy table without altering existing business records. The existing API pre-deploy command applies the migration; successful rollout is confirmed when `/ready` reports current/expected `0013_database_business_policies`. DSPy policy results are advisory; the existing backend policy gate remains authoritative for dispatch.

### Live email-program integration

With both `DSPY_ENABLED=true` and `LLM_LIVE_ENABLED=true`, the main quote dispatch/approval paths record database-backed policy recommendations in the RFQ audit trail. Missing confidence or sanctions evidence remains unknown; the recommendation cannot approve, reject, or mutate a quote.

Supplier missing-information requests use the real `supplier_communication` task in both synchronous and asynchronous ingestion paths. Generated subjects, requested fields, business paragraphs and signatures must match the verified template exactly, with confidence at least 0.92. Only prescribed greetings and signoffs may vary. Invalid output, missing policy records, configuration errors and provider failures are logged and explicitly marked `unavailable`; delivery retains the verified template, original recipient/thread and existing outbox deduplication.

Initial supplier RFQs and stale-offer confirmations also invoke that live drafting task automatically. Outreach uses RFQ-specific deduplication keys independent of generated wording; confirmations stay on the original supplier thread, while a new customer RFQ can generate a separate supplier request. Unknown catalog parts now trigger the same automatic customer sourcing update as inventory shortages, without claiming supplier contact succeeded when nothing was queued.

Customer acknowledgement, in-thread answers, sourcing updates, verified quotations and scheduled followups use the existing mailbox workers and transactional outbox automatically; deterministic commercial templates are real communications, not simulated provider responses. Purchase orders and existing compliance/review holds remain human-gated. The Render blueprint enables shared production PostgreSQL and live DSPy on the supplier-ingestion worker, and live DSPy plus the customer portal origin on the RFQ-resume worker. Blueprint changes require deployment and actual secret configuration before they affect running services; no test success establishes live delivery.

Deterministic unit tests remain isolated from external services. Real integration checks are opt-in:

```powershell
$env:DSPY_ENABLED = "true"
.\.venv\Scripts\python.exe -m pytest tests\integration\test_llm_integrations.py --run-live-llm -k "real_dspy or configured_provider_can_be_reached"
```

These checks reuse the existing `live_llm` safety gate (`--run-live-llm` or `RUN_LIVE_LLM=1`). The two DSPy checks use configured provider credentials and read the configured business-policy database without mocking either. They generate paid model calls with synthetic inputs only; they never send email, write business records, run migrations or deploy. Missing credentials or unapplied policy migrations fail the opted-in DSPy checks rather than reporting a simulated success. The existing transport check skips explicitly when its credential is missing. Provider selection uses the normal `LLM_TASK_PROVIDERS` and `LLM_DEFAULT_PROVIDER` settings.

The remaining repository cutover, data reconciliation, restore, and reliability work is tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

## Supplier document evidence and PO notification attachments

Supplier ingestion now reads PDF text, locally OCRs scanned PDF pages and images, and extracts Word DOCX paragraphs. OCR uses bundled RapidOCR ONNX models locally; supplier documents are not submitted to an additional OCR service. Documents are limited to 25 MB, PDFs to 30 pages, and OCR renders to 20 megapixels. OCR text below 0.85 confidence is withheld for review. Legacy binary DOC and unsupported/corrupt files are explicitly unreadable, not silently treated as certificate evidence.

The existing supplier-ingestion worker uses Render's Standard plan (1 CPU, 2 GB RAM, $25/month). The owner approved this upgrade after repeated 512 MB out-of-memory failures. The blueprint pins that plan so subsequent synchronization does not restore the undersized worker.

Certificate analysis preserves file SHA-256, source filename, labelled part/serial/condition, issuer, certificate/repair-station numbers and issue date when present, plus the source text for each extracted fact. Unreadable certificate candidates, unrecognized certificate types, ambiguous fields, and contradictory serial/condition evidence enter the existing operator-review queue before supplier offers are stored. Matching fields are reported as `FIELDS_CONSISTENT`, never as proof of authenticity or airworthiness; issuer validation and final compliance/release decisions remain separate.

Customer document replies retrieve the original supplier MIME, read the documents and attach only recognized certificates with an unambiguous matching part number and matching serial when known. Requests mentioning a specific quoted part are restricted to that part. Unreadable/unmatched evidence, contradictory item mapping, and documents containing supplier pricing are not released; the existing document-unavailable response is used instead. Original bytes are retained.

Portal and inbound-email PO notifications already pass attached order/supporting files into the durable mail outbox. Portal uploads now preserve sanitized original filenames for notification attachments, with a backward-compatible hashed filename for older uploads. The duplicate PO attachment read was removed. Focused checks cover all three PO documents and exact outbox attachment bytes without sending messages.

## Rate Limiting

Production rate-limit state must use Redis or the deployment edge. The current in-process limiter is a single-instance safety net and is not the final multi-instance implementation.

The remaining rate-limit provider decision and validation are tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

## Billing

Initial launch uses manual/offline invoicing and purchase-order acceptance. No payment-provider promises are made to customers until a payment integration is implemented and reconciled with orders. No payment integration is currently in the release scope.

## Mailboxes

The API and mailbox worker remain separate services. The remaining credential, permission, ownership, and staging-delivery checks are tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).
