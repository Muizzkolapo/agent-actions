const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  await page.goto('http://localhost:8890/#/workflows');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  // Find ALL inputs on the page
  const allInputs = page.locator('input');
  const count = await allInputs.count();
  console.log(`\nFound ${count} input elements:`);

  for (let i = 0; i < count; i++) {
    const input = allInputs.nth(i);
    const type = await input.getAttribute('type');
    const placeholder = await input.getAttribute('placeholder');
    const id = await input.getAttribute('id');
    const classes = await input.getAttribute('class');

    console.log(`\n${i + 1}. Input:`);
    console.log(`   Type: ${type}`);
    console.log(`   ID: ${id}`);
    console.log(`   Class: ${classes}`);
    console.log(`   Placeholder: ${placeholder}`);
  }

  // Look for the one with magnifying glass icon
  const searchWithIcon = page.locator('.filter-search, .search-box-enhanced, [class*="search"]').filter({ has: page.locator('svg') });
  const iconCount = await searchWithIcon.count();
  console.log(`\n\nFound ${iconCount} search containers with icons`);

  if (iconCount > 0) {
    for (let i = 0; i < iconCount; i++) {
      const container = searchWithIcon.nth(i);
      const classes = await container.getAttribute('class');
      console.log(`${i + 1}. Container class: ${classes}`);
    }
  }

  await page.waitForTimeout(30000);
  await browser.close();
})();
