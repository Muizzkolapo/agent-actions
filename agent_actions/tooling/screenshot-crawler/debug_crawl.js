const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
    const browser = await chromium.launch();
    const page = await browser.newPage();
    
    console.log('Navigating to http://localhost:8000...');
    await page.goto('http://localhost:8000', { waitUntil: 'domcontentloaded' });
    
    console.log('Waiting for network idle...');
    try {
        await page.waitForLoadState('networkidle', { timeout: 10000 });
    } catch (e) {
        console.log('Network idle timeout (might be polling), proceeding...');
    }

    console.log('Waiting explicit 5 seconds for rendering...');
    await page.waitForTimeout(5000);

    // Save Screenshot
    await page.screenshot({ path: 'debug_screenshot.png', fullPage: true });
    console.log('Saved debug_screenshot.png');

    // Save HTML
    const html = await page.content();
    fs.writeFileSync('debug.html', html);
    console.log('Saved debug.html');

    // Inspect Links
    const links = await page.$$eval('a', anchors => anchors.map(a => a.href));
    console.log('Found links:', links);

    await browser.close();
})();
