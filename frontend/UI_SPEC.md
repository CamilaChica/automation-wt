# Winged Tycoons Front-End Specification (React / Vite / Tailwind)

This folder contains the designs and layout definitions for the single-page application dashboard.

## 1. Structure & Layout

```
/frontend
  ├── components/
  │    ├── RFQTable.tsx         <- Lists active and historic RFQs with statuses
  │    ├── RFQDetails.tsx       <- Deep dive into the current RFQ execution details
  │    ├── AuditLogTimeline.tsx <- Displays agent-specific actions in real time
  │    ├── QuoteProposal.tsx    <- Final quote review card with operator adjustments
  │    └── MockDataEditor.tsx   <- Sidebar editor to tweak inventory/suppliers
  ├── App.tsx                   <- Layout layout container and router
  └── index.css                 <- Tailwind styling directives
```

## 2. Page Hierarchy & Stepper

The UI tracks the RFQ status using a visual stepper matching the Orchestrator status:
`Received ➔ Parsing ➔ Inventory Lookups ➔ Sourcing ➔ Compliance Check ➔ Pricing ➔ Approval ➔ Quote Sent`

### Panel Breakdown (RFQ Workspace)
- **Left Panel (Client Request)**: 
  Shows the raw customer email input side-by-side with parsed item rows.
- **Center Panel (Agent Logs)**: 
  A scrollable timeline rendering agent steps. Cards are colored by status:
  - Green (Success): e.g. `PartsIntelligenceAgent resolved PN 060-1234-00`.
  - Yellow (Escalation / Review): e.g. `ComplianceAgent flagged missing FAA Form 8130-3 on inventory SN-ACT-982`.
  - Red (Failure): e.g. `IntakeAgent could not extract items`.
- **Right Panel (Human-in-the-Loop Actions)**:
  - If status is `Compliance_Warning`: Displays a form requesting operator confirmation to "Waive airworthiness trace check" or "Select alternate supplier".
  - If status is `Pending_Approval` / `Pending_Approval_Low_Margin`: Displays a draft quote proposal with inputs to override unit sell prices, select margins, or add operator review notes, with "Approve & Send" / "Reject" triggers.

## 3. Endpoints & Integrations
- Fetch RFQs: `GET /api/rfqs`
- Submit RFQ: `POST /api/rfqs/intake` -> `{"raw_text": "..."}`
- Retrieve Audit Logs: `GET /api/rfqs/{rfq_id}`
- Submit Manual Override/Approval: `POST /api/quotes/{quote_id}/approve` -> `{"operator_name": "...", "comments": "...", "items_override": [...]}`
- Submit Rejection: `POST /api/quotes/{quote_id}/reject` -> `{"operator_name": "...", "comments": "..."}`
