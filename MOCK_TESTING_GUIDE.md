# Winged Tycoons Mock Testing Setup & Execution Guide

This guide provides complete instructions for running mock testing sessions with mock customers and internal team members on the Winged Tycoons RFQ-to-Quote platform.

---

## 1. Prerequisites & Environment Setup

### Environment Variables
For local mock testing, set the following environment variables (or configure in `.env`):
```env
WT_AUTH_ENV=development
WT_AUTH_SECRET=development-only-change-this-secret
FRONTEND_ORIGIN=http://localhost:3000
```
*Setting `WT_AUTH_ENV=development` enables on-screen One-Time Passwords (OTPs) so testers can sign in immediately without an external email provider.*

### Initialize & Seed Mock Accounts
Run the automated seed script from the repository root:
```powershell
python scripts/seed_mock_test_env.py --reset
```

This provisions the following mock personas into `data/winged_tycoons_auth.db`:

#### **Internal Team Members** (`@wingedtycoons.com`)
| Role ID | Full Name | Email | Role | Test Focus |
|---|---|---|---|---|
| `INT-001` | Camila Admin | `camila@wingedtycoons.com` | `ROLE_ADMIN` | System oversight & full access |
| `INT-002` | Alex Sales | `alex.sales@wingedtycoons.com` | `ROLE_INTERNAL` | RFQ triage & pricing overrides |
| `INT-003` | Sarah Procurement | `sarah.procurement@wingedtycoons.com` | `ROLE_INTERNAL` | Supplier sourcing & PO creation |
| `INT-004` | Dave Compliance | `dave.compliance@wingedtycoons.com` | `ROLE_INTERNAL` | Quality checks & trace audits |

#### **Mock Customers**
| Customer ID | Company / Contact | Email | Role | Portal View |
|---|---|---|---|---|
| `CUST-DELTA` | Delta MRO Services | `procurement@delta-mro.com` | `ROLE_CUSTOMER` | Customer Portal (`/customer-portal`) |
| `CUST-SKYWEST` | SkyWest Airlines | `buyer@skywest.com` | `ROLE_CUSTOMER` | Customer Portal (`/customer-portal`) |
| `CUST-AEROJET` | AeroJet Maintenance | `spares@aerojet.com` | `ROLE_CUSTOMER` | Customer Portal (`/customer-portal`) |

---

## 2. Launching the Platform

### Terminal 1: Backend API
```powershell
# Activate virtual environment if configured
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```
*API interactive docs are available at `http://127.0.0.1:8000/docs`.*

### Terminal 2: Frontend Dashboard
```powershell
cd frontend
npm run dev
```
*Frontend is accessible at `http://localhost:3000`.*

---

## 3. Synthetic Test Scenario Matrix

Use these standardized test cases during mock testing to validate all multi-agent pipeline branches:

| Scenario ID | Name | Input RFQ Text | Target Component / Part | Expected Pipeline Result |
|---|---|---|---|---|
| **ST-01** | Clean In-Stock Match | *"Please quote part 060-1234-00, quantity 2, for Delta MRO Services."* | `060-1234-00` (Radar Receiver) | **Direct Quote**: Match in inventory (`INV-001`, `INV-002`), full trace verified, generates draft quote. |
| **ST-02** | Out-of-Stock Supplier Sourcing | *"Requesting quote for part 060-1234-00, quantity 10."* | `060-1234-00` (Qty 10) | **Supplier Sourcing**: Inventory holds 2, triggers Supplier Sourcing Agent to query Apex Aero (`SUP-001`). |
| **ST-03** | Compliance Trace Hold | *"Please quote part 456-789-OH, quantity 1."* | `456-789-OH` (Actuator) | **Compliance Warning**: Item `INV-004` lacks full trace, pipeline halts at `Compliance_Warning` for human approval. |
| **ST-04** | Low Margin Escalation | High cost supplier item with tight pricing | Custom part / cost | **Manager Review**: Margin < 10% requires manager approval before quote dispatch. |

---

## 4. Role-Based Runbooks for Testers

### A. Customer Persona Runbook (Customer Portal)
1. Navigate to `http://localhost:3000/customer-portal`.
2. Sign in with a mock customer email (e.g. `procurement@delta-mro.com`).
3. Copy the development OTP displayed in the amber banner and click **Verify code**.
4. **Search Availability**: Use the search bar to query part numbers like `060-1234-00` or `456-789-OH` (note that cost, serial numbers, and locations are masked for customer privacy).
5. **Submit RFQ**: Click **Submit RFQ**, enter raw request text (e.g. Scenario ST-01), and submit.
6. **Track Status & Quotes**: View submitted RFQs, track real-time pipeline status, and inspect generated quotes.

### B. Internal Team Member Runbook (Command Center)
1. Navigate to `http://localhost:3000/`.
2. Sign in with a staff email (e.g. `alex.sales@wingedtycoons.com`).
3. Enter the development OTP to gain access to internal views.
4. **Sales Command View**:
   * View incoming RFQs in the workflow queue.
   * Click **Process RFQ** to trigger the automated multi-agent pipeline.
   * Review parsed part details, inventory allocation, and margin calculations.
   * Override unit prices if required and click **Approve & Send Quote**.
5. **Supplier Sourcing View**:
   * Inspect supplier quotes for items requiring external procurement.
   * Review supplier approval status (`Approved` vs `Pending`) and ITAR compliance flags.
6. **Trace Vault / Audit Log**:
   * Click **Audit Log** on any RFQ card to inspect real-time agent execution trails (`RFQIntakeAgent`, `PartsIntelligenceAgent`, `ComplianceAgent`, `PricingAgent`).

---

## 5. Post-Test Reset & Feedback Protocol

### Resetting Environment Between Test Runs
To reset the test database and start a fresh session:
```powershell
python scripts/seed_mock_test_env.py --reset
```

### Key Verification Checklist
- [ ] OTP auth enforces domain rules (`@wingedtycoons.com` for internal staff, non-internal domain for customers).
- [ ] Unauthenticated customer search (`/api/catalog/search`) masks sensitive internal fields.
- [ ] Multi-agent pipeline correctly routes clean matches to draft quotes.
- [ ] Compliance exceptions halt execution at `Compliance_Warning`.
- [ ] Human approval gates permit price overrides and record audit events.
