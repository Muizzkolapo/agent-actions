const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });
  const page = await context.newPage();

  console.log('📂 Navigating to localhost:8890...');
  await page.goto('http://localhost:8890');

  // Wait for page to load
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  console.log('📸 Taking screenshot - Home page');
  await page.screenshot({ path: 'prompts-test-home.png', fullPage: true });

  // Click on PROMPTS in sidebar
  console.log('🔘 Clicking on PROMPTS navigation...');
  const promptsNav = await page.locator('.nav-header[data-section="prompts"]').first();

  if (await promptsNav.count() > 0) {
    await promptsNav.click();
    await page.waitForTimeout(1500); // Wait for navigation

    console.log('📸 Taking screenshot - All Prompts page');
    await page.screenshot({ path: 'prompts-test-list.png', fullPage: true });

    // Check how many prompt cards are displayed
    const promptCards = await page.locator('.workflow-card').all();
    console.log(`\n📊 PROMPTS PAGE ANALYSIS:`);
    console.log(`Total prompt cards displayed: ${promptCards.length}`);

    // Check the subtitle text
    const subtitle = await page.locator('#prompts-list-subtitle').textContent();
    console.log(`Subtitle text: "${subtitle}"`);

    // Get first prompt card details
    if (promptCards.length > 0) {
      const firstCard = promptCards[0];
      const cardTitle = await firstCard.locator('h3').textContent();
      const cardPreview = await firstCard.locator('.workflow-description').textContent();

      console.log(`\nFirst prompt card:`);
      console.log(`  Title: ${cardTitle}`);
      console.log(`  Preview: ${cardPreview.substring(0, 80)}...`);

      // Click on first prompt to see detail view
      console.log('\n🔘 Clicking on first prompt card...');
      await firstCard.click();
      await page.waitForTimeout(1500);

      console.log('📸 Taking screenshot - Prompt detail view');
      await page.screenshot({ path: 'prompts-test-detail.png', fullPage: true });

      // Check prompt detail page elements
      const hasContent = await page.locator('.prompt-content, .schema-content, pre, code').count() > 0;
      console.log(`\nPrompt detail page has content: ${hasContent}`);
    }

    console.log('\n✅ SUMMARY:');
    if (promptCards.length === 22) {
      console.log('   ✓ All 22 prompts are displayed correctly');
    } else {
      console.log(`   ⚠️  Expected 22 prompts, found ${promptCards.length}`);
    }

  } else {
    console.log('❌ Prompts navigation not found!');
  }

  console.log('\n✅ Screenshots saved:');
  console.log('   - prompts-test-home.png');
  console.log('   - prompts-test-list.png');
  console.log('   - prompts-test-detail.png');

  await page.waitForTimeout(3000);
  await browser.close();
})();
