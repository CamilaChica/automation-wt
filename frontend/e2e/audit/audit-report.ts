import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { Page, TestInfo } from '@playwright/test';
import type { AuditFinding, AuditPersona, AuditReport } from './audit-types';

export function createAuditReport(persona: AuditPersona, entryRoutes: string[]): AuditReport {
  return {
    schemaVersion: 1,
    runId: `${persona}-${new Date().toISOString().replace(/[:.]/g, '-')}`,
    persona,
    startedAt: new Date().toISOString(),
    entryRoutes,
    routes: [],
    interactions: [],
    findings: [],
    counts: { routes: 0, states: 0, interactions: 0, skippedMutations: 0, errors: 0, warnings: 0 },
  };
}

export function observePage(page: Page, report: AuditReport, baseOrigin: string): void {
  const isFirstParty = (url: string) => {
    try {
      return new URL(url).origin === baseOrigin;
    } catch {
      return false;
    }
  };

  page.on('console', message => {
    if (message.type() === 'error') {
      report.findings.push({
        severity: 'error',
        category: 'console',
        message: message.text(),
        route: new URL(page.url()).pathname,
      });
    }
  });
  page.on('pageerror', error => {
    report.findings.push({
      severity: 'error', category: 'uncaught-exception', message: error.message,
      route: new URL(page.url()).pathname,
    });
  });
  page.on('requestfailed', request => {
    if (isFirstParty(request.url())) {
      const errorText = request.failure()?.errorText || 'request failed';
      report.findings.push({
        severity: errorText === 'net::ERR_ABORTED' ? 'warning' : 'error', category: 'network',
        message: `${request.method()} ${new URL(request.url()).pathname}: ${errorText}`,
        route: new URL(page.url()).pathname,
      });
    }
  });
  page.on('response', response => {
    const url = response.url();
    if (!isFirstParty(url) || response.status() < 400) return;
    report.findings.push({
      severity: 'error',
      category: 'http-response',
      message: `${response.status()} ${response.request().method()} ${new URL(url).pathname}`,
      route: new URL(page.url()).pathname,
    });
  });
}

export async function writeAuditReport(
  report: AuditReport,
  page: Page,
  testInfo: TestInfo,
): Promise<void> {
  report.finishedAt = new Date().toISOString();
  report.counts.routes = report.routes.length;
  report.counts.interactions = report.interactions.length;
  report.counts.skippedMutations = report.interactions.filter(item => item.outcome === 'skipped').length;
  report.counts.errors = report.findings.filter(item => item.severity === 'error').length;
  report.counts.warnings = report.findings.filter(item => item.severity === 'warning').length;

  const reportPath = testInfo.outputPath(`${report.persona}-audit-report.json`);
  await mkdir(dirname(reportPath), { recursive: true });
  await writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8');
  await testInfo.attach(`${report.persona}-audit-report`, {
    path: reportPath,
    contentType: 'application/json',
  });

  if (report.counts.errors > 0) {
    const screenshotPath = testInfo.outputPath(`${report.persona}-failure.png`);
    try {
      await page.screenshot({ path: screenshotPath, fullPage: true, animations: 'disabled' });
      await testInfo.attach(`${report.persona}-failure-screenshot`, {
        path: screenshotPath,
        contentType: 'image/png',
      });
    } catch (error) {
      const finding: AuditFinding = {
        severity: 'warning',
        category: 'artifact',
        message: `Unable to capture screenshot: ${error instanceof Error ? error.message : String(error)}`,
      };
      report.findings.push(finding);
    }
  }
}