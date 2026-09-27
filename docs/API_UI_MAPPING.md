# Backend API to Frontend UI Mapping

This inventory reflects the FastAPI routes in `api/main.py`; the backend currently uses `/api`, not `/api/v1`. The UI calls these endpoints through `frontend/src/services/api.ts` and the shared resource hooks in `frontend/src/hooks/useApiResources.ts`. The webhook route is server-to-server only and must not be called by browser code.

## Health and identity

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /` | Public | None | Service name/version metadata; operational status panel only. |
| `GET /healthz` | Public | None | `{status}` liveness response. |
| `GET /ready` | Public | None | Readiness, database health, mirroring and persistence status. TopBar `useSystemHealth`; production can return 503 until PostgreSQL cutover gates pass. |
| `POST /api/auth/otp/request` | Public | `OtpRequest` | Challenge ID and development OTP when configured. Auth screen. |
| `POST /api/auth/otp/verify` | Public | `OtpVerifyRequest` | `LoginResponse` with role and bearer token. Auth screen. |
| `POST /api/auth/logout` | Public/session cookie | None | 204 and cookie removal. Sidebar/customer sign-out. |
| `POST /api/session` | Customer or internal roles | `VoiceSessionRequest` | Ephemeral voice client secret and model. Voice service. |

## Customer, RFQ, and quote workflows

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `POST /api/rfqs/intake` | Authenticated customer/internal | `IntakeRequest` | `IntakeResponse` (`rfq_id`, status, message). Customer RFQ creation; `useCreateRFQ` invalidates RFQ lists. |
| `GET /api/rfqs` | Customer sees own records; internal roles see queue | None | `RFQ[]`. Customer dashboard, Sales, Procurement, Sourcing, Trace. `useRFQs`. |
| `GET /api/rfqs/{rfq_id}` | Authenticated; customer ownership checked | Path `rfq_id` | RFQ, items and optional quote detail; internal response also includes audit logs. `useRFQDetail` / `useQuotes(rfqId)`. There is no quote collection endpoint. |
| `POST /api/rfqs/{rfq_id}/process` | Admin/manager/sales/purchasing | Path `rfq_id` | Orchestration result. No UI retry/reprocess control is enabled yet. |
| `POST /api/quotes/{quote_id}/approve` | Admin/manager/sales | `ApproveRequest` | Approval/dispatch result. Customer Dashboard uses `useDispatchQuote`; Sales issues a quote. |
| `POST /api/quotes/{quote_id}/reject` | Admin/manager/sales | `RejectRequest` | Rejection result. Service method is available; no quote-collection view exists. |
| `POST /api/purchase-orders` | Authenticated; customer quote ownership checked | `PurchaseOrderRequest` with exactly three attachment IDs | `Pending_PO_Review`, PO and quote IDs. Customer Portal uses `useCreatePurchaseOrder`; this is not quote approval. |
| `POST /api/purchase-orders/{quote_id}/approve` | Admin/manager/purchasing | `PurchaseOrderApprovalRequest` | PO review state, quote ID, RFQ ID. No current view is bound to this endpoint. |
| `GET /api/attachments/{attachment_id}` | Authenticated and authorized | Path `attachment_id` | Binary attachment download. Sales/document preview. |
| `POST /api/attachments` | Authenticated and authorized | Multipart `file` | Accepted attachment ID/name/status. Customer RFQ and PO uploads. |

## Catalog and sourcing

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/catalog/search` | Customer/admin/manager/sales/purchasing | `query`, optional `condition` | Customer-safe catalog rows only. Portal search; fallback rows are tagged as sample. |
| `GET /api/inventory` | Admin/manager/purchasing | None | Internal inventory list; service exists, but current customer-facing panels do not expose internal cost/location fields. |
| `GET /api/suppliers` | Admin/manager/purchasing | None | Supplier directory. |
| `GET /api/suppliers/{supplier_id}` | Admin/manager/purchasing | Path `supplier_id` | Single supplier profile. |
| `GET /api/supplier-offers?part_number=...` | Admin/manager/purchasing/sales | Part number query | Supplier offers. Procurement and Sourcing views use `useSupplierOffers`. |
| `POST /api/internal/freight/quote` | Admin/manager/purchasing/sales | `FreightRequest` | Provider quote result. No live carrier data is synthesized by the UI. |

## Internal operations and compliance

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `POST /api/internal/rfqs/{rfq_id}/automation` | Admin/manager | `AutomationPauseRequest` | Automation pause/resume result. No current view is bound. |
| `POST /api/internal/rfqs/{rfq_id}/trace-decision` | Admin/manager/purchasing | `TraceDecisionRequest` | Decision and automation status. Trace Vault uses `useTraceDecision`, then invalidates RFQs/events. |
| `GET /api/internal/automation-events` | Admin/manager/sales/purchasing | Optional status/limit | Automation event list. TopBar audit feed and Trace Vault use `useAutomationEvents`. |
| `GET /api/internal/extraction-reviews` | Admin/manager/sales/purchasing | Optional status/limit | Operator review records. |
| `GET /api/internal/extraction-reviews/{review_id}` | Admin/manager/sales/purchasing | Path `review_id` | One operator review. |
| `POST /api/internal/extraction-reviews/{review_id}/decision` | Admin/manager/sales/purchasing | `ExtractionReviewDecisionRequest` | Review-decision result. |
| `POST /api/internal/commands` | Admin/manager/sales/purchasing | `InternalCommandRequest` | Audited command result. Procurement, Sourcing and Fulfillment hooks invalidate relevant active resources. |
| `GET /api/internal/llm/health` | Admin/manager | None | Provider/configuration booleans; no secret values. |
| `GET /api/internal/llm/telemetry` | Admin/manager | Optional task/limit | LLM telemetry records. |
| `GET /api/internal/mailboxes/health` | Internal/admin/manager/sales/purchasing | None | Status strings for `sales_mailbox` and `purchasing_mailbox`, plus authenticated user. TopBar shows live status. |
| `GET /api/internal/mailboxes/{mailbox}/inbox` | Admin/manager/sales/purchasing, mailbox-specific role checked | Path `mailbox` | Mailbox and message summaries. |
| `POST /api/internal/mailboxes/{mailbox}/send` | Admin/manager/sales/purchasing, mailbox-specific role checked | `MailboxMessageRequest` | Outbound send result. |

## Fulfillment and carrier tracking

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `POST /api/internal/shipments` | Admin/manager/purchasing | `ShipmentCreateRequest` | Shipment ID, tracking URL and notification status. No current creation form is bound. |
| `GET /api/internal/shipments` | Admin/manager/purchasing | None | Persisted shipment records. Fulfillment Hub `useShipments` / `useFulfillmentStages`. |
| `POST /api/internal/shipments/{shipment_id}/events` | Admin/manager/purchasing | `ShipmentEventRequest` | Updated event. |
| `POST /api/internal/shipments/{shipment_id}/tracking` | Admin/manager/purchasing | `CarrierTrackingRequest` | Carrier registration/provider result. |
| `POST /api/internal/shipments/{shipment_id}/tracking/refresh` | Admin/manager/purchasing | Path `shipment_id` | Refreshed carrier event/provider result. |
| `POST /api/internal/shipments/{shipment_id}/sms` | Admin/manager/purchasing/sales | `ShipmentSmsRequest` | SMS adapter result. |
| `GET /api/shipments/track/{public_token}` | Public opaque token | Path `public_token` | Customer-safe trace: status, parts, quantity, carrier/tracking, ETA, events. Portal `useShipmentTrace`. There is no `GET /api/shipments/{id}`. |
| `POST /api/webhooks/carriers/aftership` | Signed provider request | Carrier webhook body/signature | Applies normalized carrier event. Backend-only. |

## Voice

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/voice/dashboard` | Internal/admin/manager/sales/purchasing | None | Voice operations dashboard derived from RFQs. |
| `POST /api/voice/tools/{tool_name}` | Customer/internal roles | `VoiceToolRequest` | Inventory, order status or escalation tool response. |

## Employee profile and time tracking

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/internal/profile` | Internal/admin/manager/sales/purchasing | None | Employee profile and presence/clock state. TopBar profile button and EmployeeProfilePanel. |
| `PATCH /api/internal/profile` | Internal/admin/manager/sales/purchasing | Display name and job title | Updated employee profile. |
| `PUT /api/internal/profile/presence` | Internal/admin/manager/sales/purchasing | Online flag | Updated employee profile. |
| `POST /api/internal/profile/clock` | Internal/admin/manager/sales/purchasing | `clock_in` or `clock_out` | Updated employee profile; conflicts return 409. |
| `GET /api/internal/work-hours?month=YYYY-MM` | Internal/admin/manager/sales/purchasing | Month query | Current employee hours and daily totals. |
| `GET /api/internal/hr/work-hours?month=YYYY-MM` | Admin/manager | Month query | HR report with employee totals. |

## Employee profile and time tracking

| Method and path | Access | Request | Response / UI mapping |
| --- | --- | --- | --- |
| `GET /api/internal/profile` | Internal/admin/manager/sales/purchasing | None | `EmployeeProfile`; EmployeeProfilePanel. |
| `PATCH /api/internal/profile` | Internal/admin/manager/sales/purchasing | Display name and job title | Updated `EmployeeProfile`. |
| `PUT /api/internal/profile/presence` | Internal/admin/manager/sales/purchasing | Online flag | Updated `EmployeeProfile`. |
| `POST /api/internal/profile/clock` | Internal/admin/manager/sales/purchasing | `clock_in` / `clock_out` | Updated `EmployeeProfile`; conflicts return 409. |
| `GET /api/internal/work-hours?month=YYYY-MM` | Internal/admin/manager/sales/purchasing | Month query | Employee totals and daily seconds. |
| `GET /api/internal/hr/work-hours?month=YYYY-MM` | Admin/manager | Month query | HR report with employee totals. |

## View mapping and non-API content

| View | Live bindings | Remaining sample/demo content |
| --- | --- | --- |
| TopBar | `/ready`, mailbox health, employee profile/presence | AOG alert count is not API-backed. |
| Customer Dashboard | RFQ list/detail, quote detail and dispatch, internal shipment counts, RFQ creation | Price-option cards, spend/SLA/savings estimates, document previews and route maps remain badged sample content. |
| Aero Procurement / Sourcing | RFQ queue and supplier offers | Lead-time history, supplier performance, workload matrix, compliance-document panels remain sample where no read contract exists. |
| Fulfillment Hub | Shipment list and status-derived stage label; command targets actual shipment ID | Five-step workflow graphic, inspection/package/compliance checks and map route are demos, not shipment milestones. |
| Trace Vault | RFQs, compliance-related automation events and trace-decision mutation | OCR, document checklist, historical timeline and KPI metrics remain sample. |
| Customer Portal | Catalog search, RFQ/attachment upload, customer PO and token-based shipment trace | A catalog fallback is explicitly badged and cannot be represented as confirmed availability. |

## Contract gaps

- The backend does not expose `GET /api/v1/quotes`, `POST /api/v1/quotes/{id}/dispatch`, `GET /api/v1/fulfillment/stages`, or `GET /api/shipments/{id}`. Existing quote data comes from `GET /api/rfqs/{rfq_id}` and quote dispatch from `POST /api/quotes/{quote_id}/approve`.
- `useFulfillmentStages` derives a single human-readable stage from each persisted shipment status. It does not claim that the backend returned a multi-stage milestone history or inventory reservation.
- Compliance evidence and historical KPI endpoints do not exist. Those panels remain visibly sample until backend read contracts and persisted data are added.
