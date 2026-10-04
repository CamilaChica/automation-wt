# Backend API to Frontend UI Mapping

This inventory reflects the FastAPI routes in `api/main.py`; the backend currently uses `/api`, not `/api/v1`. The UI calls these endpoints through `frontend/src/services/api.ts` and the shared resource hooks in `frontend/src/hooks/useApiResources.ts`. The webhook route is server-to-server only and must not be called by browser code.

The frontend no longer substitutes sample RFQs, inventory, supplier records, catalog results, or voice data when an API request fails. It uses the API response or surfaces the request error. Deterministic fixtures remain test-only. This client-side change does not certify production readiness or replace the PostgreSQL runtime cutover gate.

The external Next.js customer portal calls only its same-origin `/api/customer/*` route handlers. Those handlers allowlist the required customer operations, keep the backend session token in an HttpOnly cookie, verify request origins on writes, and omit internal attachment metadata and notification details from responses.

## Health and identity

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /` | Public | None | Service name/version metadata; operational status panel only. |
| `GET /healthz` | Public | None | `{status}` liveness response. |
| `GET /ready` | Public | None | Readiness, database health, mirroring and persistence status. TopBar `useSystemHealth`; production can return 503 until PostgreSQL cutover gates pass. |
| `POST /api/auth/otp/request` | Public | `OtpRequest` | Challenge ID and development OTP when configured. Auth screen. |
| `POST /api/auth/otp/verify` | Public | `OtpVerifyRequest` | HttpOnly session cookie; role and email only in response. Auth screen. |
| `GET /api/auth/session` | Authenticated session cookie | None | Current session email and role; used by the customer portal gate. |
| `POST /api/auth/logout` | Session cookie | None | Revokes the server-side session and removes the cookie. |
| `POST /api/session` | Customer or internal roles | `VoiceSessionRequest` | Ephemeral voice client secret and model. Voice service. |

## Customer, RFQ, and quote workflows

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `POST /api/rfqs/intake` | Authenticated customer/internal | `IntakeRequest` | `IntakeResponse` (`rfq_id`, status, message). The external customer portal sends a structured request through its server-side proxy. |
| `GET /api/rfqs` | Customer sees own records; internal roles see queue | None | `RFQ[]`. Customer dashboard, Sales, Procurement, Sourcing, Trace. `useRFQs`. |
| `GET /api/rfqs/{rfq_id}` | Authenticated; customer ownership checked | Path `rfq_id` | RFQ, items and optional quote detail; customers only see sent quotes, and internal response also includes audit logs. |
| `GET /api/quotes/{quote_id}` | Customer; sent quote ownership checked | Path `quote_id` | Customer-safe sent quote totals, items, quote status, and RFQ status for the external portal. Internal costs and audit details are never returned. |
| `POST /api/rfqs/{rfq_id}/process` | Admin/manager/sales/purchasing | Path `rfq_id` | Procurement explicitly starts pipeline processing for an RFQ in `Intake`; this endpoint does not itself reset failed intake. |
| `POST /api/internal/rfqs/{rfq_id}/reset-intake` | Admin/manager | `reason` (required, 1-1000 characters) | Procurement resets only `Intake_Failed` to `Intake`, records the operator/reason in the audit log, and requires a separate explicit process action. `NEEDS_HUMAN_REVIEW` is rejected. |
| `POST /api/quotes/{quote_id}/approve` | Admin/manager/sales | `ApproveRequest` | Approval/dispatch result. A queued PostgreSQL outbox message returns `Quote_Dispatch_Pending`/`PENDING` without advancing persisted RFQ or quote status; statuses advance to `Quote_Sent`/`Sent` only after delivery is confirmed `SENT`. Ambiguous delivery moves the records to operator review. Customer Dashboard uses `useDispatchQuote`; Sales issues a quote. |
| `POST /api/quotes/{quote_id}/reject` | Admin/manager/sales | `RejectRequest` | Rejection result. Sales Command rejects the selected quote with an audited reason. There is no quote-collection view. |
| `POST /api/purchase-orders` | Authenticated; customer quote ownership checked; sent quote required | `PurchaseOrderRequest` with three unique, already-uploaded valid PDF attachment IDs | `Pending_PO_Review`, PO and quote IDs. The external portal uploads signed export-certification, KYC, and purchase-order documents before submitting; this is not quote approval. |
| `POST /api/purchase-orders/{quote_id}/approve` | Admin/manager/purchasing | `PurchaseOrderApprovalRequest` | Backend approval mutation updates the RFQ. There is no registered pending-PO list endpoint, so the internal UI cannot discover and review queued POs end to end. |
| `GET /api/attachments/{attachment_id}` | Authenticated and authorized | Path `attachment_id` | Binary attachment download. Sales/document preview. |
| `POST /api/attachments` | Authenticated and authorized | Multipart `file` | Accepted attachment ID/name/status only; storage paths and content hashes remain server-side. Customer RFQ and PO uploads. |

## Catalog and sourcing

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/catalog/search` | Customer/admin/manager/sales/purchasing | `query`, optional `condition` | Customer-safe catalog rows only. Portal search; frontend displays only API results and surfaces API errors. |
| `GET /api/inventory` | Admin/manager/purchasing | None | Role-gated Procurement inventory tab; uses the request-scoped async operational repository when enabled. Internal cost/location fields are not shown to sales/customer roles; frontend displays only API results. |
| `GET /api/suppliers` | Admin/manager/purchasing | None | Role-gated Procurement supplier directory; uses the request-scoped async supplier repository when enabled; frontend displays only API results. |
| `GET /api/suppliers/{supplier_id}` | Admin/manager/purchasing | Path `supplier_id` | Selected Procurement supplier profile; uses the request-scoped async supplier repository when enabled. |
| `GET /api/supplier-offers?part_number=...` | Admin/manager/purchasing/sales | Part number query | Supplier offers. Procurement and Sourcing use `useSupplierOffers`; the request-scoped async supplier repository is used when enabled. |
| `POST /api/internal/freight/quote` | Admin/manager/purchasing/sales | `FreightRequest` | Procurement collects route/weight/package/service inputs and shows provider rates or `DRY_RUN`; dry-run charges are not applied to quotes and no shipment is booked. |

## Internal operations and compliance

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `POST /api/internal/rfqs/{rfq_id}/automation` | Admin/manager | `AutomationPauseRequest` | Automation pause/resume result. Procurement exposes role-gated pause/resume controls and records an operator reason when pausing. |
| `POST /api/internal/rfqs/{rfq_id}/trace-decision` | Admin/manager/purchasing | `TraceDecisionRequest` | Decision and automation status. Trace Vault uses `useTraceDecision`, then invalidates RFQs/events. |
| `GET /api/internal/automation-events` | Admin/manager/sales/purchasing | Optional status/limit | Automation event list. TopBar audit feed and Trace Vault use `useAutomationEvents`. |
| `GET /api/internal/extraction-reviews` | Admin/manager/sales/purchasing | Optional status/limit | Pending operator extraction-review queue in Trace Vault. |
| `GET /api/internal/extraction-reviews/{review_id}` | Admin/manager/sales/purchasing | Path `review_id` | Selected source text, extracted fields, reason, and hold flags in Trace Vault. |
| `POST /api/internal/extraction-reviews/{review_id}/decision` | Admin/manager/sales/purchasing | `ExtractionReviewDecisionRequest` | Trace Vault approves the displayed extraction with server source-grounding validation or rejects it with operator comments. |
| `POST /api/internal/commands` | Admin/manager/sales/purchasing | `InternalCommandRequest` | Audited command result. Procurement, Sourcing and Fulfillment hooks invalidate relevant active resources. |
| `POST /api/internal/agents/orchestrate` | Internal/admin/manager/sales/purchasing | `query` (1-4000 characters), optional `response_mode` (`app` default or `human`) | Bounded model-led analysis using single-purpose, decorator-registered, Pydantic-validated catalog, inventory, supplier-search, pricing, exact RFQ lookup, exact supplier-offer lookup, and citation-backed RAG tools. The purchasing-only discount action queues one non-binding request against an exact approved USD supplier offer, is capped at 5%, rate-limited to one call per operator per 60 seconds, and audited; it cannot accept an offer or place an order. Database tools accept structured arguments, never model-generated SQL; responses omit raw documents and sensitive contact/source fields. `app` returns schema-validated structured JSON; `human` returns descriptive text in `data.log_message`. Other agents carry the discount contract as metadata only; the server registry controls execution. |
| `GET /api/internal/llm/health` | Admin/manager | None | Trace Vault shows provider routing, configuration booleans, and fallback status; no secret values. |
| `GET /api/internal/llm/telemetry` | Admin/manager | Optional task/limit | Trace Vault shows recent task/model, latency, token, estimated-cost, validation, and review-outcome telemetry. |
| `GET /api/internal/mailboxes/health` | Internal/admin/manager/sales/purchasing | None | Status strings for `sales_mailbox` and `purchasing_mailbox`, plus authenticated user. TopBar shows live status. |
| `GET /api/internal/mailboxes/{mailbox}/inbox` | Admin/manager/sales/purchasing, mailbox-specific role checked | Path `mailbox` | Procurement mailbox view shows message headers/body and attachment names/types; raw MIME and attachment contents are not returned. |
| `POST /api/internal/mailboxes/{mailbox}/send` | Admin/manager/sales/purchasing, mailbox-specific role checked | `MailboxMessageRequest` | Procurement send form requires recipient/subject/body and explicit confirmation; result is reported in the UI. |

## Fulfillment and carrier tracking

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `POST /api/internal/shipments` | Admin/manager/purchasing | `ShipmentCreateRequest` | Fulfillment Hub creates a shipment from an eligible RFQ after confirmation and shows the tracking-link notification result. |
| `GET /api/internal/shipments` | Admin/manager/purchasing | None | Persisted shipment records. Uses the request-scoped async repository when async persistence is enabled, with the local fallback preserved. Fulfillment Hub `useShipments` / `useFulfillmentStages`. |
| `POST /api/internal/shipments/{shipment_id}/events` | Admin/manager/purchasing | `ShipmentEventRequest` | Fulfillment Hub records a confirmed operational event and refreshes shipment state; uses an async repository transaction when enabled. |
| `POST /api/internal/shipments/{shipment_id}/tracking` | Admin/manager/purchasing | `CarrierTrackingRequest` | Fulfillment Hub registers carrier tracking after confirmation and displays provider result; shipment persistence uses the async repository when enabled. |
| `POST /api/internal/shipments/{shipment_id}/tracking/refresh` | Admin/manager/purchasing | Path `shipment_id` | Fulfillment Hub refreshes registered tracking after confirmation and displays the returned event; shipment lookup/event persistence use async repositories when enabled. |
| `POST /api/internal/shipments/{shipment_id}/sms` | Admin/manager/purchasing/sales | `ShipmentSmsRequest` | Fulfillment Hub sends an E.164 customer update after explicit confirmation; shipment lookup uses the async repository when enabled. Current shipment selection is restricted to admin/manager/purchasing roles. |
| `GET /api/shipments/track/{public_token}` | Public opaque token | Path `public_token` | Customer-safe trace: status, parts, quantity, carrier/tracking, ETA, events. Uses the request-scoped async repository when async persistence is enabled, with the local fallback preserved. Portal `useShipmentTrace`. There is no `GET /api/shipments/{id}`. |
| `POST /api/webhooks/carriers/aftership` | Signed provider request | Carrier webhook body/signature | Applies normalized carrier event. Backend-only. |

## Voice

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/voice/dashboard` | Internal/admin/manager/sales/purchasing | None | Voice operations dashboard derived from RFQs. |
| `POST /api/voice/tools/{tool_name}` | Customer/internal roles | `VoiceToolRequest` and, for concern recording, explicit `X-Human-Confirmed: true` | Inventory, order status or escalation tool response. Customer voice displays the concern details and waits for a confirmation click before recording. |

## Employee profile and time tracking

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/internal/profile` | Internal/admin/manager/sales/purchasing | None | Employee profile and presence/clock state. TopBar profile button and EmployeeProfilePanel. |
| `PATCH /api/internal/profile` | Internal/admin/manager/sales/purchasing | Display name and job title | Updated employee profile. |
| `PUT /api/internal/profile/presence` | Internal/admin/manager/sales/purchasing | Online flag | Updated employee profile. |
| `POST /api/internal/profile/clock` | Internal/admin/manager/sales/purchasing | `clock_in` or `clock_out` | Updated employee profile; conflicts return 409. |
| `GET /api/internal/work-hours?month=YYYY-MM` | Internal/admin/manager/sales/purchasing | Month query | Current employee hours and daily totals. |
| `GET /api/internal/hr/work-hours?month=YYYY-MM` | Admin/manager | Month query | HR report with employee totals. |

## View mapping and non-API content

The rows below identify demo-only sections that are not backed by live read APIs. They are not operational evidence and remain delivery blockers until hidden or mapped to persisted API data.

| View | Live bindings | Remaining sample/demo content |
| --- | --- | --- |
| TopBar | `/ready`, mailbox health, employee profile/presence, AOG count derived from live RFQs | Sidebar queue counts are removed until API-backed counts are available. |
| Customer Dashboard | RFQ list/detail, persisted quote totals/items and dispatch, internal shipment counts, RFQ creation with operator-entered customer identity | Quote comparisons and sample presets are removed; document previews and shipment milestones remain unavailable without read APIs. |
| Aero Procurement / Sourcing | RFQ queue, inventory/supplier directories, supplier offers, mailbox, and freight quote requests | Supplier-performance, AOG workload, lead-time and document-evidence panels show unavailable states because no live reporting/evidence API exists. |
| Fulfillment Hub | Shipment list/stage, shipment creation, event and carrier tracking controls for admin/manager/purchasing; SMS is confirmation-gated | Sample inspection, packaging, compliance and route panels are removed; persisted telemetry is not available from the current API. |
| Trace Vault | RFQs, extraction review records/decisions, LLM telemetry, and compliance-related automation events | Fabricated OCR/certification controls and milestone history are removed; per-document checklist and milestone endpoints are not registered. |
| Customer Portal | API-backed catalog search, RFQ/attachment upload, customer PO and token-based shipment trace | Client sample fallback is removed; API failures surface as errors. |

## Contract gaps

- The backend does not expose `GET /api/v1/quotes`, `POST /api/v1/quotes/{id}/dispatch`, `GET /api/v1/fulfillment/stages`, or `GET /api/shipments/{id}`. Existing quote data comes from `GET /api/rfqs/{rfq_id}` and quote dispatch from `POST /api/quotes/{quote_id}/approve`.
- The pending-PO list route is not registered. The backend has a PO-approval mutation, but without a list endpoint the internal UI cannot discover and review queued POs end to end.
- `useFulfillmentStages` derives a single human-readable stage from each persisted shipment status. It does not claim that the backend returned a multi-stage milestone history or inventory reservation.
- Compliance evidence and historical KPI endpoints do not exist. Those panels remain visibly sample until backend read contracts and persisted data are added.

## Delivery Plan

The API/UI contract inventory and sample-data boundaries are documented above. All remaining implementation and end-user release actions, in execution order, are maintained only in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).
