# UI Crawler Findings

Target: `https://winged-tycoons-frontend.onrender.com/internal`

This file records observed behavior, not a task checklist. All remaining implementation, staging, and release actions are ordered in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

- Production `/ready` last returned HTTP 503. Do not run crawler mutations or deploy against production while readiness is blocked.
- The last local Playwright run against isolated storage reported 63 passed, 13 failed, and 2 skipped. Failures span admin/command-center/customer/procurement/sales and internal workflow scenarios; local mocked tests do not prove deployed delivery.
- The last read-only dashboard observation showed zero active RFQs, so authenticated live RFQ/detail/event/attachment payload behavior remains unverified.
- There is no intake retry/reprocess endpoint. Failed RFQs remain blocked from mutation until a safe API and audit policy are approved.
- Several displayed values remain sample/demo, including document/compliance panels, historical SLA, spend/savings estimates, maps, and workflow milestones without persisted read contracts.
- Carrier-map sourcing and unread-notification feed behavior are not confirmed production capabilities.
