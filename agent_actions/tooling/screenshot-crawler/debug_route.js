const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
    const browser = await chromium.launch();
    const page = await browser.newPage();

    const TARGET = 'http://localhost:8000/#/actions';
    console.log(`Navigating to ${TARGET}...`);
    await page.goto(TARGET, { waitUntil: 'domcontentloaded' });

    console.log('Waiting for network idle...');
    await page.waitForTimeout(5000); // Give it time to settle

    // Save Screenshot
    await page.screenshot({ path: 'debug_actions.png', fullPage: true });
    console.log('Saved debug_actions.png');

    // Dump current URL to see if it redirected
    console.log('Current URL:', page.url());

    await browser.close();
})();
