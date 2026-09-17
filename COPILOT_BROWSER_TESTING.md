# Copilot Browser Testing in This Repository

Yes, GitHub Copilot can help test in the browser here, but it does so through test tooling and extensions (not a built-in browser UI owned by Copilot itself).

## How It Works Here

This repository uses:
- Playwright for browser E2E (`frontend/tests/e2e`)
- Vitest for frontend unit/integration tests (`frontend/tests`)
- Python unittest for backend workflow logic (`tests`)

Copilot/agent workflows are effective when they:
1. generate tests,
2. execute them,
3. inspect failures,
4. patch code/tests,
5. re-run until green.

## 3 Practical Modes

### 1) Generate + Execute E2E Browser Tests (Playwright)

Use this for full user journeys across interfaces:
- Customer portal flows
- Sales workflows
- Procurement workflows
- Admin/audit controls

Repo commands:

```powershell
npm --prefix frontend run test:e2e:list
npm --prefix frontend run test:e2e
```

Target a single scenario:

```powershell
npm --prefix frontend run test:e2e -- --project=chromium --grep "customer uploads compliance PDF"
```

### 2) Agent/IDE Tooling Mode (VS Code + Playwright Toolchain)

With VS Code agent workflows and Playwright config in place, Copilot can:
- author and refactor Playwright specs,
- exercise role-specific routes,
- verify DOM states and auth transitions,
- iterate on failures using test output.

Relevant files:
- `frontend/playwright.config.ts`
- `frontend/tests/e2e/*.spec.ts`

### 3) Browser Context + Diagnostics Mode

Copilot can assist with selector/debug workflows by combining:
- frontend/browser behavior,
- test failures,
- logs and stack traces.

This is best used for:
- flaky selectors,
- auth state/routing issues,
- cross-role regressions.

## Direct Capability Mapping

| Capability | Supported Here | How |
|---|---|---|
| Open a visible browser window | Yes | Playwright headed runs/configurable launch modes |
| Click elements and fill forms | Yes | Playwright action APIs in `frontend/tests/e2e` |
| Inspect visual/DOM behavior | Yes | Playwright assertions + route mocks |
| Test role-based access/auth | Yes | Customer/internal session flows and OTP scenarios |
| Mock third-party providers | Yes | MSW handlers in `frontend/src/testing/msw` |

## Recommended Execution Loop

```powershell
# 1) Fast confidence on logic
npm --prefix frontend run test:unit
python -m unittest discover -s tests -p "test_*.py"

# 2) Browser scenario discovery
npm --prefix frontend run test:e2e:list

# 3) Run one targeted E2E flow
npm --prefix frontend run test:e2e -- --project=chromium --grep "full flow"

# 4) Run full browser suite
npm --prefix frontend run test:e2e
```

## Boundaries and Accuracy Notes

- Copilot does not replace test runners; it orchestrates generation/fixes around them.
- Browser automation depends on Playwright setup and installed browser binaries.
- Claims should be tied to actual scripts and files in this repo, not generic platform promises.
