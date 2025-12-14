const { chromium } = require('playwright');

(async () => {
  console.log('Launching browser to review workflows page...');
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  // Navigate to the docs site
  const docsPath = 'http://localhost:8890';
  await page.goto(docsPath);
  console.log('✓ Loaded documentation site');

  // Wait for the page to load
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);

  // Take initial screenshot
  await page.screenshot({ path: 'workflows-page-loaded.png', fullPage: true });
  console.log('✓ Initial screenshot saved: workflows-page-loaded.png');

  // Check what's on the page
  const bodyText = await page.locator('body').textContent();
  console.log('\n📄 Page contains text:', bodyText.substring(0, 200) + '...');

  // Look for navigation headers
  const navHeaders = page.locator('.nav-header');
  const navHeaderCount = await navHeaders.count();
  console.log(`\n🔍 Found ${navHeaderCount} nav headers`);

  if (navHeaderCount > 0) {
    for (let i = 0; i < navHeaderCount; i++) {
      const header = navHeaders.nth(i);
      const text = await header.textContent();
      const dataSection = await header.getAttribute('data-section');
      console.log(`  ${i + 1}. "${text?.trim()}" - data-section="${dataSection}"`);
    }
  }

  // Try to find and click workflows header
  try {
    const workflowsHeaders = page.locator('.nav-header').filter({ hasText: 'Workflows' });
    const count = await workflowsHeaders.count();
    console.log(`\n🎯 Found ${count} headers containing "Workflows"`);

    if (count > 0) {
      const workflowsHeader = workflowsHeaders.first();
      console.log('  Clicking on Workflows header...');
      await workflowsHeader.click({ timeout: 5000 });
      console.log('  ✓ Clicked Workflows header');
      await page.waitForTimeout(1000);

      // Take screenshot after expand
      await page.screenshot({ path: 'workflows-sidebar-expanded.png', fullPage: true });
      console.log('  ✓ Screenshot after expand: workflows-sidebar-expanded.png');
    }
  } catch (error) {
    console.log(`  ⚠️  Could not click workflows header: ${error.message}`);
  }

  // Check for workflows list
  const workflowsList = page.locator('#workflows-list li');
  const workflowsCount = await workflowsList.count();
  console.log(`\n📋 Found ${workflowsCount} workflows in list`);

  if (workflowsCount > 0) {
    for (let i = 0; i < Math.min(5, workflowsCount); i++) {
      const workflow = workflowsList.nth(i);
      const text = await workflow.textContent();
      console.log(`  ${i + 1}. ${text?.trim()}`);
    }
  }

  // Look for all tables on the page
  const tables = page.locator('table');
  const tableCount = await tables.count();
  console.log(`\n📊 Found ${tableCount} tables on page`);

  if (tableCount > 0) {
    for (let i = 0; i < tableCount; i++) {
      const table = tables.nth(i);
      const headers = table.locator('th');
      const headerCount = await headers.count();

      console.log(`\nTable ${i + 1} (${headerCount} headers):`);

      if (headerCount > 0) {
        for (let j = 0; j < headerCount; j++) {
          const th = headers.nth(j);
          const text = await th.textContent();
          const classes = await th.getAttribute('class');
          console.log(`  ${j + 1}. "${text?.trim()}" - classes: ${classes || 'none'}`);
        }

        // Take screenshot of this table
        await table.screenshot({ path: `table-${i + 1}.png` });
        console.log(`  ✓ Screenshot: table-${i + 1}.png`);
      }
    }
  }

  // Look for sortable headers specifically
  const sortableHeaders = page.locator('.sortable-header, th.sortable, [class*="sortable"]');
  const sortableCount = await sortableHeaders.count();
  console.log(`\n🔽 Found ${sortableCount} sortable headers`);

  if (sortableCount > 0) {
    for (let i = 0; i < sortableCount; i++) {
      const header = sortableHeaders.nth(i);
      const text = await header.textContent();
      const classes = await header.getAttribute('class');
      const styles = await header.evaluate(el => {
        const computed = window.getComputedStyle(el);
        const after = window.getComputedStyle(el, '::after');
        return {
          cursor: computed.cursor,
          position: computed.position,
          paddingRight: computed.paddingRight,
          afterContent: after.content,
          afterOpacity: after.opacity
        };
      });

      console.log(`  ${i + 1}. "${text?.trim()}"`);
      console.log(`      Classes: ${classes}`);
      console.log(`      Styles:`, JSON.stringify(styles, null, 6));
    }

    // Test clicking on first sortable header
    console.log('\n🖱️  Testing sort interaction...');
    const firstSortable = sortableHeaders.first();
    const headerText = await firstSortable.textContent();

    console.log(`  Initial state: "${headerText?.trim()}"`);
    const classesBefore = await firstSortable.getAttribute('class');
    console.log(`  Classes before: ${classesBefore}`);

    // First click
    await firstSortable.click();
    await page.waitForTimeout(500);
    const classesAfter1 = await firstSortable.getAttribute('class');
    console.log(`  Classes after 1st click: ${classesAfter1}`);

    await page.screenshot({ path: 'sort-after-click-1.png', fullPage: true });
    console.log('  ✓ Screenshot: sort-after-click-1.png');

    // Second click
    await firstSortable.click();
    await page.waitForTimeout(500);
    const classesAfter2 = await firstSortable.getAttribute('class');
    console.log(`  Classes after 2nd click: ${classesAfter2}`);

    await page.screenshot({ path: 'sort-after-click-2.png', fullPage: true });
    console.log('  ✓ Screenshot: sort-after-click-2.png');
  }

  console.log('\n✅ Review complete! Screenshots saved.');
  console.log('Keeping browser open for 30 seconds for manual inspection...');

  // Keep browser open briefly
  await page.waitForTimeout(30000);

  await browser.close();
  console.log('Browser closed.');
})();
