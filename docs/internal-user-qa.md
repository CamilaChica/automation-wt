# Internal User Q&A

## 1. What is the internal portal used for?

The internal portal is the operations dashboard for approved Winged Tycoons staff. Depending on assigned access and available services, it provides views for dashboard activity, sales/RFQs, supplier sourcing, procurement, trace records, fulfillment, audit events, and employee profile/timekeeping. It is an operator workspace, not a guarantee that every displayed record or sample metric is live production data. See [docs/API_UI_MAPPING.md](API_UI_MAPPING.md) for route roles, view bindings, and sample-data boundaries.

Internal users use it to:

- review incoming RFQs
- check inventory availability
- assess supplier options
- validate compliance and traceability
- review pricing and margin thresholds
- approve or reject quote proposals
- monitor agent activity and audit history

## 2. Where do I start?

Open the internal route in the deployed frontend or run the local app:

- Local: http://localhost:3000/internal
- Deployed: https://winged-tycoons-frontend.onrender.com/internal

Sign in with an approved `@wingedtycoons.com` staff account and complete email OTP verification. Production email delivery must be configured; local development OTP behavior is not suitable for production. Internal access and customer access use separate roles. If internal OTP sign-in is unavailable, contact the system administrator rather than switching to a customer role.

## 3. What is an RFQ?

An RFQ is a request for quotation. It includes the requested part number, quantity, urgency, destination, and delivery requirements. In this system, an RFQ can be submitted from raw customer text, an email, or the internal user interface.

## 4. How does an RFQ move through processing?

The workflow follows this general path:

1. Intake
2. Parsing and item extraction
3. Internal inventory lookup
4. Supplier sourcing fallback
5. Compliance review
6. Pricing and margin check
7. Human approval or rejection
8. Quote sent status

If extraction fails, a compliance check fails, or a workflow dependency is unavailable, the RFQ may remain pending or enter a failure/warning state. Check the actual RFQ detail and audit data; do not infer completion from a dashboard count or sample view.

## 5. What happens when inventory is insufficient?

The workflow can attempt supplier discovery when internal stock is unavailable. Supplier replies, shared persistence, and pipeline resumption must be verified for the current deployment before treating this as a completed live transaction. A sourcing request is not the same as a customer quote.

## 6. What does compliance review check?

Compliance review examines traceability, certificate validity, condition status, and related publication or documentation requirements. If a required record is missing, the system can halt the processing flow and escalate for human review.

## 7. How is a quote priced?

Pricing is based on the selected source item and configured margin rules. Default settings are defined in `config/settings.py`, including a target margin and threshold below which a quote may require escalation.

## 8. What if the quote is below margin threshold?

The system may flag the quote for review. Internal operators can adjust pricing, validate commercial assumptions, or reject the quote before final transmission.

## 9. What is the approval step?

Approval is the human-in-the-loop gate. Internal users confirm the quote or reject it with notes. This step prevents incorrect or noncompliant offers from being sent externally.

## 10. Where do I see tool activity or audit logs?

Use the audit drawer, RFQ detail panel, and relevant view to inspect available activity. Validate important outcomes against persisted records and service logs. Sample/demo telemetry is labeled as such and is not evidence of live shipment, mailbox, or RFQ activity.

## 11. Are there test or demo flows for internal users?

Yes. Local tests and mock UI fixtures cover scenarios such as:

- clean flow with in-stock parts
- sourcing fallback with quantity shortages
- compliance halt and escalation
- approval/rejection confirmation and duplicate-submit protection

These tests do not perform production writes and do not prove live PostgreSQL, worker, mailbox, or customer-email behavior. See [docs/AUTO_CRAWLER_FINDINGS.md](AUTO_CRAWLER_FINDINGS.md) for the recorded verification and remaining release gates.

## 12. What should I do if the workflow stalls?

Check the following:

- API service is healthy
- Frontend is pointing to the correct backend
- RFQ has a current status and available audit entries
- A compliance exception has not triggered a warning state
- Pricing or sourcing stage is waiting on manual review

For an intake failure, the UI does not currently expose a retry/reprocess API. Quote issuance, sourcing, and trace actions are disabled for failed RFQs. Escalate to intake operations; do not claim the request was reprocessed until a new persisted outcome is confirmed.

## 13. What is not available to internal users?

Internal users should use the internal role and assigned account. Role checks separate customer and internal API access. Do not use customer credentials to bypass internal sign-in or share sessions between users.

## 14. What are the most important operational safeguards?

- Verify the backend is running before attempting quote workflows
- Confirm approval and rejection actions are recorded
- Keep compliance warnings visible and resolved before sending a quote
- Use the audit timeline and persisted data to verify source, traceability, and margin decisions
- Confirm destructive or external actions before submission; wait for completion feedback and avoid duplicate submissions
- Do not treat `/healthz`, a cached dashboard, or an HTTP-200 `/ready` response as proof of PostgreSQL-primary persistence or a sent email

## 15. What if the backend or frontend cannot be reached?

- Confirm the FastAPI backend is running on port 8000
- Confirm the frontend dev server is running on port 3000
- Ensure the frontend `/api` proxy points at the correct backend
- Re-check local environment variables and service configuration

## 16. What is the production release status?

Production is not signed off. The release plan still requires verified shared PostgreSQL runtime behavior, live database integration, authenticated mailbox checks, an end-to-end RFQ-to-sent-email trace, and controlled staging mutation/rollback tests. See [docs/PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md) for current gates. Do not deploy backend or resume workers based only on local test success or historical health responses.

## 17. What do status labels or empty queues mean?

Use the selected RFQ's actual API/detail data to interpret its status. “Pending extraction” means a part number has not been extracted yet; “Intake failed” means downstream quote, sourcing, and trace mutations are disabled. An empty queue may mean there are no records or the data did not load; check for an explicit load error and use the view's read retry only to reload data. It does not reprocess an RFQ.

## 18. How do I update my employee profile or record work hours?

Use the employee profile controls to update your display name or job title, set presence, and clock in or out. A conflicting clock action may return a conflict; do not repeatedly submit it. The work-hours view provides your monthly totals. The HR work-hours endpoint is restricted to admin/manager roles. These endpoints require an authenticated internal session.

## 19. Which internal panels are live data?

Use [docs/API_UI_MAPPING.md](API_UI_MAPPING.md) to check each panel. RFQ queues, supplier offers, shipments, automation events, and profile/timekeeping have API bindings. Some AOG counts, performance estimates, document panels, trace history/KPIs, and fulfillment-stage graphics remain sample/demo content where the mapping says there is no backend read contract. Do not use sample content as an operational decision or customer commitment.
