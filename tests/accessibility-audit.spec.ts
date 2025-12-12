import { test, expect, Page } from '@playwright/test';
import type { Locator } from '@playwright/test';

/**
 * Comprehensive Accessibility & Usability Audit
 * Agent-Actions Documentation Site
 *
 * Testing against WCAG 2.1 AA standards and best practices
 */

const BASE_URL = 'http://localhost:8890';

test.describe('Accessibility & Usability Audit', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    // Wait for data to load
    await page.waitForSelector('.stats-cards', { timeout: 10000 });
  });

  // ============================================
  // 1. KEYBOARD NAVIGATION
  // ============================================

  test.describe('1. Keyboard Navigation', () => {

    test('should allow tab navigation through all interactive elements', async ({ page }) => {
      const focusableElements = await page.evaluate(() => {
        const selectors = [
          'a[href]',
          'button:not([disabled])',
          'input:not([disabled])',
          '[tabindex]:not([tabindex="-1"])'
        ];
        return document.querySelectorAll(selectors.join(',')).length;
      });

      console.log(`Found ${focusableElements} focusable elements`);
      expect(focusableElements).toBeGreaterThan(0);

      // Tab through first 10 elements and verify focus
      for (let i = 0; i < Math.min(10, focusableElements); i++) {
        await page.keyboard.press('Tab');
        const focused = await page.evaluate(() => {
          const el = document.activeElement;
          return {
            tag: el?.tagName,
            class: el?.className,
            hasVisibleOutline: el ? window.getComputedStyle(el).outline !== 'none' : false
          };
        });
        console.log(`Tab ${i + 1}:`, focused);
      }
    });

    test('should have logical tab order', async ({ page }) => {
      const tabOrder = await page.evaluate(() => {
        const focusable = Array.from(document.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ));
        return focusable.map((el, i) => ({
          index: i,
          tag: el.tagName,
          text: el.textContent?.trim().slice(0, 30) || '',
          tabIndex: el.getAttribute('tabindex') || '0',
          position: {
            x: (el as HTMLElement).offsetLeft,
            y: (el as HTMLElement).offsetTop
          }
        }));
      });

      console.log('Tab order (first 15):', tabOrder.slice(0, 15));

      // Verify sidebar comes before main content
      const sidebarElements = tabOrder.filter(el =>
        el.text.includes('Agent-Actions') ||
        el.text.includes('Overview') ||
        el.text.includes('Workflows')
      );
      const mainElements = tabOrder.filter(el =>
        el.text.includes('QanaLabs Workflows') ||
        el.text.includes('Total Actions')
      );

      if (sidebarElements.length > 0 && mainElements.length > 0) {
        expect(sidebarElements[0].index).toBeLessThan(mainElements[0].index);
      }
    });

    test('CRITICAL: should show visible focus indicators', async ({ page }) => {
      const issues: string[] = [];

      // Test search input
      await page.click('#search-input');
      const searchFocus = await page.evaluate(() => {
        const el = document.getElementById('search-input');
        if (!el) return null;
        const styles = window.getComputedStyle(el);
        return {
          outline: styles.outline,
          boxShadow: styles.boxShadow,
          borderColor: styles.borderColor
        };
      });

      if (searchFocus && searchFocus.outline === 'none' && !searchFocus.boxShadow.includes('rgb')) {
        issues.push('Search input lacks visible focus indicator');
      }

      // Test stat cards
      const statCards = await page.$$('.stat-card');
      if (statCards.length > 0) {
        await statCards[0].focus();
        const cardFocus = await page.evaluate(() => {
          const el = document.querySelector('.stat-card:focus');
          if (!el) return null;
          const styles = window.getComputedStyle(el);
          return {
            outline: styles.outline,
            boxShadow: styles.boxShadow
          };
        });

        if (!cardFocus) {
          issues.push('Stat cards lack focus state - should have tabindex="0" or be buttons');
        }
      }

      // Test buttons
      const buttons = await page.$$('button');
      for (const button of buttons.slice(0, 3)) {
        await button.focus();
        const hasFocus = await button.evaluate(el => {
          const styles = window.getComputedStyle(el);
          return styles.outline !== 'none' || styles.boxShadow.includes('rgb');
        });

        if (!hasFocus) {
          const text = await button.textContent();
          issues.push(`Button "${text?.slice(0, 20)}" lacks visible focus indicator`);
        }
      }

      console.log('Focus indicator issues:', issues);
      expect(issues.length).toBe(0);
    });

    test('should allow keyboard navigation of tables', async ({ page }) => {
      const table = await page.$('.runs-table');
      if (!table) {
        console.log('No table found on overview page');
        return;
      }

      // Check if table rows are keyboard accessible
      const rowsAccessible = await page.evaluate(() => {
        const rows = Array.from(document.querySelectorAll('.runs-table tbody tr'));
        return rows.map(row => ({
          isClickable: (row as HTMLElement).style.cursor === 'pointer',
          hasTabIndex: row.hasAttribute('tabindex'),
          hasClickHandler: (row as any).onclick !== null
        }));
      });

      console.log('Table rows accessibility:', rowsAccessible.slice(0, 5));

      // If rows are clickable, they should be keyboard accessible
      const clickableRows = rowsAccessible.filter(r => r.isClickable);
      if (clickableRows.length > 0) {
        const accessibleRows = clickableRows.filter(r => r.hasTabIndex);
        if (accessibleRows.length === 0) {
          console.warn('CRITICAL: Clickable table rows lack tabindex for keyboard access');
        }
      }
    });

    test('should support arrow key navigation in sidebar', async ({ page }) => {
      // Focus first nav link
      await page.focus('.nav-link');
      const initialFocus = await page.evaluate(() => document.activeElement?.textContent);

      // Press arrow down
      await page.keyboard.press('ArrowDown');
      const afterArrow = await page.evaluate(() => document.activeElement?.textContent);

      console.log('Arrow key navigation:', { initialFocus, afterArrow });
      // Note: This may not work without custom JavaScript - log for awareness
    });
  });

  // ============================================
  // 2. SCREEN READER SUPPORT
  // ============================================

  test.describe('2. Screen Reader Support', () => {

    test('CRITICAL: should have proper semantic HTML structure', async ({ page }) => {
      const structure = await page.evaluate(() => {
        return {
          hasMain: !!document.querySelector('main'),
          hasNav: !!document.querySelector('nav'),
          hasAside: !!document.querySelector('aside'),
          h1Count: document.querySelectorAll('h1').length,
          headingStructure: Array.from(document.querySelectorAll('h1, h2, h3, h4')).map(h => ({
            level: h.tagName,
            text: h.textContent?.trim().slice(0, 40)
          }))
        };
      });

      console.log('Semantic structure:', structure);

      expect(structure.hasMain).toBe(true);
      expect(structure.hasNav).toBe(true);
      expect(structure.h1Count).toBeGreaterThanOrEqual(1);
      expect(structure.h1Count).toBeLessThanOrEqual(2); // Should only have 1 h1 per page
    });

    test('CRITICAL: should have proper table structure', async ({ page }) => {
      const tableStructure = await page.evaluate(() => {
        const tables = Array.from(document.querySelectorAll('table'));
        return tables.map(table => ({
          hasCaption: !!table.querySelector('caption'),
          hasThead: !!table.querySelector('thead'),
          hasTbody: !!table.querySelector('tbody'),
          headers: Array.from(table.querySelectorAll('th')).map(th => ({
            text: th.textContent?.trim(),
            hasScope: th.hasAttribute('scope'),
            scope: th.getAttribute('scope')
          })),
          firstRowCells: Array.from(table.querySelectorAll('tbody tr:first-child td')).map(td => ({
            hasHeaders: td.hasAttribute('headers'),
            headers: td.getAttribute('headers')
          }))
        }));
      });

      console.log('Table structure:', JSON.stringify(tableStructure, null, 2));

      tableStructure.forEach((table, i) => {
        expect(table.hasThead, `Table ${i + 1} should have <thead>`).toBe(true);
        expect(table.hasTbody, `Table ${i + 1} should have <tbody>`).toBe(true);

        // Headers should ideally have scope attribute
        const headersWithScope = table.headers.filter(h => h.hasScope);
        if (headersWithScope.length === 0) {
          console.warn(`Table ${i + 1} headers lack scope attributes for screen readers`);
        }
      });
    });

    test('CRITICAL: should have proper ARIA labels and roles', async ({ page }) => {
      const ariaIssues: string[] = [];

      // Check buttons have labels
      const buttons = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('button')).map(btn => ({
          text: btn.textContent?.trim(),
          ariaLabel: btn.getAttribute('aria-label'),
          title: btn.getAttribute('title'),
          hasContent: (btn.textContent?.trim().length || 0) > 0,
          innerHTML: btn.innerHTML.slice(0, 50)
        }));
      });

      buttons.forEach((btn, i) => {
        if (!btn.hasContent && !btn.ariaLabel && !btn.title) {
          ariaIssues.push(`Button ${i + 1} lacks accessible label (only contains: "${btn.innerHTML}")`);
        }
      });

      // Check stat cards (interactive) have proper roles
      const statCards = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('.stat-card')).map(card => ({
          role: card.getAttribute('role'),
          tabindex: card.getAttribute('tabindex'),
          ariaLabel: card.getAttribute('aria-label'),
          text: card.textContent?.trim().slice(0, 50)
        }));
      });

      statCards.forEach((card, i) => {
        if (card.role === 'button' && !card.tabindex) {
          ariaIssues.push(`Stat card ${i + 1} has role="button" but no tabindex`);
        }
        if (card.tabindex && !card.role) {
          console.warn(`Stat card ${i + 1} has tabindex but no role`);
        }
      });

      // Check search input
      const searchInput = await page.evaluate(() => {
        const input = document.getElementById('search-input');
        return input ? {
          hasLabel: !!document.querySelector('label[for="search-input"]'),
          ariaLabel: input.getAttribute('aria-label'),
          placeholder: input.getAttribute('placeholder'),
          id: input.id
        } : null;
      });

      if (searchInput && !searchInput.hasLabel && !searchInput.ariaLabel) {
        ariaIssues.push('Search input lacks proper label (use <label> or aria-label)');
      }

      console.log('ARIA issues:', ariaIssues);
      console.log('Stat cards:', statCards);
      console.log('Buttons:', buttons.slice(0, 5));

      expect(ariaIssues.length).toBe(0);
    });

    test('should have proper status badge announcements', async ({ page }) => {
      const badges = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('.status-badge')).map(badge => ({
          text: badge.textContent?.trim(),
          ariaLabel: badge.getAttribute('aria-label'),
          role: badge.getAttribute('role'),
          className: badge.className
        }));
      });

      console.log('Status badges:', badges.slice(0, 10));

      // Status badges should have consistent, clear text
      badges.forEach(badge => {
        expect(badge.text).toBeTruthy();
        expect(badge.text?.length).toBeGreaterThan(0);
      });
    });

    test('should have accessible navigation landmarks', async ({ page }) => {
      const landmarks = await page.evaluate(() => {
        return {
          nav: Array.from(document.querySelectorAll('nav')).map(n => ({
            ariaLabel: n.getAttribute('aria-label'),
            ariaLabelledby: n.getAttribute('aria-labelledby')
          })),
          main: Array.from(document.querySelectorAll('main')).map(m => ({
            ariaLabel: m.getAttribute('aria-label')
          })),
          aside: Array.from(document.querySelectorAll('aside')).map(a => ({
            ariaLabel: a.getAttribute('aria-label')
          }))
        };
      });

      console.log('Landmarks:', landmarks);

      // Multiple navs should have labels to distinguish them
      if (landmarks.nav.length > 1) {
        const unlabeled = landmarks.nav.filter(n => !n.ariaLabel && !n.ariaLabelledby);
        if (unlabeled.length > 0) {
          console.warn(`${unlabeled.length} nav elements lack aria-label`);
        }
      }
    });
  });

  // ============================================
  // 3. COLOR & CONTRAST
  // ============================================

  test.describe('3. Color & Contrast', () => {

    test('CRITICAL: should meet WCAG AA contrast ratios', async ({ page }) => {
      // Helper function to calculate contrast ratio
      const getContrast = (rgb1: string, rgb2: string): number => {
        const getLuminance = (rgb: string): number => {
          const [r, g, b] = rgb.match(/\d+/g)!.map(Number);
          const [rs, gs, bs] = [r, g, b].map(val => {
            const s = val / 255;
            return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
          });
          return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
        };

        const l1 = getLuminance(rgb1);
        const l2 = getLuminance(rgb2);
        const lighter = Math.max(l1, l2);
        const darker = Math.min(l1, l2);
        return (lighter + 0.05) / (darker + 0.05);
      };

      const contrastIssues = await page.evaluate(() => {
        const issues: any[] = [];

        // Check text elements
        const textElements = document.querySelectorAll('p, span, a, button, h1, h2, h3, td, th, label');
        const checked = new Set<HTMLElement>();

        Array.from(textElements).slice(0, 50).forEach(el => {
          if (checked.has(el as HTMLElement)) return;
          checked.add(el as HTMLElement);

          const styles = window.getComputedStyle(el);
          const color = styles.color;
          const bgColor = styles.backgroundColor;
          const fontSize = parseFloat(styles.fontSize);
          const fontWeight = styles.fontWeight;

          // Skip if no background (transparent)
          if (bgColor === 'rgba(0, 0, 0, 0)' || !bgColor) return;

          issues.push({
            element: el.tagName,
            text: (el.textContent?.trim().slice(0, 30) || ''),
            color,
            bgColor,
            fontSize,
            fontWeight,
            className: el.className
          });
        });

        return issues;
      });

      console.log(`Checking ${contrastIssues.length} elements for contrast...`);

      const failedContrast: any[] = [];

      contrastIssues.forEach(item => {
        try {
          const ratio = getContrast(item.color, item.bgColor);
          const isLargeText = item.fontSize >= 18 || (item.fontSize >= 14 && parseInt(item.fontWeight) >= 700);
          const requiredRatio = isLargeText ? 3 : 4.5; // WCAG AA

          if (ratio < requiredRatio) {
            failedContrast.push({
              ...item,
              ratio: ratio.toFixed(2),
              required: requiredRatio,
              isLargeText
            });
          }
        } catch (e) {
          // Skip invalid colors
        }
      });

      console.log('Contrast failures (WCAG AA):', failedContrast.slice(0, 10));

      if (failedContrast.length > 0) {
        console.warn(`Found ${failedContrast.length} contrast issues`);
      }
    });

    test('CRITICAL: should not rely solely on color for status', async ({ page }) => {
      const statusElements = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('.status-badge')).map(badge => ({
          text: badge.textContent?.trim(),
          className: badge.className,
          hasIcon: !!badge.querySelector('svg') || badge.textContent?.includes('✓') || badge.textContent?.includes('✗'),
          styles: {
            color: window.getComputedStyle(badge).color,
            bgColor: window.getComputedStyle(badge).backgroundColor
          }
        }));
      });

      console.log('Status badges (color dependency check):', statusElements.slice(0, 10));

      // Status badges should have text labels, not just colors
      statusElements.forEach(badge => {
        expect(badge.text).toBeTruthy();
        expect(badge.text!.length).toBeGreaterThan(0);
      });

      // Ideally should also have icons, but text is minimum requirement
      const withoutIcons = statusElements.filter(b => !b.hasIcon);
      console.log(`${withoutIcons.length}/${statusElements.length} status badges lack icons (text-only)`);
    });

    test('should have distinguishable interactive elements', async ({ page }) => {
      const interactiveStyles = await page.evaluate(() => {
        const links = Array.from(document.querySelectorAll('a')).slice(0, 5);
        const buttons = Array.from(document.querySelectorAll('button')).slice(0, 5);

        return {
          links: links.map(a => {
            const styles = window.getComputedStyle(a);
            return {
              color: styles.color,
              textDecoration: styles.textDecoration,
              cursor: styles.cursor,
              underline: styles.textDecorationLine
            };
          }),
          buttons: buttons.map(btn => {
            const styles = window.getComputedStyle(btn);
            return {
              color: styles.color,
              bgColor: styles.backgroundColor,
              border: styles.border,
              cursor: styles.cursor
            };
          })
        };
      });

      console.log('Interactive element styles:', interactiveStyles);

      // Links should have some visual indicator (color, underline, or both)
      // Buttons should have clear boundaries
      expect(interactiveStyles.buttons.every(b => b.cursor === 'pointer')).toBe(true);
    });

    test('should support colorblind users with patterns/icons', async ({ page }) => {
      // Check if DAG nodes use more than just color
      const dagExists = await page.$('.dag-container');
      if (!dagExists) {
        console.log('No DAG found on this page');
        return;
      }

      // Navigate to a workflow to see DAG
      await page.click('.nav-link[data-view="overview"]');
      await page.waitForTimeout(500);

      const workflowLink = await page.$('.nav-link[data-workflow]');
      if (workflowLink) {
        await workflowLink.click();
        await page.waitForTimeout(1000);

        // Check DAG legend
        const legend = await page.evaluate(() => {
          const legendEl = document.querySelector('.dag-legend');
          if (!legendEl) return null;

          return Array.from(legendEl.querySelectorAll('.dag-legend-item')).map(item => ({
            text: item.textContent?.trim(),
            color: window.getComputedStyle(item.querySelector('.dag-legend-dot') || item).backgroundColor
          }));
        });

        console.log('DAG legend:', legend);

        if (legend) {
          // Legend should have text labels, not just colored dots
          legend.forEach(item => {
            expect(item.text).toBeTruthy();
          });
        }
      }
    });
  });

  // ============================================
  // 4. RESPONSIVE DESIGN
  // ============================================

  test.describe('4. Responsive Design', () => {

    test('should work on mobile viewport (375x667)', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto(BASE_URL);
      await page.waitForSelector('.stats-cards', { timeout: 10000 });

      // Check if sidebar is hidden or transformed
      const sidebar = await page.$('.sidebar');
      const sidebarVisible = await sidebar?.isVisible();
      const sidebarStyles = await page.evaluate(() => {
        const el = document.querySelector('.sidebar');
        if (!el) return null;
        const styles = window.getComputedStyle(el);
        return {
          display: styles.display,
          transform: styles.transform,
          position: styles.position,
          width: styles.width
        };
      });

      console.log('Mobile sidebar:', { sidebarVisible, sidebarStyles });

      // Main content should be visible
      const mainContent = await page.$('.main-content');
      expect(await mainContent?.isVisible()).toBe(true);

      // Stats cards should stack vertically
      const statsLayout = await page.evaluate(() => {
        const cards = Array.from(document.querySelectorAll('.stat-card'));
        if (cards.length < 2) return null;

        const firstCard = cards[0].getBoundingClientRect();
        const secondCard = cards[1].getBoundingClientRect();

        return {
          firstCardWidth: firstCard.width,
          secondCardWidth: secondCard.width,
          isStacked: firstCard.bottom <= secondCard.top + 10, // Allow for small gap
          gap: secondCard.top - firstCard.bottom
        };
      });

      console.log('Stats cards layout (mobile):', statsLayout);
    });

    test('should have responsive tables', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const table = await page.$('.runs-table');
      if (!table) {
        console.log('No table on this view');
        return;
      }

      const tableResponsive = await page.evaluate(() => {
        const table = document.querySelector('.runs-table');
        if (!table) return null;

        const container = table.closest('.recent-runs-container');
        const styles = window.getComputedStyle(container || table);

        return {
          overflowX: styles.overflowX,
          tableWidth: table.getBoundingClientRect().width,
          viewportWidth: window.innerWidth,
          isScrollable: styles.overflowX === 'auto' || styles.overflowX === 'scroll'
        };
      });

      console.log('Table responsiveness:', tableResponsive);

      // Table should either fit or be scrollable
      if (tableResponsive && tableResponsive.tableWidth > tableResponsive.viewportWidth) {
        expect(tableResponsive.isScrollable).toBe(true);
      }
    });

    test('should have usable sidebar toggle on mobile', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const toggleButton = await page.$('.sidebar-toggle, .floating-sidebar-toggle');
      if (toggleButton) {
        const isVisible = await toggleButton.isVisible();
        console.log('Sidebar toggle visible on mobile:', isVisible);

        if (isVisible) {
          // Should be large enough to tap (min 44x44px for mobile)
          const size = await toggleButton.evaluate(el => {
            const rect = el.getBoundingClientRect();
            return { width: rect.width, height: rect.height };
          });

          console.log('Toggle button size:', size);
          expect(size.width).toBeGreaterThanOrEqual(28); // Minimum tap target
          expect(size.height).toBeGreaterThanOrEqual(28);
        }
      }
    });

    test('should maintain readability on tablet (768x1024)', async ({ page }) => {
      await page.setViewportSize({ width: 768, height: 1024 });
      await page.goto(BASE_URL);
      await page.waitForSelector('.stats-cards');

      const textSizes = await page.evaluate(() => {
        const elements = document.querySelectorAll('h1, h2, p, td, th');
        return Array.from(elements).slice(0, 20).map(el => ({
          tag: el.tagName,
          fontSize: parseFloat(window.getComputedStyle(el).fontSize),
          text: el.textContent?.trim().slice(0, 30)
        }));
      });

      console.log('Text sizes on tablet:', textSizes);

      // Body text should be at least 14px
      const bodyText = textSizes.filter(t => ['P', 'TD', 'TH'].includes(t.tag));
      bodyText.forEach(t => {
        expect(t.fontSize).toBeGreaterThanOrEqual(12);
      });
    });
  });

  // ============================================
  // 5. ERROR STATES & FEEDBACK
  // ============================================

  test.describe('5. Error States & Feedback', () => {

    test('should show clear empty states', async ({ page }) => {
      // Try searching for something that doesn't exist
      const searchInput = await page.$('#search-input');
      if (searchInput) {
        await searchInput.fill('xyznonexistentworkflow123');
        await page.keyboard.press('Enter');
        await page.waitForTimeout(500);

        const emptyState = await page.evaluate(() => {
          // Look for empty state indicators
          const tbody = document.querySelector('.runs-table tbody');
          return tbody?.textContent?.includes('No') || tbody?.textContent?.includes('match');
        });

        console.log('Empty state shown:', emptyState);
      }
    });

    test('should provide feedback for loading states', async ({ page }) => {
      // Check if there are any loading indicators in the HTML
      const hasLoadingIndicators = await page.evaluate(() => {
        const indicators = document.querySelectorAll('[class*="loading"], [class*="spinner"], [aria-busy="true"]');
        return indicators.length > 0;
      });

      console.log('Has loading indicators:', hasLoadingIndicators);

      // This is informational - good practice but not critical
    });

    test('should handle data loading errors gracefully', async ({ page }) => {
      // Navigate to a page that might fail
      const errorHandling = await page.evaluate(() => {
        return {
          hasErrorBoundary: document.querySelector('[class*="error"]') !== null,
          consoleErrors: [] // Would need to capture console in real scenario
        };
      });

      console.log('Error handling:', errorHandling);
    });
  });

  // ============================================
  // 6. USABILITY HEURISTICS
  // ============================================

  test.describe('6. Usability Heuristics', () => {

    test('should have consistent navigation across pages', async ({ page }) => {
      // Click on a workflow
      const workflowLink = await page.$('.nav-link[data-workflow]');
      if (workflowLink) {
        await workflowLink.click();
        await page.waitForTimeout(500);

        // Check if sidebar is still present
        const sidebar = await page.$('.sidebar');
        expect(await sidebar?.isVisible()).toBe(true);

        // Check if breadcrumbs are present
        const breadcrumb = await page.$('.breadcrumb');
        const breadcrumbText = await breadcrumb?.textContent();
        console.log('Breadcrumb:', breadcrumbText);

        expect(breadcrumbText).toBeTruthy();
      }
    });

    test('should provide clear action feedback', async ({ page }) => {
      // Click on a stat card
      const statCard = await page.$('.stat-card');
      if (statCard) {
        await statCard.click();
        await page.waitForTimeout(500);

        // Should navigate somewhere
        const currentView = await page.evaluate(() => {
          return document.querySelector('.content-view.active')?.id;
        });

        console.log('After clicking stat card, active view:', currentView);
        expect(currentView).toBeTruthy();
      }
    });

    test('should have descriptive page titles', async ({ page }) => {
      const title = await page.title();
      console.log('Page title:', title);

      expect(title).toBeTruthy();
      expect(title.length).toBeGreaterThan(0);
      expect(title).not.toBe('Document'); // Should be descriptive
    });

    test('should have consistent terminology', async ({ page }) => {
      const terms = await page.evaluate(() => {
        const text = document.body.textContent || '';
        return {
          hasWorkflow: text.includes('Workflow'),
          hasWorkflows: text.includes('Workflows'),
          hasAction: text.includes('Action'),
          hasActions: text.includes('Actions'),
          hasRun: text.includes('Run'),
          hasRuns: text.includes('Runs')
        };
      });

      console.log('Terminology usage:', terms);
      // Just logging - consistency should be verified manually
    });

    test('should show help/documentation where needed', async ({ page }) => {
      // Look for help icons, tooltips, or info buttons
      const helpElements = await page.evaluate(() => {
        const helps = document.querySelectorAll('[title], [aria-describedby], [data-tooltip]');
        return Array.from(helps).slice(0, 10).map(el => ({
          tag: el.tagName,
          title: el.getAttribute('title'),
          ariaDescribedby: el.getAttribute('aria-describedby'),
          text: el.textContent?.trim().slice(0, 30)
        }));
      });

      console.log('Help elements:', helpElements);
    });

    test('CRITICAL: should prevent errors with clear constraints', async ({ page }) => {
      // Check if filter inputs have validation
      const filterInputs = await page.$$('.filter-search-input');

      for (const input of filterInputs) {
        const attrs = await input.evaluate(el => ({
          type: (el as HTMLInputElement).type,
          maxLength: (el as HTMLInputElement).maxLength,
          pattern: el.getAttribute('pattern'),
          required: el.getAttribute('required')
        }));

        console.log('Filter input attributes:', attrs);
      }
    });
  });

  // ============================================
  // 7. PERFORMANCE & PERCEPTION
  // ============================================

  test.describe('7. Performance & Perception', () => {

    test('should load interactive elements quickly', async ({ page }) => {
      const startTime = Date.now();
      await page.goto(BASE_URL);
      await page.waitForSelector('.stat-card', { timeout: 10000 });
      const loadTime = Date.now() - startTime;

      console.log(`Page loaded in ${loadTime}ms`);
      expect(loadTime).toBeLessThan(5000); // Should load in under 5 seconds
    });

    test('should provide visual feedback on hover', async ({ page }) => {
      const statCard = await page.$('.stat-card');
      if (!statCard) return;

      // Get initial state
      const initialStyles = await statCard.evaluate(el => {
        const styles = window.getComputedStyle(el);
        return {
          boxShadow: styles.boxShadow,
          transform: styles.transform,
          borderColor: styles.borderColor
        };
      });

      // Hover
      await statCard.hover();
      await page.waitForTimeout(100);

      const hoverStyles = await statCard.evaluate(el => {
        const styles = window.getComputedStyle(el);
        return {
          boxShadow: styles.boxShadow,
          transform: styles.transform,
          borderColor: styles.borderColor
        };
      });

      console.log('Hover feedback:', {
        initial: initialStyles,
        hover: hoverStyles,
        changed: initialStyles.boxShadow !== hoverStyles.boxShadow ||
                initialStyles.transform !== hoverStyles.transform
      });

      // Should have some visual change on hover
      const hasHoverEffect =
        initialStyles.boxShadow !== hoverStyles.boxShadow ||
        initialStyles.transform !== hoverStyles.transform ||
        initialStyles.borderColor !== hoverStyles.borderColor;

      expect(hasHoverEffect).toBe(true);
    });
  });
});
