const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  await page.goto('http://localhost:8890');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  console.log('Page loaded, looking for search inputs...');

  // Look for any search input on the page
  const searchInputs = page.locator('input[type="text"], input[placeholder*="search" i], input[placeholder*="Search" i]');
  const count = await searchInputs.count();
  console.log(`Found ${count} search/text inputs`);

  if (count > 0) {
    const searchInput = searchInputs.first();
    const placeholder = await searchInput.getAttribute('placeholder');
    console.log(`Using input with placeholder: "${placeholder}"`);

    // Take screenshot of page
    await page.screenshot({ path: 'search-page-view.png', fullPage: true });
    console.log('✓ Screenshot: search-page-view.png');

    // Focus on the input to see the styling
    await searchInput.click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'search-focused-view.png', fullPage: true });
    console.log('✓ Screenshot: search-focused-view.png');
  }

  // Try to navigate to workflows view by clicking breadcrumb or nav
  try {
    const workflowsNav = page.locator('a[data-view], .nav-link').filter({ hasText: /workflow/i }).first();
    if (await workflowsNav.count() > 0) {
      await workflowsNav.click();
      await page.waitForTimeout(1000);

      const searchInputs2 = page.locator('input[type="text"]');
      if (await searchInputs2.count() > 0) {
        await page.screenshot({ path: 'workflows-page-search.png', fullPage: true });
        console.log('✓ Screenshot: workflows-page-search.png');

        const input = searchInputs2.first();
        await input.click();
        await page.waitForTimeout(500);
        await page.screenshot({ path: 'workflows-page-search-focused.png', fullPage: true });
        console.log('✓ Screenshot: workflows-page-search-focused.png');
      }
    }
  } catch (e) {
    console.log('Could not navigate to workflows view:', e.message);
  }

  console.log('\n✅ Screenshots captured. Keeping browser open...');
  await page.waitForTimeout(30000);
  await browser.close();
})();
