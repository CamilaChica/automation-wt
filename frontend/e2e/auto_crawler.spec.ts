import { test, expect } from '@playwright/test';

const ORIGIN = 'https://winged-tycoons-frontend.onrender.com';

const VIEWPORTS = [
  { name: 'iPhone SE', width: 375, height: 667 },
  { name: 'iPhone 14 Pro', width: 393, height: 852 },
  { name: 'Pixel 7', width: 412, height: 915 },
  { name: 'iPad Mini', width: 768, height: 1024 },
];

const ROUTES = [
  '/internal',
  '/internal/sales',
  '/internal/sourcing',
  '/internal/trace',
  '/internal/procurement',
  '/internal/fulfillment',
];

test('Strict Mobile Responsive Layout Audit', async ({ page }) => {
  for (const vp of VIEWPORTS) {
    await page.setViewportSize({ width: vp.width, height: vp.height });

    for (const route of ROUTES) {
      await page.goto(`${ORIGIN}${route}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(600); // Allow responsive CSS recalculation

      // 1. ASSERT SIDEBAR IS COLLAPSED ON MOBILE/TABLET (Width < 1024px)
      const sidebarVisible = await page.evaluate(() => {
        const sidebar = document.querySelector('aside, nav, [class*="sidebar"]');
        if (!sidebar) return false;
        const rect = sidebar.getBoundingClientRect();
        // Check if desktop sidebar takes up >200px width on screen simultaneously with main content
        return rect.width > 200 && rect.left >= 0 && window.innerWidth < 1024;
      });

      expect(sidebarVisible, `[LAYOUT ERROR] Desktop sidebar is expanded on ${vp.name} (${vp.width}px) on ${route}. It must collapse into a mobile drawer.`).toBe(false);

      // 2. ASSERT MAIN CONTENT IS NOT OCCLUDED OR OVERLAPPING
      const isContentClipping = await page.evaluate(() => {
        const main = document.querySelector('main, [role="main"], .main-content');
        if (!main) return false;
        const rect = main.getBoundingClientRect();
        return rect.left < 0 || rect.width < 280; // Content squished under 280px
      });

      expect(isContentClipping, `[LAYOUT ERROR] Main content is squished or clipped on ${vp.name} on ${route}.`).toBe(false);

      const visualDefects = await page.evaluate(() => {
        const visibleElements = Array.from(document.querySelectorAll<HTMLElement>(
          'main *, aside *, header *, [role="dialog"] *, button, a[href], input, select, textarea, table, article, [role="button"], [role="tab"]',
        )).filter(element => {
          const rect = element.getBoundingClientRect();
          const style = window.getComputedStyle(element);
          return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
        });

        const minimumDimensionViolations = visibleElements
          .filter(element => {
            const isInteractive = element.matches('button, a[href], input, select, textarea, [role="button"], [role="tab"]');
            const rect = element.getBoundingClientRect();
            return isInteractive && (rect.width < 44 || rect.height < 44);
          })
          .slice(0, 30)
          .map(element => `${element.tagName.toLowerCase()}[aria-label="${element.getAttribute('aria-label') || ''}"] ${element.textContent?.trim().replace(/\s+/g, ' ').slice(0, 80) || ''} ${Math.round(element.getBoundingClientRect().width)}x${Math.round(element.getBoundingClientRect().height)}`);

        const overlapViolations: string[] = [];
        for (let firstIndex = 0; firstIndex < visibleElements.length; firstIndex += 1) {
          const first = visibleElements[firstIndex];
          const firstRect = first.getBoundingClientRect();
          for (let secondIndex = firstIndex + 1; secondIndex < visibleElements.length; secondIndex += 1) {
            const second = visibleElements[secondIndex];
            if (first.contains(second) || second.contains(first)) continue;
            const secondRect = second.getBoundingClientRect();
            const intersects = firstRect.left < secondRect.right && firstRect.right > secondRect.left
              && firstRect.top < secondRect.bottom && firstRect.bottom > secondRect.top;
            if (!intersects) continue;

            const firstStyle = window.getComputedStyle(first);
            const secondStyle = window.getComputedStyle(second);
            const isKnownLayering = firstStyle.position === 'absolute' || firstStyle.position === 'fixed'
              || secondStyle.position === 'absolute' || secondStyle.position === 'fixed';
            if (!isKnownLayering) {
              overlapViolations.push(`${first.tagName.toLowerCase()} overlaps ${second.tagName.toLowerCase()}`);
            }
            if (overlapViolations.length >= 30) break;
          }
          if (overlapViolations.length >= 30) break;
        }

        return { minimumDimensionViolations, overlapViolations };
      });

      expect(
        visualDefects.minimumDimensionViolations,
        `[READABILITY ERROR] Interactive elements below 44px on ${vp.name} at ${route}`,
      ).toEqual([]);
      expect(
        visualDefects.overlapViolations,
        `[OVERLAP ERROR] Visible layout elements overlap on ${vp.name} at ${route}`,
      ).toEqual([]);
    }
  }
});
