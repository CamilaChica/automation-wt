# UI Crawler Findings and Remediation Status

Target: `https://winged-tycoons-frontend.onrender.com/internal`

## Local Remediation Completed

- Workflow stepper uses an internally scrollable, non-shrinking track.
- Customer dashboard tabs and account badges no longer compress their labels.
- Top-bar groups preserve essential controls and titles without clipping.
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
- `npm --prefix frontend run test:e2e -- --project=ui-gadgets e2e/mobile_responsiveness_diagnosis.spec.ts`: 38 passed before adding the focused map-render check; that additional map check passed separately.
- Viewport matrix: `375x667`, `393x852`, `412x915`, `768x1024`, `1440x900`, and `2560x1440`, across six internal views. Checks include horizontal overflow, visible text clipping, interactive dimensions, and browser runtime errors.
- Mocked failed-intake case verified quote, procurement, and trace actions are disabled.
- Mocked cancellation case verified cancelling quote and trace confirmations submits no mutation request.
- `python -m unittest discover -s tests -p "test_*.py"`: 208 passed, 18 skipped, 1 expected failure.
- `npm --prefix frontend audit --omit=dev`: 0 production dependency vulnerabilities. The full npm install reported 6 development dependency advisories; review/fix them separately without force-upgrading packages.
- `git diff --check`: passed after updating this report.

## Outstanding Release Gates

- [ ] Deploy the current frontend and record the deployed build identifier.
- [ ] Re-run the authenticated production crawler and payload assertions after deployment; this local mocked audit does not validate the live API or production DOM.
- [ ] Verify live RFQ status/field preservation end-to-end in a controlled environment. Local fixtures cover extracted, pending, and failed states, but do not prove deployed persistence/orchestration mapping.
- [ ] Test mutations in staging using disposable records: quote approval/dispatch, PO, certify/reject, freeze, email, supplier add-to-quote, and fulfillment commands. Verify rollback/cleanup, duplicate prevention, and success/failure feedback. No staging or production writes were performed in this remediation.
- [ ] Complete keyboard navigation/focus restoration review and run axe/Playwright accessibility checks. The viewport audit checks names, hit targets, and runtime errors, not full WCAG conformance.
- [ ] Add or verify slow-network and API-failure browser scenarios for all dynamic views.
- [ ] Review six development dependency advisories and decide on minimal compatible updates.
- [ ] Implement an explicit backend retry/reprocess endpoint and UI only if product policy authorizes that operation; until then, failed RFQs show escalation guidance and actions stay disabled.

## Evidence Notes

- Previous attached production DOM snapshots identified stepper compression, customer tab shrinkage, wrapping account pills, top-bar collisions, telemetry label collisions, abstract map geometry, emoji rendering, and mis-sized count badges. These are addressed locally and covered by the current mocked viewport matrix where measurable.
- The current local browser tests do not authenticate to or mutate production. Existing earlier crawler notes reported no authenticated console/page errors or `401/403/404/5xx` responses in the earlier deployed build; that evidence predates these changes and must not be used as post-remediation sign-off.
- The map uses OpenStreetMap tiles and attribution. When external tiles fail, the component displays a text route summary.

## Release Status

**Not signed off.** Local frontend, backend, and mocked-browser checks pass. Deployment, authenticated live verification, staging mutation/rollback coverage, complete accessibility review, and development advisory triage remain open.
