const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

// Configuration
const BASE_URL = 'http://localhost:8000';
const OUTPUT_DIR = path.join(__dirname, 'screenshots');

// State management
const visited = new Set();
const BASE_ORIGIN = new URL(BASE_URL).origin;

// Seed known routes - the app uses hash-based routing
const queue = [
    BASE_URL,
    `${BASE_URL}/#/actions`,
    `${BASE_URL}/#/workflows`,
    `${BASE_URL}/#/prompts`,
    `${BASE_URL}/#/schemas`,
    `${BASE_URL}/#/runs`
];

/**
 * Helper to sanitize URL paths for filenames
 */
function getFileName(urlStr) {
    try {
        const url = new URL(urlStr);
        // Extract meaningful route from hash
        let hash = url.hash || '';
        if (hash.startsWith('#/')) {
            hash = hash.substring(2); // Remove #/
        } else if (hash.startsWith('#')) {
            hash = hash.substring(1); // Remove #
        }

        // Replace slashes and special chars
        let route = hash.replace(/\//g, '_').replace(/[^a-zA-Z0-9_-]/g, '_');
        route = route.replace(/^_+|_+$/g, '').replace(/_+/g, '_');
        if (!route) route = 'home';
        return `${route}.png`;
    } catch (e) {
        return `unknown_${Date.now()}.png`;
    }
}

/**
 * Navigate to a hash-based route properly
 * Hash routing requires the page to be loaded first, then hash change triggered
 */
async function navigateToHash(page, urlStr) {
    const url = new URL(urlStr);
    const hash = url.hash;

    // If no hash, just navigate normally
    if (!hash || hash === '#' || hash === '#/') {
        await page.goto(urlStr, { waitUntil: 'domcontentloaded' });
        return;
    }

    // For hash routes, we need to:
    // 1. Go to base URL first (if not already there)
    // 2. Then trigger hash navigation via JavaScript
    const currentUrl = page.url();
    const currentOrigin = new URL(currentUrl).origin;

    if (currentOrigin !== url.origin || !currentUrl.includes(url.origin)) {
        await page.goto(url.origin, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(1000);
    }

    // Trigger hash navigation
    await page.evaluate((newHash) => {
        window.location.hash = newHash;
    }, hash);
}

(async () => {
    if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

    const browser = await chromium.launch({ headless: true });
    // Set a consistent viewport for proper layout
    const context = await browser.newContext({
        viewport: { width: 1440, height: 900 }
    });
    const page = await context.newPage();

    console.log(`Starting crawl on ${BASE_URL}`);

    while (queue.length > 0) {
        const currentUrl = queue.shift();

        if (visited.has(currentUrl)) continue;
        visited.add(currentUrl);

        try {
            console.log(`Navigating to: ${currentUrl}`);
            await navigateToHash(page, currentUrl);

            // Wait for content to render after hash change
            try {
                await page.waitForLoadState('networkidle', { timeout: 5000 });
            } catch (e) { }
            await page.waitForTimeout(2000); // Wait for hash routing + render

            // Scroll to top before screenshot
            await page.evaluate(() => window.scrollTo(0, 0));
            await page.waitForTimeout(500);

            const filename = getFileName(currentUrl);
            await page.screenshot({
                path: path.join(OUTPUT_DIR, filename),
                fullPage: true
            });
            console.log(`Saved: ${filename}`);

            // Link Discovery - look for hash-based links
            const hrefs = await page.$$eval('a', anchors => anchors.map(a => a.href));
            for (const href of hrefs) {
                try {
                    const cleanUrl = new URL(href);
                    if (cleanUrl.origin === BASE_ORIGIN) {
                        const nextUrl = cleanUrl.href;
                        if (!visited.has(nextUrl) && !queue.includes(nextUrl)) {
                            queue.push(nextUrl);
                        }
                    }
                } catch (err) { }
            }

            // Also discover hash links from onclick handlers or data attributes
            const hashRoutes = await page.$$eval('[href^="#"], [data-route]', els =>
                els.map(el => el.getAttribute('href') || el.getAttribute('data-route')).filter(Boolean)
            );
            for (const route of hashRoutes) {
                if (route.startsWith('#')) {
                    const nextUrl = `${BASE_ORIGIN}/${route}`;
                    if (!visited.has(nextUrl) && !queue.includes(nextUrl)) {
                        queue.push(nextUrl);
                    }
                }
            }

        } catch (error) {
            console.error(`Error processing ${currentUrl}:`, error.message);
        }
    }

    console.log('Crawl complete.');
    await browser.close();
})();