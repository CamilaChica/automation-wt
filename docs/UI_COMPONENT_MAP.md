# UI Pending Work Checklist

Updated 2026-09-22 after the accessibility and operational-transparency pass.

## Completed

- Customer form labels, names, autocomplete, instructional placeholders, and focus rings.
- Keyboard-accessible workflow, dashboard, procurement, and sourcing controls.
- Customer attachment upload and RFQ attachment linking.
- Sales attachment downloads use IDs from RFQ detail and show unavailable state when absent.
- Audit drawer warning, dialog semantics, focus trap, Escape close, and UTC/ISO timestamps.
- Global search routing, reduced-motion support, intrinsic logo dimensions, typed shipment/quote contracts.
- Playwright parameter-property cleanup and focused UI audit coverage.
- Typed internal command API for procurement and fulfillment actions.
- `SIMULATED DATA` disclosure banners on static telemetry, procurement, sourcing, fulfillment, sales, and trace surfaces.

## Pending UI Work

### High priority

- Replace hardcoded dashboard metrics, charts, OCR/CV results, trace checklists, customer cards, and telemetry with authenticated API data.
- Complete backend command semantics beyond audit recording for quote assembly, PO issuance, packaging, stamp generation, and supplier document audit.
- Add durable document-status and attachment-to-RFQ records so trace/document actions survive process restarts.
- Restrict mock fallbacks to development/test builds and show an environment-level mock banner when enabled.

### Medium priority

- Add typed response interfaces for remaining supplier offers, view-local payloads, and service methods that still use broad types.
- Make CustomerDashboard filters, document previews, certificate downloads, and shipment/radar links API-backed.
- Replace static `REAL TIME DATA` labels with API-backed status or `SIMULATED DATA` labels wherever data remains illustrative.
- Add API-backed supplier matching and quote assembly to the sourcing matrix.
- Add durable fulfillment workflow endpoints for QA, packaging, airworthiness, and shipment events.

### Production gate

- Migrate RFQ, quote, communication, PO, and audit operational state from the SQLite-compatible store to PostgreSQL.
- Run the full frontend build, unit suite, Playwright discovery, and all E2E projects after backend command contracts are deployed.
- Verify live Graph mailbox ingestion, PostgreSQL persistence, attachment storage, outbound email, supplier chasing, and PO notification in Render.
