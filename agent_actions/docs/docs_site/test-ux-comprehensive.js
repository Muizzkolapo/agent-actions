/**
 * Comprehensive UX Audit for Agent Actions Docs Site
 *
 * This provides a detailed UI/UX assessment including:
 * - Visual design consistency
 * - User experience patterns
 * - Missing features for production readiness
 * - Accessibility and usability
 * - Information architecture
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:8890';
const SCREENSHOTS_DIR = './ux-comprehensive-screenshots';
const REPORT_FILE = './UX_PRODUCTION_READINESS.md';

const ROUTES_TO_TEST = [
    { url: '/#/', name: 'Home/Dashboard', type: 'dashboard' },
    { url: '/#/workflows', name: 'All Workflows', type: 'list' },
    { url: '/#/actions', name: 'All Actions', type: 'list' },
    { url: '/#/actions/llm', name: 'LLM Actions Filter', type: 'filtered-list' },
    { url: '/#/actions/tool', name: 'Tool Actions Filter', type: 'filtered-list' },
    { url: '/#/prompts', name: 'All Prompts', type: 'list' },
    { url: '/#/schemas', name: 'All Schemas', type: 'list' },
    { url: '/#/runs', name: 'All Runs', type: 'list' },
    { url: '/#/observability', name: 'Observability Dashboard', type: 'dashboard' },
];

if (!fs.existsSync(SCREENSHOTS_DIR)) {
    fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

const uxFindings = [];

async function comprehensivePageAnalysis(page, route) {
    const { url, name, type } = route;
    const fullUrl = BASE_URL + url;

    const findings = {
        route: url,
        name,
        type,
        timestamp: new Date().toISOString(),

        // Visual Design
        visualDesign: {
            issues: [],
            improvements: [],
            score: 0
        },

        // User Experience
        userExperience: {
            issues: [],
            improvements: [],
            score: 0
        },

        // Content & Information Architecture
        contentIA: {
            issues: [],
            improvements: [],
            score: 0
        },

        // Functionality
        functionality: {
            issues: [],
            improvements: [],
            score: 0
        },

        // Accessibility
        accessibility: {
            issues: [],
            improvements: [],
            score: 0
        },

        // Production Readiness
        productionReadiness: {
            blockers: [],
            recommended: [],
            niceToHave: []
        }
    };

    try {
        // === VISUAL DESIGN CHECKS ===

        // Check for loading states
        const loadingElements = await page.$$('.loading, .spinner, [aria-busy="true"]');
        if (loadingElements.length > 0) {
            findings.visualDesign.issues.push('Persistent loading indicators detected');
        }

        // Check for empty states
        const emptyStateMessage = await page.$('.empty-state-message, [class*="empty"]');
        if (!emptyStateMessage && type === 'list') {
            findings.visualDesign.improvements.push('Add empty state illustrations/messages for better UX when no data');
        }

        // Check for consistent spacing
        const pageHeader = await page.$('.page-header');
        if (!pageHeader) {
            findings.visualDesign.issues.push('Missing consistent page header structure');
        }

        // Check for visual hierarchy
        const headings = await page.$$eval('h1, h2, h3, h4, h5, h6', els =>
            els.map(el => ({ tag: el.tagName, text: el.textContent?.trim() }))
        );

        if (headings.length === 0) {
            findings.contentIA.issues.push('No heading structure - poor information hierarchy');
        }

        const h1Count = headings.filter(h => h.tag === 'H1').length;
        if (h1Count === 0) {
            findings.contentIA.issues.push('Missing H1 heading - poor SEO and accessibility');
        } else if (h1Count > 1) {
            findings.accessibility.issues.push(`Multiple H1 headings (${h1Count}) - should have exactly one per page`);
        }

        // Check for color contrast (basic check)
        const buttons = await page.$$('button:not([style*="display: none"])');
        if (buttons.length > 0) {
            findings.visualDesign.improvements.push('Consider adding hover states and focus indicators for all interactive elements');
        }

        // === USER EXPERIENCE CHECKS ===

        // Check for breadcrumb navigation
        const breadcrumbs = await page.$('.breadcrumb, nav[aria-label*="breadcrumb"]');
        if (!breadcrumbs && url !== '/#/') {
            findings.userExperience.improvements.push('Add breadcrumb navigation for easier navigation context');
        }

        // Check for back/navigation buttons on detail pages
        if (url.includes('/workflow/') || url.includes('/action/') || url.includes('/run/')) {
            const backButton = await page.$('button[aria-label*="back"], button[aria-label*="Back"]');
            if (!backButton) {
                findings.userExperience.issues.push('Missing back button on detail view');
            }
        }

        // Check for tooltips/help text
        const helpIcons = await page.$$('[aria-label*="help"], [title*="help"], .tooltip');
        if (helpIcons.length === 0) {
            findings.userExperience.improvements.push('Add tooltips/help text for complex features');
        }

        // Check for keyboard navigation
        const focusableElements = await page.$$('a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
        findings.accessibility.improvements.push(`Ensure all ${focusableElements.length} interactive elements have proper keyboard navigation`);

        // === FUNCTIONALITY CHECKS ===

        if (type === 'list' || type === 'filtered-list') {
            // Check for search functionality
            const searchInput = await page.$('input[id*="search"], input[placeholder*="Search"]');
            if (!searchInput) {
                findings.functionality.issues.push('Missing search functionality on list view');
                findings.productionReadiness.blockers.push('Implement search functionality');
            }

            // Check for filters
            const filterButton = await page.$('.filter-button, button[id*="filter"]');
            const hasVisibleFilter = filterButton ? await filterButton.isVisible() : false;

            // Check for sort
            const sortButton = await page.$('.sort-button, button[id*="sort"]');
            if (!sortButton) {
                findings.functionality.issues.push('Missing sort functionality on list view');
                findings.productionReadiness.blockers.push('Implement sort functionality');
            }

            // Check for view toggle
            const viewToggle = await page.$('.view-toggle');
            if (!viewToggle) {
                findings.functionality.improvements.push('Add grid/list view toggle for better user preference');
            }

            // Check for pagination or infinite scroll
            const pagination = await page.$('.pagination, nav[aria-label*="pagination"]');
            if (!pagination) {
                findings.functionality.improvements.push('Consider adding pagination for large datasets');
            }

            // Check for bulk actions
            const checkboxes = await page.$$('input[type="checkbox"]');
            if (checkboxes.length === 0) {
                findings.functionality.improvements.push('Consider adding bulk selection/actions for power users');
            }

            // Check for export functionality
            const exportButton = await page.$('button[aria-label*="export"], button[aria-label*="download"]');
            if (!exportButton) {
                findings.productionReadiness.recommended.push('Add export/download functionality for data');
            }
        }

        if (type === 'dashboard') {
            // Check for stats/metrics cards
            const statsCards = await page.$$('.stat-card, .metric-card');
            if (statsCards.length === 0) {
                findings.functionality.issues.push('Dashboard missing statistics/metrics cards');
            } else {
                findings.functionality.improvements.push(`Dashboard has ${statsCards.length} metric cards - consider adding real-time updates`);
            }

            // Check for charts/visualizations
            const charts = await page.$$('canvas, svg[class*="chart"], .chart');
            if (charts.length === 0) {
                findings.productionReadiness.recommended.push('Add data visualizations/charts for better insights');
            }

            // Check for refresh button
            const refreshButton = await page.$('button[aria-label*="refresh"], button[aria-label*="Refresh"]');
            if (!refreshButton) {
                findings.functionality.improvements.push('Add refresh button for real-time data updates');
            }
        }

        // === CONTENT & INFORMATION ARCHITECTURE ===

        // Check page title
        const pageTitle = await page.title();
        if (!pageTitle || pageTitle === '' || pageTitle === 'Document') {
            findings.contentIA.issues.push('Missing or generic page title - important for SEO and browser tabs');
        } else if (pageTitle === 'QanaLabs Workflows' && !url.includes('workflow')) {
            findings.contentIA.issues.push(`Page title "${pageTitle}" doesn't match current page (${name})`);
        }

        // Check for descriptive text
        const subtitle = await page.$('.subtitle, .page-subtitle, p[class*="subtitle"]');
        if (!subtitle && type !== 'detail') {
            findings.contentIA.improvements.push('Add descriptive subtitle/intro text to explain page purpose');
        }

        // Check for action buttons
        const primaryActions = await page.$$('button.primary, button[class*="primary"], .btn-primary');
        if (primaryActions.length === 0 && type === 'list') {
            findings.userExperience.improvements.push('Consider adding primary action button (e.g., "Create New", "Import")');
        }

        // === ACCESSIBILITY CHECKS ===

        // Check for alt text on images
        const images = await page.$$('img');
        for (const img of images) {
            const alt = await img.getAttribute('alt');
            const src = await img.getAttribute('src');
            if (!alt && src) {
                findings.accessibility.issues.push(`Image missing alt text: ${src}`);
            }
        }

        // Check for ARIA labels
        const buttonsWithoutLabel = await page.$$('button:not([aria-label]):not([aria-labelledby])');
        const buttonsWithoutText = [];
        for (const btn of buttonsWithoutLabel) {
            const text = await btn.textContent();
            const ariaLabel = await btn.getAttribute('aria-label');
            if (!text?.trim() && !ariaLabel) {
                buttonsWithoutText.push('button without text or aria-label');
            }
        }
        if (buttonsWithoutText.length > 0) {
            findings.accessibility.issues.push(`${buttonsWithoutText.length} buttons without accessible labels`);
        }

        // Check for form labels
        const inputs = await page.$$('input:not([type="hidden"])');
        for (const input of inputs) {
            const id = await input.getAttribute('id');
            const ariaLabel = await input.getAttribute('aria-label');
            const placeholder = await input.getAttribute('placeholder');

            if (id) {
                const label = await page.$(`label[for="${id}"]`);
                if (!label && !ariaLabel) {
                    findings.accessibility.issues.push(`Input field missing label (id: ${id})`);
                }
            }
        }

        // === PRODUCTION READINESS CHECKS ===

        // Check for error handling
        const errorMessages = await page.$$('.error-message, [role="alert"]');
        if (errorMessages.length > 0) {
            const errorTexts = await Promise.all(errorMessages.map(el => el.textContent()));
            findings.productionReadiness.blockers.push(`Active error messages found: ${errorTexts.join(', ')}`);
        }

        // Check for 404/broken links
        const links = await page.$$('a[href]');
        const brokenLinks = [];
        for (const link of links.slice(0, 20)) { // Check first 20 links
            const href = await link.getAttribute('href');
            if (href && (href.includes('undefined') || href.includes('null'))) {
                brokenLinks.push(href);
            }
        }
        if (brokenLinks.length > 0) {
            findings.productionReadiness.blockers.push(`Broken links detected: ${brokenLinks.join(', ')}`);
        }

        // Check for responsive design indicators
        const viewport = page.viewportSize();
        findings.productionReadiness.recommended.push(`Test responsive design on mobile (current: ${viewport.width}x${viewport.height})`);

        // Check for loading performance
        findings.productionReadiness.recommended.push('Run Lighthouse audit for performance metrics');
        findings.productionReadiness.recommended.push('Add loading skeletons/placeholders for better perceived performance');

        // Check for security best practices
        findings.productionReadiness.recommended.push('Implement CSP (Content Security Policy) headers');
        findings.productionReadiness.recommended.push('Add HTTPS enforcement');

        // === NICE TO HAVE FEATURES ===

        findings.productionReadiness.niceToHave.push('Add dark mode toggle');
        findings.productionReadiness.niceToHave.push('Add keyboard shortcuts (e.g., "/" for search)');
        findings.productionReadiness.niceToHave.push('Add recent/favorite items quick access');
        findings.productionReadiness.niceToHave.push('Add onboarding tour for first-time users');
        findings.productionReadiness.niceToHave.push('Add contextual help system');
        findings.productionReadiness.niceToHave.push('Implement progressive web app (PWA) features');
        findings.productionReadiness.niceToHave.push('Add analytics/usage tracking');

        // Calculate scores (0-100)
        findings.visualDesign.score = Math.max(0, 100 - (findings.visualDesign.issues.length * 15 + findings.visualDesign.improvements.length * 5));
        findings.userExperience.score = Math.max(0, 100 - (findings.userExperience.issues.length * 15 + findings.userExperience.improvements.length * 5));
        findings.contentIA.score = Math.max(0, 100 - (findings.contentIA.issues.length * 15 + findings.contentIA.improvements.length * 5));
        findings.functionality.score = Math.max(0, 100 - (findings.functionality.issues.length * 15 + findings.functionality.improvements.length * 5));
        findings.accessibility.score = Math.max(0, 100 - (findings.accessibility.issues.length * 15 + findings.accessibility.improvements.length * 5));

        findings.overallScore = Math.round(
            (findings.visualDesign.score + findings.userExperience.score + findings.contentIA.score +
             findings.functionality.score + findings.accessibility.score) / 5
        );

        // Take screenshots
        const screenshotName = url.replace(/[^a-zA-Z0-9]/g, '_') + '.png';
        const screenshotPath = path.join(SCREENSHOTS_DIR, screenshotName);
        await page.screenshot({ path: screenshotPath, fullPage: true });
        findings.screenshot = screenshotPath;

    } catch (error) {
        findings.error = error.message;
        findings.productionReadiness.blockers.push(`Page failed to load: ${error.message}`);
    }

    return findings;
}

function generateComprehensiveReport() {
    let md = `# UI/UX Production Readiness Report\n## Agent Actions Documentation Site\n\n`;
    md += `**Generated:** ${new Date().toLocaleString()}\n`;
    md += `**Pages Analyzed:** ${uxFindings.length}\n`;
    md += `**Base URL:** ${BASE_URL}\n\n`;

    // Calculate overall readiness score
    const avgScore = Math.round(uxFindings.reduce((sum, f) => sum + f.overallScore, 0) / uxFindings.length);
    const readinessLevel = avgScore >= 85 ? '🟢 Production Ready' :
                          avgScore >= 70 ? '🟡 Needs Improvements' :
                          avgScore >= 50 ? '🟠 Significant Work Needed' :
                          '🔴 Not Ready for Production';

    md += `**Overall Readiness Score:** ${avgScore}/100 - ${readinessLevel}\n\n`;
    md += `---\n\n`;

    // Executive Summary
    md += `## 📊 Executive Summary\n\n`;

    const allBlockers = uxFindings.flatMap(f => f.productionReadiness.blockers);
    const allRecommended = [...new Set(uxFindings.flatMap(f => f.productionReadiness.recommended))];
    const allNiceToHave = [...new Set(uxFindings.flatMap(f => f.productionReadiness.niceToHave))];

    md += `### Critical Blockers (Must Fix Before Production)\n`;
    md += `**Count:** ${allBlockers.length}\n\n`;
    if (allBlockers.length > 0) {
        allBlockers.forEach((blocker, i) => {
            md += `${i + 1}. ${blocker}\n`;
        });
    } else {
        md += `✅ No critical blockers found!\n`;
    }
    md += `\n`;

    md += `### Recommended Improvements (Should Have)\n`;
    md += `**Count:** ${allRecommended.length}\n\n`;
    allRecommended.slice(0, 10).forEach((rec, i) => {
        md += `${i + 1}. ${rec}\n`;
    });
    md += `\n`;

    md += `### Nice to Have Features (Future Enhancements)\n`;
    md += `**Count:** ${allNiceToHave.length}\n\n`;
    allNiceToHave.slice(0, 10).forEach((nice, i) => {
        md += `${i + 1}. ${nice}\n`;
    });
    md += `\n---\n\n`;

    // Prioritized Task Table
    md += `## 📋 Prioritized Task List\n\n`;
    md += `| Priority | Category | Task | Affected Pages | Effort | Impact | Status |\n`;
    md += `|----------|----------|------|----------------|--------|--------|--------|\n`;

    const tasks = [];

    // Collect all tasks
    uxFindings.forEach(finding => {
        const pageName = finding.name;

        // Critical issues
        finding.productionReadiness.blockers.forEach(blocker => {
            tasks.push({
                priority: 1,
                priorityLabel: '🔴 Critical',
                category: 'Blocker',
                task: blocker,
                pages: [pageName],
                effort: 'High',
                impact: 'Critical'
            });
        });

        // Functionality issues
        finding.functionality.issues.forEach(issue => {
            tasks.push({
                priority: 2,
                priorityLabel: '🟠 High',
                category: 'Functionality',
                task: issue,
                pages: [pageName],
                effort: 'Medium',
                impact: 'High'
            });
        });

        // Accessibility issues
        finding.accessibility.issues.forEach(issue => {
            tasks.push({
                priority: 3,
                priorityLabel: '🟡 Medium',
                category: 'Accessibility',
                task: issue,
                pages: [pageName],
                effort: 'Low',
                impact: 'Medium'
            });
        });

        // UX improvements
        finding.userExperience.improvements.forEach(improvement => {
            tasks.push({
                priority: 4,
                priorityLabel: '🟢 Low',
                category: 'UX Enhancement',
                task: improvement,
                pages: [pageName],
                effort: 'Medium',
                impact: 'Medium'
            });
        });
    });

    // Deduplicate and group tasks
    const groupedTasks = {};
    tasks.forEach(task => {
        const key = `${task.category}:${task.task}`;
        if (groupedTasks[key]) {
            groupedTasks[key].pages.push(...task.pages);
        } else {
            groupedTasks[key] = task;
        }
    });

    // Sort by priority and output
    Object.values(groupedTasks)
        .sort((a, b) => a.priority - b.priority)
        .forEach(task => {
            const pages = [...new Set(task.pages)].join(', ');
            md += `| ${task.priorityLabel} | ${task.category} | ${task.task} | ${pages} | ${task.effort} | ${task.impact} | ⬜ Todo |\n`;
        });

    md += `\n---\n\n`;

    // Score Cards by Page
    md += `## 🎯 Score Cards by Page\n\n`;
    md += `| Page | Overall | Visual | UX | Content | Functionality | Accessibility |\n`;
    md += `|------|---------|--------|----|---------|--------------|--------------|\n`;

    uxFindings.forEach(finding => {
        md += `| ${finding.name} | **${finding.overallScore}** | `;
        md += `${finding.visualDesign.score} | `;
        md += `${finding.userExperience.score} | `;
        md += `${finding.contentIA.score} | `;
        md += `${finding.functionality.score} | `;
        md += `${finding.accessibility.score} |\n`;
    });

    md += `\n---\n\n`;

    // Detailed findings by page
    md += `## 📝 Detailed Findings by Page\n\n`;

    uxFindings.forEach(finding => {
        md += `### ${finding.name} (${finding.route})\n\n`;
        md += `**Overall Score:** ${finding.overallScore}/100\n`;
        md += `**Page Type:** ${finding.type}\n`;
        md += `**Screenshot:** \`${finding.screenshot}\`\n\n`;

        if (finding.error) {
            md += `⚠️ **ERROR:** ${finding.error}\n\n`;
        }

        // Visual Design
        if (finding.visualDesign.issues.length > 0 || finding.visualDesign.improvements.length > 0) {
            md += `#### Visual Design (Score: ${finding.visualDesign.score}/100)\n`;
            if (finding.visualDesign.issues.length > 0) {
                md += `**Issues:**\n`;
                finding.visualDesign.issues.forEach(issue => md += `- ❌ ${issue}\n`);
            }
            if (finding.visualDesign.improvements.length > 0) {
                md += `**Improvements:**\n`;
                finding.visualDesign.improvements.forEach(imp => md += `- 💡 ${imp}\n`);
            }
            md += `\n`;
        }

        // User Experience
        if (finding.userExperience.issues.length > 0 || finding.userExperience.improvements.length > 0) {
            md += `#### User Experience (Score: ${finding.userExperience.score}/100)\n`;
            if (finding.userExperience.issues.length > 0) {
                md += `**Issues:**\n`;
                finding.userExperience.issues.forEach(issue => md += `- ❌ ${issue}\n`);
            }
            if (finding.userExperience.improvements.length > 0) {
                md += `**Improvements:**\n`;
                finding.userExperience.improvements.forEach(imp => md += `- 💡 ${imp}\n`);
            }
            md += `\n`;
        }

        // Content & IA
        if (finding.contentIA.issues.length > 0 || finding.contentIA.improvements.length > 0) {
            md += `#### Content & Information Architecture (Score: ${finding.contentIA.score}/100)\n`;
            if (finding.contentIA.issues.length > 0) {
                md += `**Issues:**\n`;
                finding.contentIA.issues.forEach(issue => md += `- ❌ ${issue}\n`);
            }
            if (finding.contentIA.improvements.length > 0) {
                md += `**Improvements:**\n`;
                finding.contentIA.improvements.forEach(imp => md += `- 💡 ${imp}\n`);
            }
            md += `\n`;
        }

        // Functionality
        if (finding.functionality.issues.length > 0 || finding.functionality.improvements.length > 0) {
            md += `#### Functionality (Score: ${finding.functionality.score}/100)\n`;
            if (finding.functionality.issues.length > 0) {
                md += `**Issues:**\n`;
                finding.functionality.issues.forEach(issue => md += `- ❌ ${issue}\n`);
            }
            if (finding.functionality.improvements.length > 0) {
                md += `**Improvements:**\n`;
                finding.functionality.improvements.forEach(imp => md += `- 💡 ${imp}\n`);
            }
            md += `\n`;
        }

        // Accessibility
        if (finding.accessibility.issues.length > 0 || finding.accessibility.improvements.length > 0) {
            md += `#### Accessibility (Score: ${finding.accessibility.score}/100)\n`;
            if (finding.accessibility.issues.length > 0) {
                md += `**Issues:**\n`;
                finding.accessibility.issues.forEach(issue => md += `- ❌ ${issue}\n`);
            }
            if (finding.accessibility.improvements.length > 0) {
                md += `**Improvements:**\n`;
                finding.accessibility.improvements.forEach(imp => md += `- 💡 ${imp}\n`);
            }
            md += `\n`;
        }

        md += `---\n\n`;
    });

    // Recommendations
    md += `## 🚀 Recommended Implementation Roadmap\n\n`;
    md += `### Phase 1: Critical Fixes (Before Production)\n`;
    md += `**Timeline:** Immediate (1-2 weeks)\n\n`;
    md += `1. Fix all page title issues\n`;
    md += `2. Resolve accessibility issues (missing alt text, aria labels)\n`;
    md += `3. Fix broken links and error states\n`;
    md += `4. Ensure all list pages have functional search/sort\n`;
    md += `5. Add proper error handling and empty states\n\n`;

    md += `### Phase 2: UX Improvements (Production Ready+)\n`;
    md += `**Timeline:** Short term (2-4 weeks)\n\n`;
    md += `1. Add loading skeletons/placeholders\n`;
    md += `2. Implement breadcrumb navigation\n`;
    md += `3. Add tooltips and contextual help\n`;
    md += `4. Improve visual consistency\n`;
    md += `5. Add export/download functionality\n`;
    md += `6. Implement responsive design\n\n`;

    md += `### Phase 3: Enhanced Features (Nice to Have)\n`;
    md += `**Timeline:** Medium term (1-2 months)\n\n`;
    md += `1. Add dark mode support\n`;
    md += `2. Implement keyboard shortcuts\n`;
    md += `3. Add data visualizations/charts\n`;
    md += `4. Create onboarding tour\n`;
    md += `5. Add bulk actions\n`;
    md += `6. Implement PWA features\n\n`;

    md += `### Phase 4: Advanced Features (Future)\n`;
    md += `**Timeline:** Long term (3+ months)\n\n`;
    md += `1. Real-time updates\n`;
    md += `2. Advanced analytics\n`;
    md += `3. Customizable dashboards\n`;
    md += `4. Collaborative features\n`;
    md += `5. Advanced filtering/search\n`;
    md += `6. Performance optimizations\n\n`;

    return md;
}

async function main() {
    console.log('🔍 Starting Comprehensive UX Audit...');
    console.log(`📍 Base URL: ${BASE_URL}`);
    console.log(`📄 Routes to analyze: ${ROUTES_TO_TEST.length}\n`);

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        viewport: { width: 1920, height: 1080 }
    });
    const page = await context.newPage();

    try {
        for (const route of ROUTES_TO_TEST) {
            console.log(`Analyzing: ${route.name} (${route.url})`);

            try {
                await page.goto(BASE_URL + route.url, { waitUntil: 'networkidle', timeout: 10000 });
                await page.waitForTimeout(2000);

                const findings = await comprehensivePageAnalysis(page, route);
                uxFindings.push(findings);

                console.log(`  ✓ Score: ${findings.overallScore}/100`);

            } catch (error) {
                console.error(`  ❌ Error: ${error.message}`);
                uxFindings.push({
                    route: route.url,
                    name: route.name,
                    type: route.type,
                    error: error.message,
                    overallScore: 0,
                    visualDesign: { score: 0, issues: [], improvements: [] },
                    userExperience: { score: 0, issues: [], improvements: [] },
                    contentIA: { score: 0, issues: [], improvements: [] },
                    functionality: { score: 0, issues: [], improvements: [] },
                    accessibility: { score: 0, issues: [], improvements: [] },
                    productionReadiness: { blockers: [error.message], recommended: [], niceToHave: [] }
                });
            }
        }

        console.log(`\n✅ Analysis complete!`);
        console.log('📝 Generating comprehensive report...\n');

        const report = generateComprehensiveReport();
        fs.writeFileSync(REPORT_FILE, report, 'utf8');

        const avgScore = Math.round(uxFindings.reduce((sum, f) => sum + f.overallScore, 0) / uxFindings.length);

        console.log(`✅ Report saved to: ${REPORT_FILE}`);
        console.log(`📸 Screenshots saved to: ${SCREENSHOTS_DIR}/`);
        console.log(`\n📊 Summary:`);
        console.log(`   Overall Readiness Score: ${avgScore}/100`);
        console.log(`   Pages Analyzed: ${uxFindings.length}`);
        console.log(`   Critical Blockers: ${uxFindings.flatMap(f => f.productionReadiness.blockers).length}`);

    } catch (error) {
        console.error('❌ Fatal error:', error);
    } finally {
        await browser.close();
    }
}

main();
