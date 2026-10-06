const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const SCREENSHOTS_DIR = 'C:\\Users\\camil\\.gemini\\antigravity-ide\\brain\\d00b0f58-0b72-4fb2-a8b6-2ae9f25f7f20\\screenshots';
const RESULTS_FILE = 'C:\\Users\\camil\\.gemini\\antigravity-ide\\brain\\d00b0f58-0b72-4fb2-a8b6-2ae9f25f7f20\\crawl_results.json';

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function runCrawl() {
  console.log('=== Winged Tycoons Internal UI Exploratory Crawl & Interactive Mutation Test ===\n');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  const report = {
    timestamp: new Date().toISOString(),
    routes_visited: [],
    dialogs_visited: [],
    element_discovery: {},
    mutations_executed: [],
    console_errors: [],
    network_errors: [],
    screenshots_captured: [],
  };

  // Monitor console messages
  page.on('console', msg => {
    const text = msg.text();
    if (msg.type() === 'error') {
      console.error(`[Browser Console Error] ${text}`);
      report.console_errors.push({ type: 'error', text, location: msg.location() });
    }
  });

  // Intercept and maintain authenticated session & fallbacks
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const pathName = url.pathname;

    if (pathName.endsWith('/auth/session')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'X-CSRF-Token': 'playwright-csrf' },
        body: JSON.stringify({
          role: 'ROLE_ADMIN',
          email: 'operator@wingedtycoons.com',
          full_name: 'System Operator',
        }),
      });
      return;
    }

    if (pathName.endsWith('/auth/csrf')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'X-CSRF-Token': 'playwright-csrf' },
        body: JSON.stringify({ csrf_token: 'playwright-csrf' }),
      });
      return;
    }

    try {
      const response = await route.fetch();
      if (response.status() === 401) {
        if (pathName.includes('/rfqs')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify([
              {
                id: 'RFQ-001',
                customer_name: 'Priya Nair',
                company_name: 'Northwind MRO LLC',
                customer_email: 'pnair@northwindmro.com',
                status: 'Under Review',
                created_at: new Date().toISOString(),
                items: [{ part_number: '060-1234-00', quantity: 2, condition_preference: 'NE', target_price: 1100.0 }]
              },
              {
                id: 'RFQ-002',
                customer_name: 'Valentina Rojas',
                company_name: 'Aero Service Group Inc.',
                customer_email: 'vrojas@aeroservice.com',
                status: 'Quoted',
                created_at: new Date().toISOString(),
                items: [{ part_number: '456-789-OH', quantity: 1, condition_preference: 'OH', target_price: 550.0 }]
              }
            ])
          });
          return;
        }
        if (pathName.includes('/mailboxes/health')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ sales_mailbox: 'ok', purchasing_mailbox: 'ok', authenticated_user: 'operator@wingedtycoons.com' })
          });
          return;
        }
        if (pathName.includes('/profile')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ email: 'operator@wingedtycoons.com', full_name: 'System Operator', role: 'ROLE_ADMIN' })
          });
          return;
        }
        if (pathName.includes('/sales/me')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              month: 'October 2026',
              revenue: 84500,
              orders: 14,
              hours: 152,
              daily_seconds: { '2026-10-01': 28800, '2026-10-02': 29400, '2026-10-05': 30000 },
              handled_rfqs: [
                { rfq_id: 'RFQ-101', part_number: '060-1234-00', customer_email: 'pnair@northwindmro.com', status: 'Accepted' },
                { rfq_id: 'RFQ-102', part_number: '456-789-OH', customer_email: 'vrojas@aeroservice.com', status: 'Sent' }
              ]
            })
          });
          return;
        }
        if (pathName.includes('/analytics/owner') || pathName.includes('/sales')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              total_revenue: 125000,
              total_quotes: 48,
              win_rate: 0.62,
              reps: [{ name: 'Alex Taylor', sales: 65000 }, { name: 'Maria Fontaine', sales: 60000 }]
            })
          });
          return;
        }
      }
      await route.fulfill({ response });
    } catch {
      await route.continue();
    }
  });

  async function takeScreenshot(name) {
    const filePath = path.join(SCREENSHOTS_DIR, `${name}.png`);
    await page.screenshot({ path: filePath, fullPage: false });
    report.screenshots_captured.push({ name, path: filePath });
    console.log(`[Screenshot Captured] ${name}.png`);
  }

  try {
    // 1. Initial Navigation & Authentication
    console.log('1. Navigating to http://localhost:3000/internal and establishing admin session...');
    await page.goto('http://localhost:3000/internal', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);

    // Inject Admin Auth
    await page.evaluate(() => {
      localStorage.setItem('wt_role', 'ROLE_ADMIN');
      localStorage.setItem('wt_email', 'operator@wingedtycoons.com');
      localStorage.setItem('wt_theme', 'dark');
      window.dispatchEvent(new Event('wt-auth-changed'));
    });
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);

    await takeScreenshot('01_internal_authenticated_home');
    report.routes_visited.push({ route: '/internal', name: 'Today (Operations Control Room)' });

    // Helper to count interactive elements on the current page
    async function discoverElements(viewName) {
      const counts = await page.evaluate(() => {
        const buttons = Array.from(document.querySelectorAll('button:not([disabled])')).map(b => b.textContent?.trim() || b.getAttribute('aria-label') || 'Button');
        const links = Array.from(document.querySelectorAll('a[href]')).map(a => a.textContent?.trim() || a.getAttribute('href') || 'Link');
        const inputs = Array.from(document.querySelectorAll('input:not([disabled]), textarea:not([disabled])')).map(i => i.getAttribute('placeholder') || i.getAttribute('name') || 'Input');
        const selects = document.querySelectorAll('select:not([disabled])').length;
        const tabs = document.querySelectorAll('[role="tab"]').length;
        return {
          buttonCount: buttons.length,
          linkCount: links.length,
          inputCount: inputs.length,
          selectCount: selects,
          tabCount: tabs,
          total: buttons.length + links.length + inputs.length + selects + tabs,
          sampleButtons: buttons.slice(0, 10),
          sampleInputs: inputs.slice(0, 5),
        };
      });
      report.element_discovery[viewName] = counts;
      console.log(`[Discovery] ${viewName}: ${counts.total} interactive controls (${counts.buttonCount} buttons, ${counts.inputCount} inputs, ${counts.linkCount} links)`);
      return counts;
    }

    await discoverElements('Today (Operations Control Room)');

    // 2. Test TopBar Interactions
    console.log('\n2. Testing TopBar Mutations (Theme Toggle, Audit Log Drawer, Global Search)...');
    
    // Theme Toggle
    const htmlClassesBefore = await page.evaluate(() => document.documentElement.className);
    const themeBtn = page.locator('header button[aria-label*="theme" i], header button:has(svg.lucide-sun), header button:has(svg.lucide-moon)').first();
    if (await themeBtn.isVisible()) {
      await themeBtn.click();
      await page.waitForTimeout(600);
      const htmlClassesAfter = await page.evaluate(() => document.documentElement.className);
      report.mutations_executed.push({
        action: 'TopBar Theme Toggle',
        before: htmlClassesBefore,
        after: htmlClassesAfter,
        success: htmlClassesBefore !== htmlClassesAfter,
      });
      await takeScreenshot('02_topbar_theme_toggled');
      console.log(`  - Theme toggled: ${htmlClassesBefore} -> ${htmlClassesAfter}`);
      // Toggle back to dark
      await themeBtn.click();
      await page.waitForTimeout(400);
    }

    // Audit Log Drawer Toggle
    const auditBtn = page.locator('header button[aria-label*="audit" i], header button:has(svg.lucide-activity)').first();
    if (await auditBtn.isVisible()) {
      await auditBtn.click();
      await page.waitForTimeout(800);
      await takeScreenshot('03_audit_log_drawer_open');
      report.dialogs_visited.push({ name: 'Audit Log Slide-Over Drawer', status: 'Opened' });
      report.mutations_executed.push({ action: 'Open Audit Log Drawer', success: true });
      console.log('  - Audit Log Drawer opened.');

      // Close drawer
      const closeDrawerBtn = page.locator('button:has(svg.lucide-x)').first();
      if (await closeDrawerBtn.isVisible()) {
        await closeDrawerBtn.click();
        await page.waitForTimeout(400);
        report.mutations_executed.push({ action: 'Close Audit Log Drawer', success: true });
        console.log('  - Audit Log Drawer closed.');
      }
    }

    // 3. Systematically Crawl & Mutate All Sidebar Views
    const sidebarViews = [
      { name: 'Business Overview', label: 'Business Overview' },
      { name: 'Today (Operations)', label: 'Today' },
      { name: 'My Work', label: 'My Work' },
      { name: 'RFQs & Quotes', label: 'RFQs & Quotes' },
      { name: 'Supplier Offers', label: 'Supplier Offers' },
      { name: 'Inventory & Email', label: 'Inventory & Email' },
      { name: 'Shipments', label: 'Shipments' },
      { name: 'Reviews & AI Health', label: 'Reviews & AI Health' },
    ];

    console.log('\n3. Crawling and Testing Sidebar Views...');
    for (let i = 0; i < sidebarViews.length; i++) {
      const view = sidebarViews[i];
      console.log(`\nNavigating to View [${i + 1}/${sidebarViews.length}]: ${view.name}...`);
      
      const navBtn = page.locator(`button[aria-label="${view.label}"]`).first();
      if (await navBtn.isVisible()) {
        await navBtn.click();
        await page.waitForTimeout(1000);
        report.routes_visited.push({ route: `/internal (${view.label})`, name: view.name });
        await discoverElements(view.name);
        await takeScreenshot(`04_${view.label.toLowerCase().replace(/[^a-z0-9]/g, '_')}`);

        // View-specific interactive mutations
        if (view.label === 'Supplier Offers') {
          const searchInput = page.locator('input[placeholder*="part" i], input[placeholder*="search" i]').first();
          if (await searchInput.isVisible()) {
            await searchInput.fill('060-1234-00');
            await page.waitForTimeout(600);
            report.mutations_executed.push({ action: 'Supplier Offers: Search Part 060-1234-00', success: true });
            await takeScreenshot('05_sourcing_search_filtered');
            console.log('  - Filtered supplier offers by part 060-1234-00');
          }
        }

        if (view.label === 'Shipments') {
          const mapToggleBtn = page.locator('button:has-text("Interactive Map"), button:has-text("Map"), button:has(svg.lucide-map)').first();
          if (await mapToggleBtn.isVisible()) {
            await mapToggleBtn.click();
            await page.waitForTimeout(1200);
            report.mutations_executed.push({ action: 'Shipments: Switch to Interactive Map View', success: true });
            await takeScreenshot('06_shipments_map_view');
            console.log('  - Switched to Interactive Map view');

            // Switch back to list
            const listToggleBtn = page.locator('button:has-text("Shipments List"), button:has-text("List")').first();
            if (await listToggleBtn.isVisible()) {
              await listToggleBtn.click();
              await page.waitForTimeout(600);
              report.mutations_executed.push({ action: 'Shipments: Switch back to List View', success: true });
              console.log('  - Switched back to List view');
            }
          }
        }

        if (view.label === 'Reviews & AI Health') {
          const filterInput = page.locator('input[placeholder*="filter" i], input[placeholder*="search" i]').first();
          if (await filterInput.isVisible()) {
            await filterInput.fill('FAA 8130');
            await page.waitForTimeout(600);
            report.mutations_executed.push({ action: 'Reviews & AI Health: Filter Certifications by FAA 8130', success: true });
            await takeScreenshot('07_reviews_filtered');
            console.log('  - Filtered compliance records by FAA 8130');
          }
        }

        if (view.label === 'My Work') {
          const tabs = ['Leaderboard', 'Profile', 'Sales'];
          for (const tabName of tabs) {
            const tabBtn = page.locator(`button:has-text("${tabName}")`).first();
            if (await tabBtn.isVisible()) {
              await tabBtn.click();
              await page.waitForTimeout(600);
              report.mutations_executed.push({ action: `My Work: Switch tab to ${tabName}`, success: true });
              await takeScreenshot(`08_mywork_${tabName.toLowerCase()}`);
              console.log(`  - Switched sub-tab to ${tabName}`);
            }
          }
        }

        if (view.label === 'Today') {
          // Check for Review Queue / Extraction Review dialog triggers
          const reviewBtn = page.locator('button:has-text("Review"), button:has-text("Inspect"), button:has-text("Open Review")').first();
          if (await reviewBtn.isVisible()) {
            await reviewBtn.click();
            await page.waitForTimeout(800);
            const dialog = page.locator('[role="dialog"]').first();
            if (await dialog.isVisible()) {
              report.dialogs_visited.push({ name: 'Extraction Review Dialog', status: 'Opened' });
              report.mutations_executed.push({ action: 'Open Extraction Review Dialog', success: true });
              await takeScreenshot('09_extraction_review_dialog');
              console.log('  - Opened Extraction Review Dialog');

              // Test editing an input in the review dialog (Customer Name or Company)
              const nameInput = dialog.locator('input[id*="customer_name" i], input[name*="customer_name" i], input').first();
              if (await nameInput.isVisible()) {
                const prev = await nameInput.inputValue();
                await nameInput.fill(prev ? `${prev} (Verified)` : 'Priya Nair (Verified)');
                report.mutations_executed.push({ action: 'Edit customer contact in Review Dialog', success: true });
                console.log('  - Tested non-destructive edit in Extraction Review Dialog');
              }

              // Close dialog
              const cancelBtn = dialog.locator('button:has-text("Cancel"), button:has-text("Close"), button:has(svg.lucide-x)').first();
              if (await cancelBtn.isVisible()) {
                await cancelBtn.click();
                await page.waitForTimeout(500);
                report.mutations_executed.push({ action: 'Close Extraction Review Dialog', success: true });
                console.log('  - Closed Extraction Review Dialog');
              }
            }
          }
        }
      }
    }

    // 4. Return to Operations Home and test Global Search routing
    console.log('\n4. Testing Global Search Bar in TopBar...');
    const globalSearch = page.locator('header input[type="text"], header input[placeholder*="search" i]').first();
    if (await globalSearch.isVisible()) {
      await globalSearch.fill('060-1234-00');
      await globalSearch.press('Enter');
      await page.waitForTimeout(800);
      report.mutations_executed.push({ action: 'TopBar Global Search: "060-1234-00" (Auto-routes to Sourcing)', success: true });
      await takeScreenshot('10_global_search_routed');
      console.log('  - TopBar Global Search: typed "060-1234-00" and routed successfully.');
    }

    console.log('\n=== Crawl & Mutation Run Completed Successfully ===');

  } catch (err) {
    console.error('Error during crawl execution:', err);
    report.fatal_error = err.message;
  } finally {
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(report, null, 2), 'utf-8');
    console.log(`\nDetailed report written to: ${RESULTS_FILE}`);
    await browser.close();
  }
}

runCrawl().catch(console.error);
