import { expect, type BrowserContext, type Locator, type Page, type TestInfo } from '@playwright/test';
import type {
  AuditPersona,
  AuditReport,
  AuditedInteraction,
  ControlToken,
  CrawlOptions,
} from './audit-types';
import { createAuditReport, observePage, writeAuditReport } from './audit-report';

interface CrawlState {
  route: string;
  path: ControlToken[];
}

interface ButtonDescriptor extends ControlToken {
  disabled: boolean;
  mutating: boolean;
  blockedByDialog: boolean;
}

const INTERACTIVES = 'button:visible, [role="button"]:visible, [role="tab"]:visible';
const MUTATION_WORDS = /\b(submit|send|approve|reject|purchase|order|dispatch|delete|remove|reset|save|upload|certify|freeze|confirm|sign out|log out|clock in|clock out|create|execute|record)\b/i;

function normalizePath(href: string, baseURL: string): string | null {
  try {
    const url = new URL(href, baseURL);
    if (url.origin !== new URL(baseURL).origin || !['http:', 'https:'].includes(url.protocol)) return null;
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/assets/')) return null;
    if (/\.(?:pdf|png|jpe?g|gif|webp|svg|ico|zip|csv|xlsx?|docx?|pptx?|mp[34]|woff2?|ttf)$/i.test(url.pathname)) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

async function settle(page: Page): Promise<void> {
  await expect(page.locator('body')).toBeVisible();
  await page.waitForLoadState('domcontentloaded').catch(() => undefined);
  await page.waitForTimeout(180);
}

async function stateSignature(page: Page): Promise<string> {
  return page.evaluate(() => JSON.stringify({
    path: `${location.pathname}${location.search}${location.hash}`,
    title: document.title,
    text: (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 2_000),
    selected: Array.from(document.querySelectorAll<HTMLElement>(
      '[aria-selected="true"], [aria-pressed="true"], [aria-current="page"], [data-state="active"]',
    )).map(element => element.getAttribute('aria-label') || element.innerText.trim().slice(0, 80)),
    dialogs: document.querySelectorAll('[role="dialog"]:not([aria-hidden="true"])').length,
    rootClass: document.documentElement.className,
  }));
}

async function buttonDescriptors(page: Page): Promise<ButtonDescriptor[]> {
  return page.locator(INTERACTIVES).evaluateAll((elements, mutationPattern) => elements.map((element, index) => {
    const all = elements as HTMLElement[];
    const node = element as HTMLElement;
    const activeDialog = document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]:not([aria-hidden="true"])');
    const role = node.getAttribute('role') || (node.tagName.toLowerCase() === 'button' ? 'button' : 'button');
    const name = (node.getAttribute('aria-label') || node.innerText || node.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
    const disabled = node.matches(':disabled,[aria-disabled="true"]');
    const occurrence = all.slice(0, index).filter(candidate => {
      const candidateRole = candidate.getAttribute('role') || 'button';
      const candidateName = (candidate.getAttribute('aria-label') || candidate.innerText || candidate.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
      return candidateRole === role && candidateName === name;
    }).length;
    return {
      index,
      occurrence,
      name: name || `${node.tagName.toLowerCase()} without accessible name`,
      role,
      disabled,
      mutating: node.matches('button[type="submit"]') || new RegExp(mutationPattern, 'i').test(name),
      blockedByDialog: Boolean(activeDialog && !activeDialog.contains(node)),
    };
  }), MUTATION_WORDS.source);
}

async function locateButton(page: Page, token: ControlToken): Promise<Locator> {
  const role = token.role === 'tab' ? 'tab' : 'button';
  const named = page.getByRole(role, { name: token.name, exact: true });
  return named.nth(token.occurrence);
}

function stateKey(route: string, signature: string): string {
  return `${route}\n${signature}`;
}

async function navigate(page: Page, route: string, baseURL: string, report: AuditReport): Promise<number | undefined> {
  const target = new URL(route, baseURL).toString();
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const response = await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 15_000 });
      await settle(page);
      if (response && response.status() >= 400) {
        report.findings.push({
          severity: 'error',
          category: 'route-response',
          route,
          message: `Navigation returned HTTP ${response.status()}`,
        });
      }
      return response?.status();
    } catch (error) {
      if (attempt === 2) {
        report.findings.push({
          severity: 'error', category: 'navigation', route,
          message: error instanceof Error ? error.message : String(error),
        });
      }
    }
  }
}

async function inspectDom(page: Page, route: string, report: AuditReport): Promise<{
  links: string[];
  buttons: ButtonDescriptor[];
  inputCount: number;
  title: string;
  status?: number;
}> {
  const dom = await page.evaluate(() => {
    const visible = (element: Element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
    };
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>('a[href]'))
      .filter(visible)
      .map(anchor => anchor.href);
    const inputs = Array.from(document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
      'input,textarea,select',
    )).filter(visible).map(element => {
      const id = element.id;
      const explicitLabel = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent : '';
      const wrapperLabel = element.closest('label')?.textContent || '';
      const name = element.getAttribute('aria-label') || element.getAttribute('aria-labelledby') || explicitLabel || wrapperLabel || element.getAttribute('placeholder') || element.getAttribute('name') || '';
      return {
        tag: element.tagName.toLowerCase(),
        type: element instanceof HTMLInputElement ? element.type : element.tagName.toLowerCase(),
        name: String(name).replace(/\s+/g, ' ').trim(),
        required: element.required,
        disabled: element.matches(':disabled,[aria-disabled="true"]'),
      };
    });
    const duplicateIds = Array.from(document.querySelectorAll('[id]'))
      .map(element => element.id)
      .filter((id, index, ids) => ids.indexOf(id) !== index);
    return {
      title: document.title,
      bodyText: (document.body?.innerText || '').replace(/\s+/g, ' ').trim(),
      links,
      inputs,
      duplicateIds: [...new Set(duplicateIds)],
      hasMain: Boolean(document.querySelector('main,[role="main"]')),
      hasBody: Boolean(document.body),
    };
  });

  if (!dom.hasBody || !dom.bodyText) {
    report.findings.push({ severity: 'error', category: 'dom', route, message: 'Page body is missing or empty.' });
  }
  if (dom.duplicateIds.length) {
    report.findings.push({ severity: 'error', category: 'dom', route, message: `Duplicate DOM ids: ${dom.duplicateIds.join(', ')}` });
  }
  for (const input of dom.inputs) {
    if (!input.name) {
      report.findings.push({
        severity: 'error', category: 'accessibility', route,
        message: `Visible ${input.tag} (${input.type}) has no accessible name.`,
      });
    }
  }
  const links = dom.links.map(href => normalizePath(href, page.url())).filter((path): path is string => Boolean(path));
  const buttons = await buttonDescriptors(page);
  for (const button of buttons) {
    if (button.name.endsWith('without accessible name')) {
      report.findings.push({ severity: 'error', category: 'accessibility', route, message: button.name });
    }
  }
  return { links: [...new Set(links)], buttons, inputCount: dom.inputs.length, title: dom.title };
}

export async function crawlPerspective(
  context: BrowserContext,
  persona: AuditPersona,
  entryRoutes: string[],
  testInfo: TestInfo,
  options: CrawlOptions = {},
): Promise<AuditReport> {
  const page = await context.newPage();
  const baseURL = testInfo.project.use.baseURL as string;
  const baseOrigin = new URL(baseURL).origin;
  const report = createAuditReport(persona, entryRoutes);
  observePage(page, report, baseOrigin);

  const maxRoutes = options.maxRoutes ?? 20;
  const maxStates = options.maxStates ?? 28;
  const maxActions = options.maxActions ?? 100;
  const maxActionsPerState = options.maxActionsPerState ?? 18;
  const allowedRoutePrefixes = options.allowedRoutePrefixes;
  const pending: CrawlState[] = entryRoutes.map(route => ({ route, path: [] }));
  const discoveredRoutes = new Set<string>();
  const visitedStates = new Set<string>();
  let actionCount = 0;

  while (pending.length && report.counts.states < maxStates && report.routes.length < maxRoutes) {
    const state = pending.shift()!;
    const route = state.route;
    const routeStatus = await navigate(page, route, baseURL, report);
    for (const step of state.path) {
      const locator = await locateButton(page, step);
      try {
        await expect(locator).toBeVisible({ timeout: 2_000 });
        await locator.click({ timeout: 2_000 });
        await settle(page);
      } catch (error) {
        report.findings.push({
          severity: 'warning', category: 'state-replay', route,
          action: step.name,
          message: `Could not replay discovered UI state: ${error instanceof Error ? error.message : String(error)}`,
        });
        break;
      }
    }

    const beforeState = await stateSignature(page);
    const currentStateKey = stateKey(route, beforeState);
    if (visitedStates.has(currentStateKey)) continue;
    visitedStates.add(currentStateKey);
    report.counts.states += 1;

    const inspected = await inspectDom(page, route, report);
    const routeRecord = report.routes.find(item => item.path === route);
    if (routeRecord) {
      routeRecord.stateCount += 1;
      routeRecord.interactiveCount += inspected.buttons.length + inspected.links.length;
      routeRecord.inputCount += inspected.inputCount;
    } else {
      report.routes.push({
        path: route,
        status: routeStatus,
        title: inspected.title,
        stateCount: 1,
        interactiveCount: inspected.buttons.length + inspected.links.length,
        inputCount: inspected.inputCount,
      });
    }

    for (const discovered of inspected.links) {
      if (discoveredRoutes.has(discovered) || discoveredRoutes.size >= maxRoutes) continue;
      if (allowedRoutePrefixes && !allowedRoutePrefixes.some(prefix => {
        const pathname = new URL(discovered, baseURL).pathname;
        const normalizedPrefix = prefix !== '/' ? prefix.replace(/\/$/, '') : prefix;
        return pathname === normalizedPrefix || (normalizedPrefix !== '/' && pathname.startsWith(`${normalizedPrefix}/`));
      })) continue;
      discoveredRoutes.add(discovered);
      pending.push({ route: discovered, path: [] });
    }

    const actions = inspected.buttons.slice(0, maxActionsPerState);
    for (const button of actions) {
      if (actionCount >= maxActions) break;
      const control = `${button.role}: ${button.name}`;
      const record: AuditedInteraction = { route, control, outcome: 'skipped' };
      if (button.disabled) {
        record.note = 'Disabled control inspected but not activated.';
        report.interactions.push(record);
        continue;
      }
      if (button.blockedByDialog) {
        record.note = 'Background control was not activated while a modal dialog was open.';
        report.interactions.push(record);
        continue;
      }
      if (button.mutating) {
        record.note = 'Potentially destructive or submitting action was not activated by the crawler.';
        report.interactions.push(record);
        continue;
      }

      actionCount += 1;
      await navigate(page, route, baseURL, report);
      let replayFailed = false;
      for (const step of state.path) {
        const stepLocator = await locateButton(page, step);
        try {
          await stepLocator.click({ timeout: 2_000 });
          await settle(page);
        } catch {
          replayFailed = true;
          break;
        }
      }
      if (replayFailed) {
        record.outcome = 'failed';
        record.note = 'Could not restore the state before interaction.';
        report.interactions.push(record);
        continue;
      }
      const actionBefore = await stateSignature(page);
      const locator = await locateButton(page, button);
      try {
        if (await locator.count() <= button.occurrence) {
          record.note = 'Control is no longer present after restoring the UI state.';
          report.interactions.push(record);
          continue;
        }
        await expect(locator).toBeVisible({ timeout: 2_000 });
        if (!(await locator.isEnabled())) {
          record.note = 'Control became disabled after the UI state was restored.';
          report.interactions.push(record);
          continue;
        }
        await locator.click({ timeout: 2_000 });
        await settle(page);
        const actionAfter = await stateSignature(page);
        record.before = actionBefore.slice(0, 400);
        record.after = actionAfter.slice(0, 400);
        record.outcome = actionBefore === actionAfter ? 'unchanged' : 'changed';
        if (record.outcome === 'changed') {
          const changedRoute = normalizePath(page.url(), baseURL) || route;
          const nextPath = [...state.path, button];
          const nextKey = stateKey(changedRoute, actionAfter);
          if (!visitedStates.has(nextKey) && report.counts.states + pending.length < maxStates) {
            pending.push({ route: changedRoute, path: nextPath });
          }
        } else {
          report.findings.push({
            severity: 'warning', category: 'interaction-transition', route,
            action: button.name,
            message: 'Safe control click produced no observable URL, content, selected-state, or dialog transition.',
          });
        }
      } catch (error) {
        record.outcome = 'failed';
        record.note = error instanceof Error ? error.message : String(error);
        report.findings.push({
          severity: 'error', category: 'interaction', route,
          action: button.name, message: record.note,
        });
      }
      report.interactions.push(record);
    }
  }

  if (pending.length) {
    report.findings.push({
      severity: 'warning', category: 'crawl-limit',
      message: `Crawl stopped at configured bounds (${maxRoutes} routes, ${maxStates} UI states, ${maxActions} actions).`,
    });
  }

  await writeAuditReport(report, page, testInfo);
  await page.close();
  return report;
}