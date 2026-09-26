# UI Crawler Findings and Remediation Status

Target: `https://winged-tycoons-frontend.onrender.com/internal`

## Local Remediation Completed

- Workflow stepper uses an internally scrollable, non-shrinking track.
- Customer dashboard tabs and account badges no longer compress their labels.
- Top-bar groups preserve essential controls and titles without clipping.
- The former `font-mono` utility now uses Montserrat as requested; UI labels and numeric values share the same family.
- Proposal review header now gives RFQ identity its own responsive row and keeps the P/N token unbroken. Aircraft details receive full width on narrow screens.
- Proposal price rows use a flexible description column and a single-line, right-aligned value column; the `Included (FREE)` value no longer wraps.
- Short count badges use centered inline-flex geometry and stay on one line.
- Fulfillment stages use a responsive five-column grid, keep each numeral inside its circle, remove duplicate numeral prefixes, and no longer render decorative connector bars that displaced stage items.
- The local-only airworthiness toggle was removed and replaced by a clearly labeled `SAMPLE` status; airport route copy includes IATA codes (`MIA`, `DFW`).
- Trace history milestones use equal-width grid columns with centered circles, captions, and sublabels.
- The RFQ queue's requestor heading is split into a deliberate two-line `Requested by` label.
- Customer portal language control is a globe-only selector beside Contact Us at every viewport; its accessible name and tooltip include the current language. The logo wordmark stays hidden at compact widths so it cannot wrap into the controls and uses the medium aero-navy token with light-theme contrast preserved.
- The customer UI supports English, French, Spanish, German, Portuguese, Italian, Japanese, Chinese, Korean, Dutch, Arabic, and Hindi. User cookie preference takes precedence over browser language/region; first visit uses the browser's language and region without requesting precise location. Arabic switches direction to RTL.
- Portal text, form labels/options, validation/loading/failure messages, shipment display, footer, Contact Us menu, and voice-support dialog use the selected language. The voice call's conversation language remains an independent setting.
- The RFQ compliance checkbox is 16x16px; the global 44px target minimum remains applied to the containing label/click area.
- Base interactive hit targets are at least 44px at all viewport sizes.
- Shipment map now uses Leaflet with MIA, DFW, and FRA coordinates, OpenStreetMap attribution, non-overlapping hover labels, and a text fallback when tiles fail.
- Hard-coded shipment routes and statuses are labeled as sample/demo data, not live telemetry.
- RFQ fallback notices are shown only when the configured mock RFQ fallback is actually returned. RFQ views expose load failures instead of silently presenting empty lists.
- Failed RFQs cannot use quote, sourcing, or trace mutation controls. The UI directs operators to intake operations; a retry/reprocess API is not currently exposed.
- Quote issuance, trace decisions, procurement commands, fulfillment commands, and supplier add-to-quote require confirmation and have pending/duplicate-submit guards.
- Emoji glyphs were removed from the touched production UI messages and labels.
- The local viewport test opens the mobile navigation drawer before selecting views and now includes a failed-intake guard test and a cancelled-mutation test.

## Local Verification

- `npm --prefix frontend run test:unit`: 11 passed.
- `npm --prefix frontend run build`: passed.
- `npm --prefix frontend run lint`: passed.
- `npm --prefix frontend audit`: 0 vulnerabilities after updating Playwright, Vite, and Vitest and adding axe tooling.
- `npm --prefix frontend run test:e2e -- --project=ui-gadgets e2e/mobile_responsiveness_diagnosis.spec.ts`: 49 passed across the viewport matrix, axe, keyboard, failed-RFQ, map-render, cancellation, confirmed-pending, attached-DOM, and language-selector regressions.
- Language regressions verify all 12 options, translated content, preference cookie persistence, saved preference precedence over locale, `de-DE` first-visit detection, Arabic RTL, voice-modal language propagation, and mobile/desktop selector accessibility.
- Viewport matrix: `375x667`, `393x852`, `412x915`, `768x1024`, `1440x900`, and `2560x1440`, across six internal views. Checks include horizontal overflow, visible text clipping, interactive dimensions, and browser runtime errors.
- axe WCAG 2.0/2.1 A/AA scan: no violations across all six internal views.
- Keyboard test: audit drawer traps focus and restores focus to its opener after Escape.
- Mocked failed-intake case verified quote, procurement, and trace actions are disabled.
- Mocked cancellation cases verified quote, trace, sourcing, procurement, and fulfillment confirmations submit no mutation request.
- Mocked confirmed procurement case verified one request, pending/disabled/`aria-busy` state, and success feedback after the response.
- Mobile DOM regression verified Montserrat, intact P/N text, readable aircraft detail, right-aligned pricing, duplicate-free stages, airport codes, no inert verification toggle, and centered trace milestone text.
- `python -m unittest discover -s tests -p "test_*.py"`: 208 passed, 18 skipped, 1 expected failure.
- `git diff --check`: passed after updating this report.

## Outstanding Release Gates

- [ ] Deploy the current frontend and record the deployed build identifier. **Blocked pending backend persistence/readiness reconciliation. The remediation commit will use Render's `[skip render]` phrase to avoid automatically deploying the backend.**
- [x] Read-only production navigation pass visited Dashboard, Sales, Sourcing, Procurement, Trace Vault, and Fulfillment in the available browser session; observed zero page errors, console errors, HTTP error responses, and non-GET requests.
- [ ] Re-run authenticated production payload assertions after a safe deployment; the current live RFQ queue showed no RFQ records, so this pass did not verify production RFQ payload semantics.
- [ ] Verify live RFQ status/field preservation end-to-end in a controlled environment. Local fixtures cover extracted, pending, and failed states, but do not prove deployed persistence/orchestration mapping.
- [ ] Test mutations in staging using disposable records: quote approval/dispatch, PO, certify/reject, freeze, email, supplier add-to-quote, and fulfillment commands. Verify rollback/cleanup, duplicate prevention, and success/failure feedback. No staging or production writes were performed in this remediation.
- [x] Run axe WCAG 2.0/2.1 A/AA checks on all six local internal views and test audit-drawer keyboard focus trapping/restoration.
- [ ] Add or verify slow-network and API-failure browser scenarios for all dynamic views.
- [x] Resolve the reported development dependency advisories with compatible updates; `npm audit` now reports zero vulnerabilities.
- [ ] Implement an explicit backend retry/reprocess endpoint and UI only if product policy authorizes that operation; until then, failed RFQs show escalation guidance and actions stay disabled.

## Evidence Notes

- Previous attached production DOM snapshots identified stepper compression, customer tab shrinkage, wrapping account pills, top-bar collisions, telemetry label collisions, abstract map geometry, emoji rendering, and mis-sized count badges. These are addressed locally and covered by the current mocked viewport matrix where measurable.
- The read-only production navigation pass succeeded in an already-open browser session and made no non-GET requests. It is not equivalent to full payload verification and must not be represented as proving RFQ status/persistence correctness.
- The production dashboard displayed `0` active RFQs during this pass. No real RFQ payload or workflow transition was available to verify.
- Live `GET /ready` returned HTTP 200 and claimed `storage_engine=postgresql`, `operational_store=postgresql`, and mirroring enabled, while also reporting `operational_store_path=/opt/render/project/src/data/operations.db`. This inconsistent readiness response matches the blocker documented in `docs/PRODUCTION_AUTOMATION_PLAN.md`; do not use it as proof of PostgreSQL-primary runtime or deploy the backend until reconciled.
- No staging or production mutation was performed. The mutation tests use intercepted local API routes only.
- The map uses OpenStreetMap tiles and attribution. When external tiles fail, the component displays a text route summary.

## Release Status

**Not signed off.** Local frontend, backend, axe, keyboard, and mocked-mutation checks pass; npm audit is clear. Production navigation was crawled read-only. Deployment and live payload verification are blocked by the inconsistent Render readiness payload; real staging mutation/rollback coverage and slow-network/API-failure scenarios remain open.
