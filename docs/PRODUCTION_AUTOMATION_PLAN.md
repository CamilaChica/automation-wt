# Production Automation Improvement Plan

**Last updated:** 2026-10-04
**Goal:** Improve the reliability, accuracy, and usability of existing functionality quickly, without adding business features or replacing the architecture.
**Plan status:** In progress. Focused local changes are underway for supplier-ingestion batch bounds and supplier HTML-table extraction; existing portal/document paths are being verified before changing them.

## Production baseline and known issues

- Existing customer portal: <https://portal.wingedtycoons.com/customer-portal> and <https://winged-tycoons-customer-portal.onrender.com>.
- Existing internal portal: <https://team.wingedtycoons.com/internal>.
- Existing API: <https://api.wingedtycoons.com> and <https://winged-tycoons-api.onrender.com>.
- The last verified API readiness check returned HTTP 200, healthy PostgreSQL, full operational persistence, and current/expected migration `0013_database_business_policies`. This supersedes the October 2 migration observation.
- Releases `46cdc7b2` and `7610e7b8` deployed the DSPy communications corpus, guarded catalog-inquiry protocol, and bounded OCR inference to the existing services.
- Supplier ingestion reported another memory failure above 2 GB after the OCR deployment, followed by recovery. Long-term memory stability is not established.
- Portal recheck on 2026-10-04: a read-only request from `team.wingedtycoons.com` to the API reached the endpoint and returned HTTP 401, consistent with the visible secure sign-in page. The cross-origin request was not blocked by CORS. Authenticated portal data loading was not verified because no sign-in was performed.
- See [Production Decisions](./PRODUCTION_DECISIONS.md) and [Application Runtime Audit](../APPLICATION_RUNTIME_AUDIT.md) for supporting observations and limitations.

## Scope and operating rules

- Keep the existing PostgreSQL-backed workflows, guarded tools, DSPy/Pydantic extraction, workers, and outbox.
- AI interprets and drafts; deterministic services control pricing, inventory, approval, persistence, and transactional actions.
- Preserve concurrent work from other chats. Review the current worktree before each batch and stage only intended changes.
- Reuse existing services. No new services, hosting upgrades, framework migration, or recurring costs without owner approval.
- No sample customer emails, diagnostic PartsBase RFQs, paid model optimization, or external tracing of private business data.
- Run the smallest relevant checks, using deterministic fixtures for mutations and third-party behavior. Avoid repeated full-suite runs.
- Credential rotation remains deferred by the owner and is not a release gate.
- Locally installed packages do not change production dependencies. Declare and integrate a package only when an approved task needs it.

## Batch 1: Reliability and access

Release this batch independently rather than waiting for later improvements.

### Step 1: Stabilize supplier ingestion

- [ ] Locate memory accumulation in full-email/MIME fetching, attachment decoding, PDF rendering, OCR, and retry paths.
- [x] Bound live polling and historical backfill fetch pages to five messages by default, capped at ten for live polling and at the live batch size for backfill.
- [ ] Measure attachment/OCR memory and observe the deployed worker; the fetch bound is a mitigation, not proof the 2 GB failure is resolved.
- [ ] Avoid retaining whole-mailbox batches, decoded documents, and rendered pages longer than needed.
- [ ] Verify interrupted processing resumes without duplicate inventory records or outbound requests.
- [ ] Prevent historical backfill from overwhelming current incoming-mail processing.

**Completion evidence:** Representative attachment processing stays within the existing 2 GB worker budget with documented headroom; restart/retry preserves progress without duplicates. Record the production observation interval and any new failures. Deployment success alone is not proof of long-term stability.

### Step 2: Resolve remaining portal access failures

- [x] Recheck the internal portal origin against the current API with a read-only cross-origin request; the API returned 401 rather than a CORS failure.
- [ ] Fix only failures that still occur, preserving credentialed CORS and authentication protections.
- [ ] Verify existing RFQ, mailbox-health, extraction-review, and automation-activity screens in an authenticated session; current shared browser is at secure sign-in.
- [ ] Distinguish expired sessions from API outages in existing error handling.

**Completion evidence:** Supported portal origins pass credentialed preflight; authenticated read-only screens load without recurring CORS errors or unexpected authentication failures. Anonymous HTTP 401 responses remain expected where authentication is required.

## Batch 2: Extraction and document accuracy

### Step 3: Improve supplier-email extraction

- [x] Integrate BeautifulSoup4 into existing HTML-email parsing and declare it in `requirements.txt`.
- [x] Preserve table-row and cell boundaries in parsed HTML email text; a focused regression covers a two-part, two-currency supplier table.
- [ ] Retain source references through validation and persistence.
- [ ] Keep missing values explicit and prevent quoted historical text from overwriting current offers.
- [ ] Preserve existing DSPy/Pydantic validation and deterministic business rules.

**Completion evidence:** Representative multi-part emails preserve row associations, currencies, quantities, and unknown fields. Ambiguous facts enter review instead of becoming invented data. Requested quantity is not treated as available stock, and supplier offers are not treated as owned inventory.

**Local validation so far:** Nine mailbox/ingestion unit tests and twelve customer-document/OCR tests passed. Production deployment and worker memory observation for the current local changes are still pending.

### Step 4: Tighten document comparison and attachment selection

- [ ] Strengthen existing PN/SN, issuer, date, condition, release-statement, and traceability comparisons.
- [ ] Keep critical conflicts visible regardless of an overall similarity score.
- [ ] Preserve original documents and page-level evidence where available.
- [ ] Verify customer replies attach documents for the exact requested part/serial/offer.
- [ ] Verify PO notifications retain the original PO and supporting attachments.

**Completion evidence:** Mismatched or unreadable certificates are held for review; customer document responses and PO notifications select the correct files. Better readability does not establish authenticity or replace existing approval safeguards.

## Batch 3: Communication and operational clarity

### Step 5: Harden replies, follow-ups, and retries

- [ ] Trace customer and supplier replies through existing threads and RFQs.
- [ ] Stop obsolete follow-ups after replies, POs, holds, closures, or superseding offers.
- [ ] Distinguish queued, provider-accepted, failed, and uncertain send outcomes; do not claim delivery without evidence.
- [ ] Reconcile uncertain sends before retrying.
- [ ] Preserve catalog-miss, PN-confirmation, No Quote, automatic-mail exclusions, and mixed-request review behavior.

**Completion evidence:** One relevant response per triggering event, no duplicate outreach after retries, no chasing closed/superseded requests, and failed replies remain actionable. PO receipt acknowledgements do not imply acceptance or shipment.

### Step 6: Clarify agent states and operator actions

- [ ] Reconcile the meaning of existing statuses across workers and portal views.
- [ ] Use existing audit/review surfaces to show what happened, supporting evidence, the hold reason, the next action, and whether Camila must act.
- [ ] Remove misleading success labels and contradictory state presentation.
- [ ] Preserve deterministic financial limits, approval rules, and the 5% maximum automatic USD discount request.

**Completion evidence:** An operator can understand a held RFQ and its next action without investigating raw logs. No additional dashboard, agent framework, or business capability is required.

## Conditional optimization: Knowledge retrieval

### Step 7: Optimize only if measurement justifies it

- [ ] Measure current retrieval usage, record volume, latency, and memory before choosing an optimization.
- [ ] If a bottleneck is confirmed, compare supported PostgreSQL vector indexing with the existing Qdrant integration and select one approach.
- [ ] Preserve access filtering, freshness, citations, and authoritative exact PN/SN matching.
- [ ] Compare the chosen approach on the same representative corpus before rollout.

**Completion evidence:** Improved retrieval latency and memory use without weaker filtering or evidence quality. This step is not a release dependency and must not delay Batches 1-3. It is not an assumed explanation for supplier-worker memory failures.

## Library decisions

- **Prioritize:** BeautifulSoup4 for existing supplier HTML/table extraction.
- **Use selectively:** HTTPX where blocking HTTP is demonstrated; Qdrant client only if needed by the selected indexed-retrieval approach.
- **Evaluate later:** Instructor only if it improves the existing extraction adapter without stacking retry systems.
- **Defer:** LangChain, LangGraph, Pydantic AI, LlamaIndex, ChromaDB, FAISS, local Sentence Transformers, and a Psycopg 3 migration without a concrete requirement.
- **Observability:** Improve existing audit records first. External LangSmith tracing requires explicit approval and strict controls on private and export-controlled data.

## Batch execution and release procedure

1. Inspect current changes and account for concurrent work.
2. Reproduce only the specific issue being addressed.
3. Make coherent, surgical changes that preserve current behavior and safeguards.
4. Run the smallest relevant checks; add focused regressions for changed behavior.
5. Review and commit intended source/configuration/documentation changes only. Exclude installed dependencies and generated test artifacts.
6. Push once per completed batch to the existing services; confirm the intended revision actually deploys.
7. Perform safe, read-only production verification and record observed outcomes and remaining limitations.

Do not run a broad Render Blueprint Sync or delete suspended services without reviewing current configuration and recovery needs. October 2 service counts and manifest warnings are historical observations, not a current inventory.

## Preserved onboarding and approval rules

- Customer accounts are created on the first eligible email OTP request; bulk customer-user import is not required for sign-in.
- Real OTP delivery is confirmed through intended users' normal onboarding, not diagnostic emails.
- Internal staff accounts remain approval-controlled.
- PO submissions remain subject to human approval before fulfillment.
- SMS, new analytics/maps features, backup cleanup, and historical SQLite import remain out of scope.

## Success criteria

Fewer interrupted jobs, fewer incorrect extracted facts, no duplicate outreach, correctly matched documents, reliable portal access, and less manual investigation. Completion is based on recorded evidence, not the number of libraries or agents introduced.

**First pending action:** Release the focused worker/HTML parsing changes to the existing services, then observe worker memory. Authenticated portal verification requires the normal operator sign-in; do not send a diagnostic OTP.
