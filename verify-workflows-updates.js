const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  await page.goto('http://localhost:8890/#/workflows');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  console.log('✓ Loaded workflows page\n');

  // Take default screenshot
  await page.screenshot({ path: 'workflows-default.png', fullPage: true });
  console.log('✓ Screenshot: workflows-default.png');

  // Test: Workflow card styling
  console.log('\n=== Testing Workflow Cards ===');

  const workflowCard = page.locator('.workflow-card').first();

  // Default state
  await page.screenshot({ path: 'workflows-cards-default.png', fullPage: true });
  console.log('✓ Screenshot: workflows-cards-default.png');

  // Hover state
  await workflowCard.hover();
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'workflows-cards-hover.png', fullPage: true });
  console.log('✓ Screenshot: workflows-cards-hover.png');

  // Check workflow card styles
  const cardStyles = await workflowCard.evaluate(el => {
    const computed = window.getComputedStyle(el);
    return {
      background: computed.background,
      border: computed.border,
      borderRadius: computed.borderRadius,
      boxShadow: computed.boxShadow,
      transform: computed.transform,
      padding: computed.padding
    };
  });
  console.log('\nWorkflow card hover styles:');
  console.log(JSON.stringify(cardStyles, null, 2));

  console.log('\n✅ Verification complete! Review screenshots to confirm styling.');
  console.log('Browser will stay open for 30 seconds for manual inspection...');

  await page.waitForTimeout(30000);
  await browser.close();
})();
