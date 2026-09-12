# Frontend UI/UX + Access-Control Agent Rules

## Scope boundaries
- Allowed edit scope: `frontend/src/components/**`, `frontend/src/App.tsx`, `frontend/src/services/**`, `frontend/src/auth/**`, `api/main.py`, `api/auth.py`, `frontend/tests/**`, `frontend/playwright.config.ts`, `frontend/package.json`, and `README.md`.
- Avoid edits outside these paths unless required to keep role-policy wiring correct.

## Design system conventions
- Use existing Tailwind utility patterns and current component layout conventions.
- Avoid inline styles and avoid introducing a second UI framework.
- Keep view spacing, border, typography, and color patterns consistent with existing dashboard components.

## Role hierarchy and route/view ownership
- `ROLE_CUSTOMER`: customer portal only (`/customer-portal`).
- `ROLE_SALES`: internal dashboard + sales actions (`customer`, `fulfillment`, `sales` views).
- `ROLE_PURCHASING`: sourcing/procurement/compliance surfaces (`customer`, `sourcing`, `aero-procurement`, `trace-vault`, `fulfillment`).
- `ROLE_MANAGER`: all internal views and internal action permissions.
- `ROLE_ADMIN`: all internal views and internal action permissions.

## Mandatory access-enforcement rules
1. Every restricted action must have a UI-level permission check (hidden or disabled state).
2. Every restricted API action must continue to rely on backend guard enforcement (`require_roles(...)`) with no frontend-only trust.
3. Permission defaults must be deny-by-default for unknown roles.

## Approved access patterns
- Centralize frontend role/permission mapping in one module and reuse it.
- Gate restricted controls with shared wrappers/helpers instead of ad hoc checks.
- Ensure role-to-view navigation menus are filtered by the same shared policy map used by action buttons.

## Verification commands
Run from `frontend/`:

```powershell
npm run lint
npm run build
npm run test:access
npm run test:ui-regression
```

Run backend tests from repo root:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## PR evidence requirements
- Include role matrix proof (which roles can/cannot access each view/action).
- Include Playwright screenshots/snapshot results for changed views.
- Include accessibility scan output for changed views and breakpoints.
