const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  // Go directly to the workflows page
  await page.goto('http://localhost:8890/#/workflows');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  console.log('✓ Loaded workflows page');

  // Take screenshot of default state
  await page.screenshot({ path: 'workflows-search-default.png', fullPage: true });
  console.log('✓ Screenshot: workflows-search-default.png');

  // Find the search input
  const searchInput = page.locator('input[placeholder*="search" i], input[type="text"]').first();
  const placeholder = await searchInput.getAttribute('placeholder');
  console.log(`\nFound search input: "${placeholder}"`);

  // Check the classes and styling
  const classes = await searchInput.getAttribute('class');
  const parentClasses = await searchInput.locator('..').getAttribute('class');
  console.log(`Input classes: ${classes}`);
  console.log(`Parent classes: ${parentClasses}`);

  // Hover over search
  await searchInput.hover();
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'workflows-search-hover.png', fullPage: true });
  console.log('✓ Screenshot: workflows-search-hover.png');

  // Focus on search
  await searchInput.click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'workflows-search-focused.png', fullPage: true });
  console.log('✓ Screenshot: workflows-search-focused.png');

  // Check computed styles
  const styles = await searchInput.evaluate(el => {
    const computed = window.getComputedStyle(el);
    const parent = el.parentElement;
    const icon = parent.querySelector('svg');
    let iconStyles = null;
    if (icon) {
      const iconComputed = window.getComputedStyle(icon);
      iconStyles = {
        color: iconComputed.color,
        position: iconComputed.position,
        left: iconComputed.left
      };
    }
    return {
      input: {
        padding: computed.padding,
        paddingLeft: computed.paddingLeft,
        border: computed.border,
        borderRadius: computed.borderRadius,
        boxShadow: computed.boxShadow,
        background: computed.background
      },
      icon: iconStyles
    };
  });

  console.log('\nComputed styles:');
  console.log(JSON.stringify(styles, null, 2));

  console.log('\n✅ Review complete! Browser staying open for inspection...');
  await page.waitForTimeout(60000);
  await browser.close();
})();
