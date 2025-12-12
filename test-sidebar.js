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

  console.log('📸 Taking screenshot - Sidebar OPEN');
  await page.screenshot({ path: 'sidebar-open.png', fullPage: true });

  // Find and click the sidebar toggle button
  console.log('🔘 Looking for sidebar toggle button...');
  const toggleButton = await page.locator('button[aria-label="Toggle sidebar"], .sidebar-toggle, button:has-text("☰")').first();

  if (await toggleButton.count() > 0) {
    console.log('✅ Found toggle button, clicking...');
    await toggleButton.click();
    await page.waitForTimeout(1000); // Wait for animation

    console.log('📸 Taking screenshot - Sidebar CLOSED');
    await page.screenshot({ path: 'sidebar-closed.png', fullPage: true });

    console.log('🔍 Analyzing sidebar state...');

    // Get sidebar width when collapsed
    const sidebar = await page.locator('.sidebar').first();
    const sidebarBox = await sidebar.boundingBox();

    console.log('\n📊 SIDEBAR ANALYSIS:');
    console.log('Width when collapsed:', sidebarBox?.width, 'px');

    // Check if sidebar has collapsed class
    const hasCollapsed = await sidebar.evaluate(el => el.classList.contains('collapsed'));
    console.log('Has "collapsed" class:', hasCollapsed);

    // Get computed styles
    const styles = await sidebar.evaluate(el => {
      const computed = window.getComputedStyle(el);
      return {
        width: computed.width,
        padding: computed.padding,
        overflow: computed.overflow,
        transition: computed.transition
      };
    });
    console.log('Computed styles:', styles);

    // Check main content margin
    const mainContent = await page.locator('.main-content').first();
    const mainContentStyles = await mainContent.evaluate(el => {
      const computed = window.getComputedStyle(el);
      return {
        marginLeft: computed.marginLeft
      };
    });
    console.log('Main content margin-left:', mainContentStyles.marginLeft);

    // Check if any text is visible in collapsed sidebar
    const sidebarText = await sidebar.locator('text=OVERVIEW, text=WORKFLOWS, text=PROMPTS').first();
    const textVisible = await sidebarText.isVisible().catch(() => false);
    console.log('Sidebar text still visible:', textVisible);

    console.log('\n⚠️  ISSUES TO INVESTIGATE:');
    console.log('1. Check if width is appropriate for collapsed state');
    console.log('2. Check if text/labels are properly hidden');
    console.log('3. Check if icons are centered when collapsed');
    console.log('4. Check if transition is smooth');
    console.log('5. Check main content positioning');

  } else {
    console.log('❌ Toggle button not found!');
  }

  console.log('\n✅ Screenshots saved:');
  console.log('   - sidebar-open.png');
  console.log('   - sidebar-closed.png');

  await page.waitForTimeout(3000);
  await browser.close();
})();
