/**
 * Navigation & User Flow UX Audit
 *
 * Tests navigation patterns between:
 * - Workflows (parent containers)
 * - Actions/Prompts/Schemas (both in workflow context and as independent units)
 * - Detail views and list views
 * - Filtered views and unfiltered views
 */

const { chromium } = require('playwright');
const fs = require('fs');

const BASE_URL = 'http://localhost:8890';
const REPORT_FILE = './UX_NAVIGATION_ANALYSIS.md';

const navigationTests = [];
const navigationIssues = [];

async function testNavigationFlow(page, testName, steps) {
    console.log(`\nTesting: ${testName}`);
    const result = {
        testName,
        steps: [],
        issues: [],
        recommendations: [],
        success: true
    };

    for (const step of steps) {
        console.log(`  ${step.action}`);
        const stepResult = {
            action: step.action,
            url: '',
            found: false,
            details: ''
        };

        try {
            if (step.type === 'navigate') {
                await page.goto(BASE_URL + step.url, { waitUntil: 'networkidle', timeout: 10000 });
                await page.waitForTimeout(1000);
                stepResult.url = page.url();
                stepResult.found = true;
                stepResult.details = await page.title();
            }

            if (step.type === 'click') {
                const element = await page.$(step.selector);
                if (element) {
                    const isVisible = await element.isVisible();
                    if (isVisible) {
                        await element.click();
                        await page.waitForTimeout(1000);
                        stepResult.url = page.url();
                        stepResult.found = true;
                        stepResult.details = 'Element clicked successfully';
                    } else {
                        stepResult.found = false;
                        stepResult.details = 'Element exists but not visible';
                        result.issues.push(`${step.action}: Element not visible`);
                    }
                } else {
                    stepResult.found = false;
                    stepResult.details = 'Element not found';
                    result.issues.push(`${step.action}: ${step.selector} not found`);
                    result.success = false;
                }
            }

            if (step.type === 'check') {
                const element = await page.$(step.selector);
                stepResult.found = !!element;
                if (element) {
                    const isVisible = await element.isVisible();
                    const text = await element.textContent();
                    stepResult.details = `Found: ${text?.trim().substring(0, 50)}... (visible: ${isVisible})`;

                    if (step.shouldExist && !isVisible) {
                        result.issues.push(`${step.action}: Element exists but not visible`);
                    }
                } else if (step.shouldExist) {
                    stepResult.details = 'Not found';
                    result.issues.push(`${step.action}: Required element missing`);
                    result.success = false;
                }
            }

            if (step.type === 'verify_url') {
                const currentUrl = page.url();
                const matches = currentUrl.includes(step.urlPattern);
                stepResult.found = matches;
                stepResult.url = currentUrl;
                stepResult.details = matches ? 'URL matches expected pattern' : `Expected pattern: ${step.urlPattern}`;

                if (!matches) {
                    result.issues.push(`${step.action}: URL doesn't match expected pattern`);
                }
            }

        } catch (error) {
            stepResult.details = `Error: ${error.message}`;
            result.issues.push(`${step.action}: ${error.message}`);
            result.success = false;
        }

        result.steps.push(stepResult);
    }

    return result;
}

async function analyzeNavigationPatterns(page) {
    const analysis = {
        workflowNavigation: {
            issues: [],
            recommendations: []
        },
        actionNavigation: {
            issues: [],
            recommendations: []
        },
        promptNavigation: {
            issues: [],
            recommendations: []
        },
        schemaNavigation: {
            issues: [],
            recommendations: []
        },
        breadcrumbs: {
            issues: [],
            recommendations: []
        },
        crossReferences: {
            issues: [],
            recommendations: []
        },
        backNavigation: {
            issues: [],
            recommendations: []
        }
    };

    // Test 1: Workflow List to Workflow Detail
    console.log('\n=== Testing Workflow Navigation Patterns ===');

    const test1 = await testNavigationFlow(page, 'Navigate from Workflows List to First Workflow Detail', [
        { type: 'navigate', url: '/#/workflows', action: 'Go to Workflows list' },
        { type: 'check', selector: '.workflow-card', shouldExist: true, action: 'Check for workflow cards' },
        { type: 'click', selector: '.workflow-card:first-child', action: 'Click first workflow card' },
        { type: 'verify_url', urlPattern: '#/workflow/', action: 'Verify navigated to workflow detail' },
        { type: 'check', selector: '.page-header', shouldExist: true, action: 'Check for page header on detail' }
    ]);
    navigationTests.push(test1);

    if (!test1.success) {
        analysis.workflowNavigation.issues.push('Cannot navigate from workflow list to detail view');
    }

    // Test 2: Workflow Detail - View Actions
    const test2 = await testNavigationFlow(page, 'View Actions from within Workflow Detail', [
        { type: 'navigate', url: '/#/workflows', action: 'Go to Workflows list' },
        { type: 'click', selector: '.workflow-card:first-child', action: 'Click first workflow' },
        { type: 'check', selector: '[class*="action"], .action-card, .action-list', shouldExist: false, action: 'Check if actions section exists' }
    ]);
    navigationTests.push(test2);

    if (test2.steps[2].found === false) {
        analysis.workflowNavigation.recommendations.push('Add actions list/section to workflow detail view to show workflow-specific actions');
    }

    // Test 3: Navigate to Independent Actions List
    const test3 = await testNavigationFlow(page, 'Navigate to Independent Actions List (All Actions)', [
        { type: 'navigate', url: '/#/actions', action: 'Go to All Actions' },
        { type: 'check', selector: '.workflow-card, .action-card, .card', shouldExist: true, action: 'Check for action cards' },
        { type: 'check', selector: 'h1, h2', shouldExist: true, action: 'Check for page title' }
    ]);
    navigationTests.push(test3);

    if (!test3.success) {
        analysis.actionNavigation.issues.push('All Actions list view not working properly');
    }

    // Test 4: Actions - Workflow Context Link
    const test4 = await testNavigationFlow(page, 'Check if Actions show parent Workflow context', [
        { type: 'navigate', url: '/#/actions', action: 'Go to All Actions' },
        { type: 'check', selector: '.workflow-card, .action-card', shouldExist: true, action: 'Find action card' },
        { type: 'check', selector: '[class*="workflow-name"], .workflow-badge, .parent-workflow', shouldExist: false, action: 'Check for workflow context indicator' }
    ]);
    navigationTests.push(test4);

    if (test4.steps[2].found === false) {
        analysis.crossReferences.recommendations.push('Add parent workflow name/badge to action cards to show which workflow they belong to');
    }

    // Test 5: Breadcrumb Navigation
    const test5 = await testNavigationFlow(page, 'Check Breadcrumb Navigation on Detail Pages', [
        { type: 'navigate', url: '/#/workflows', action: 'Go to Workflows' },
        { type: 'check', selector: '.breadcrumb, nav[aria-label*="breadcrumb"]', shouldExist: true, action: 'Check for breadcrumbs on list view' }
    ]);
    navigationTests.push(test5);

    if (test5.steps[1].found) {
        analysis.breadcrumbs.recommendations.push('Breadcrumbs found - verify they update correctly on navigation');
    } else {
        analysis.breadcrumbs.issues.push('No breadcrumb navigation found on pages');
    }

    // Test 6: Back Button on Detail Views
    const test6 = await testNavigationFlow(page, 'Check for Back Button on Detail Views', [
        { type: 'navigate', url: '/#/workflows', action: 'Go to Workflows list' },
        { type: 'click', selector: '.workflow-card:first-child', action: 'Click first workflow' },
        { type: 'check', selector: 'button[aria-label*="back"], button[aria-label*="Back"], .back-button', shouldExist: false, action: 'Check for back button' }
    ]);
    navigationTests.push(test6);

    if (test6.steps[2].found === false) {
        analysis.backNavigation.recommendations.push('Add explicit back button on detail views for easier navigation');
    }

    // Test 7: Prompts - Independent vs Workflow Context
    const test7 = await testNavigationFlow(page, 'Navigate to Independent Prompts List', [
        { type: 'navigate', url: '/#/prompts', action: 'Go to All Prompts' },
        { type: 'check', selector: '.workflow-card, .prompt-card, .card', shouldExist: true, action: 'Check for prompt cards' },
        { type: 'check', selector: 'input[placeholder*="Search"]', shouldExist: true, action: 'Check for search functionality' }
    ]);
    navigationTests.push(test7);

    if (!test7.success) {
        analysis.promptNavigation.issues.push('Prompts list view not working properly');
    }

    // Test 8: Schemas - Independent vs Workflow Context
    const test8 = await testNavigationFlow(page, 'Navigate to Independent Schemas List', [
        { type: 'navigate', url: '/#/schemas', action: 'Go to All Schemas' },
        { type: 'check', selector: '.workflow-card, .schema-card, .card', shouldExist: true, action: 'Check for schema cards' },
        { type: 'check', selector: 'input[placeholder*="Search"]', shouldExist: true, action: 'Check for search functionality' }
    ]);
    navigationTests.push(test8);

    if (!test8.success) {
        analysis.schemaNavigation.issues.push('Schemas list view not working properly');
    }

    // Test 9: Sidebar Navigation
    const test9 = await testNavigationFlow(page, 'Test Sidebar Navigation Links', [
        { type: 'navigate', url: '/#/', action: 'Go to home' },
        { type: 'check', selector: '.sidebar a[href*="workflows"], nav a[href*="workflows"]', shouldExist: true, action: 'Check for Workflows nav link' },
        { type: 'check', selector: '.sidebar a[href*="actions"], nav a[href*="actions"]', shouldExist: true, action: 'Check for Actions nav link' },
        { type: 'check', selector: '.sidebar a[href*="prompts"], nav a[href*="prompts"]', shouldExist: true, action: 'Check for Prompts nav link' },
        { type: 'check', selector: '.sidebar a[href*="schemas"], nav a[href*="schemas"]', shouldExist: true, action: 'Check for Schemas nav link' }
    ]);
    navigationTests.push(test9);

    const navLinksFound = test9.steps.filter(s => s.found).length - 1; // -1 for navigate step
    if (navLinksFound < 4) {
        analysis.workflowNavigation.recommendations.push(`Only ${navLinksFound}/4 main navigation links found in sidebar`);
    }

    // Test 10: Filter Navigation (LLM vs Tool actions)
    const test10 = await testNavigationFlow(page, 'Navigate between Action Filters (LLM/Tool)', [
        { type: 'navigate', url: '/#/actions', action: 'Go to All Actions' },
        { type: 'navigate', url: '/#/actions/llm', action: 'Filter to LLM Actions' },
        { type: 'check', selector: '.filter-chip, .active-filter, [class*="filter"]', shouldExist: false, action: 'Check if filter is visually indicated' },
        { type: 'navigate', url: '/#/actions/tool', action: 'Filter to Tool Actions' },
        { type: 'check', selector: '.filter-chip, .active-filter, [class*="filter"]', shouldExist: false, action: 'Check if filter is visually indicated' }
    ]);
    navigationTests.push(test10);

    if (test10.steps[2].found === false) {
        analysis.actionNavigation.recommendations.push('Add visual indication when filters are active (e.g., filter chips, badges)');
    }

    // Test 11: Deep Linking
    const test11 = await testNavigationFlow(page, 'Test Deep Linking to Specific Items', [
        { type: 'navigate', url: '/#/workflows', action: 'Go to workflows' },
        { type: 'click', selector: '.workflow-card:first-child', action: 'Click first workflow' },
        { type: 'verify_url', urlPattern: '#/workflow/', action: 'Verify detail URL has unique identifier' }
    ]);
    navigationTests.push(test11);

    if (test11.success) {
        analysis.workflowNavigation.recommendations.push('Deep linking works - ensure all detail pages have shareable URLs');
    } else {
        analysis.workflowNavigation.issues.push('Deep linking may not work properly for detail pages');
    }

    // Test 12: Cross-navigation between different entity types
    const test12 = await testNavigationFlow(page, 'Navigate between different entity types', [
        { type: 'navigate', url: '/#/workflows', action: 'Start at Workflows' },
        { type: 'navigate', url: '/#/actions', action: 'Switch to Actions' },
        { type: 'navigate', url: '/#/prompts', action: 'Switch to Prompts' },
        { type: 'navigate', url: '/#/schemas', action: 'Switch to Schemas' },
        { type: 'navigate', url: '/#/workflows', action: 'Return to Workflows' }
    ]);
    navigationTests.push(test12);

    return analysis;
}

function generateNavigationReport() {
    let md = `# Navigation & User Flow Analysis\n## Agent Actions Documentation Site\n\n`;
    md += `**Generated:** ${new Date().toLocaleString()}\n`;
    md += `**Tests Performed:** ${navigationTests.length}\n\n`;

    // Executive Summary
    const successfulTests = navigationTests.filter(t => t.success).length;
    const failedTests = navigationTests.length - successfulTests;
    const totalIssues = navigationTests.reduce((sum, t) => sum + t.issues.length, 0);
    const totalRecommendations = navigationTests.reduce((sum, t) => sum + t.recommendations.length, 0);

    md += `---\n\n## 📊 Executive Summary\n\n`;
    md += `- **Tests Passed:** ${successfulTests}/${navigationTests.length}\n`;
    md += `- **Tests Failed:** ${failedTests}\n`;
    md += `- **Navigation Issues Found:** ${totalIssues}\n`;
    md += `- **Recommendations:** ${totalRecommendations}\n\n`;

    const score = Math.round((successfulTests / navigationTests.length) * 100);
    const status = score >= 90 ? '🟢 Excellent' :
                  score >= 75 ? '🟡 Good' :
                  score >= 60 ? '🟠 Needs Improvement' :
                  '🔴 Critical Issues';

    md += `**Navigation Health Score:** ${score}/100 - ${status}\n\n`;

    md += `---\n\n`;

    // Navigation Patterns Overview
    md += `## 🗺️ Navigation Patterns Overview\n\n`;
    md += `### Current Architecture\n\n`;
    md += `The Agent Actions docs site has two main navigation contexts:\n\n`;
    md += `#### 1. Workflow-Centric Context\n`;
    md += `- **Workflows** are parent containers\n`;
    md += `- Actions, Prompts, and Schemas are viewed as **part of a workflow**\n`;
    md += `- Navigation: Workflows List → Workflow Detail → View Actions/Prompts/Schemas\n\n`;

    md += `#### 2. Independent Entity Context\n`;
    md += `- Actions, Prompts, and Schemas can be viewed **independently**\n`;
    md += `- Each has its own list view across all workflows\n`;
    md += `- Navigation: Direct access via sidebar → All Actions/Prompts/Schemas\n\n`;

    md += `### Expected Navigation Flows\n\n`;
    md += `\`\`\`\n`;
    md += `Home Dashboard\n`;
    md += `├── Workflows List\n`;
    md += `│   └── Workflow Detail (specific workflow)\n`;
    md += `│       ├── View Actions (workflow-specific)\n`;
    md += `│       ├── View Prompts (workflow-specific)\n`;
    md += `│       └── View Schemas (workflow-specific)\n`;
    md += `├── All Actions List (across all workflows)\n`;
    md += `│   ├── Filter: LLM Actions\n`;
    md += `│   ├── Filter: Tool Actions\n`;
    md += `│   └── Action Detail\n`;
    md += `│       └── Link back to parent Workflow\n`;
    md += `├── All Prompts List (across all workflows)\n`;
    md += `│   └── Prompt Detail\n`;
    md += `│       └── Link back to parent Workflow\n`;
    md += `├── All Schemas List (across all workflows)\n`;
    md += `│   └── Schema Detail\n`;
    md += `│       └── Link back to parent Workflow\n`;
    md += `├── All Runs List\n`;
    md += `└── Observability Dashboard\n`;
    md += `\`\`\`\n\n`;

    md += `---\n\n`;

    // Critical Navigation Issues
    md += `## 🔴 Critical Navigation Issues\n\n`;
    const criticalIssues = navigationTests.filter(t => !t.success);
    if (criticalIssues.length > 0) {
        md += `| Test | Issue | Impact |\n`;
        md += `|------|-------|--------|\n`;
        criticalIssues.forEach(test => {
            test.issues.forEach(issue => {
                md += `| ${test.testName} | ${issue} | High |\n`;
            });
        });
    } else {
        md += `✅ No critical navigation issues found!\n`;
    }
    md += `\n---\n\n`;

    // Recommendations Table
    md += `## 💡 Navigation Improvement Recommendations\n\n`;
    md += `| Priority | Area | Recommendation | Effort | Impact |\n`;
    md += `|----------|------|----------------|--------|--------|\n`;

    const allRecommendations = [];
    navigationTests.forEach(test => {
        test.recommendations.forEach(rec => {
            allRecommendations.push({
                test: test.testName,
                recommendation: rec,
                priority: rec.includes('Add') ? '🟡 Medium' : '🟢 Low',
                effort: rec.includes('Add') ? 'Medium' : 'Low',
                impact: rec.includes('workflow') || rec.includes('context') ? 'High' : 'Medium'
            });
        });
    });

    allRecommendations.forEach(rec => {
        const area = rec.test.includes('Workflow') ? 'Workflows' :
                    rec.test.includes('Action') ? 'Actions' :
                    rec.test.includes('Prompt') ? 'Prompts' :
                    rec.test.includes('Schema') ? 'Schemas' :
                    rec.test.includes('Breadcrumb') ? 'Navigation' : 'General';
        md += `| ${rec.priority} | ${area} | ${rec.recommendation} | ${rec.effort} | ${rec.impact} |\n`;
    });

    md += `\n---\n\n`;

    // Detailed Test Results
    md += `## 📋 Detailed Test Results\n\n`;

    navigationTests.forEach((test, index) => {
        md += `### ${index + 1}. ${test.testName}\n\n`;
        md += `**Status:** ${test.success ? '✅ Pass' : '❌ Fail'}\n\n`;

        if (test.steps.length > 0) {
            md += `**Steps:**\n`;
            test.steps.forEach((step, i) => {
                const icon = step.found ? '✓' : '✗';
                md += `${i + 1}. [${icon}] ${step.action}\n`;
                if (step.details) {
                    md += `   - ${step.details}\n`;
                }
                if (step.url) {
                    md += `   - URL: \`${step.url}\`\n`;
                }
            });
            md += `\n`;
        }

        if (test.issues.length > 0) {
            md += `**Issues:**\n`;
            test.issues.forEach(issue => {
                md += `- ❌ ${issue}\n`;
            });
            md += `\n`;
        }

        if (test.recommendations.length > 0) {
            md += `**Recommendations:**\n`;
            test.recommendations.forEach(rec => {
                md += `- 💡 ${rec}\n`;
            });
            md += `\n`;
        }

        md += `---\n\n`;
    });

    // Implementation Guide
    md += `## 🚀 Implementation Guide for Navigation Improvements\n\n`;

    md += `### Phase 1: Establish Context Awareness (High Priority)\n\n`;
    md += `#### Goal: Users should always know where they are and how to get back\n\n`;
    md += `**Tasks:**\n`;
    md += `1. **Add Parent Workflow Context to Independent Views**\n`;
    md += `   - When viewing "All Actions", show which workflow each action belongs to\n`;
    md += `   - Add workflow badge/chip to each action/prompt/schema card\n`;
    md += `   - Make workflow name clickable to navigate to that workflow\n\n`;

    md += `2. **Implement Breadcrumb Navigation**\n`;
    md += `   \`\`\`\n`;
    md += `   Home > Workflows > [Workflow Name] > Actions\n`;
    md += `   Home > All Actions > [Action Name]\n`;
    md += `   \`\`\`\n`;
    md += `   - Show current location in hierarchy\n`;
    md += `   - Make all breadcrumb levels clickable\n`;
    md += `   - Update dynamically based on navigation context\n\n`;

    md += `3. **Add Back Navigation**\n`;
    md += `   - Add "← Back" button on all detail pages\n`;
    md += `   - Respect browser history (go back to previous page, not always list)\n`;
    md += `   - Show destination in button label: "← Back to Workflows"\n\n`;

    md += `### Phase 2: Enhance Workflow Detail Pages (Medium Priority)\n\n`;
    md += `**Tasks:**\n`;
    md += `1. **Add Sections to Workflow Detail**\n`;
    md += `   - Actions tab/section showing all actions in this workflow\n`;
    md += `   - Prompts tab/section showing all prompts in this workflow\n`;
    md += `   - Schemas tab/section showing all schemas in this workflow\n`;
    md += `   - Runs tab/section showing executions of this workflow\n\n`;

    md += `2. **Implement Tab or Accordion Navigation**\n`;
    md += `   \`\`\`\n`;
    md += `   [Overview] [Actions] [Prompts] [Schemas] [Runs]\n`;
    md += `   \`\`\`\n`;
    md += `   - Use URL hash to maintain state: \`#/workflow/123#actions\`\n`;
    md += `   - Highlight active tab\n`;
    md += `   - Show count badges: "Actions (5)"\n\n`;

    md += `### Phase 3: Cross-Reference Navigation (Medium Priority)\n\n`;
    md += `**Tasks:**\n`;
    md += `1. **Link from Detail Pages Back to Context**\n`;
    md += `   - On Action Detail: "Part of [Workflow Name]" (clickable)\n`;
    md += `   - On Prompt Detail: "Used in [Workflow Name]" (clickable)\n`;
    md += `   - On Schema Detail: "Defined in [Workflow Name]" (clickable)\n\n`;

    md += `2. **Add "View All" Links**\n`;
    md += `   - From "LLM Actions" filter: "View All Actions" button\n`;
    md += `   - From workflow context: "View All Workflows" breadcrumb\n`;
    md += `   - Clear filter state when switching contexts\n\n`;

    md += `3. **Related Items Navigation**\n`;
    md += `   - Show related prompts when viewing an action\n`;
    md += `   - Show related schemas when viewing an action\n`;
    md += `   - Add "Related Actions" section in workflow detail\n\n`;

    md += `### Phase 4: Visual Navigation Indicators (Low Priority)\n\n`;
    md += `**Tasks:**\n`;
    md += `1. **Active Filter Indicators**\n`;
    md += `   - Show filter chips when filters are active\n`;
    md += `   - Add "x" to clear individual filters\n`;
    md += `   - Highlight active sidebar item\n\n`;

    md += `2. **Navigation State Persistence**\n`;
    md += `   - Remember scroll position when navigating back\n`;
    md += `   - Restore filter/search state on browser back\n`;
    md += `   - Highlight recently viewed items\n\n`;

    md += `3. **Quick Navigation**\n`;
    md += `   - Add keyboard shortcuts (/ for search, g+w for workflows)\n`;
    md += `   - Implement command palette (Cmd+K)\n`;
    md += `   - Add recent/favorite items quick access\n\n`;

    md += `---\n\n`;

    // Example Implementation
    md += `## 💻 Example Implementation\n\n`;

    md += `### 1. Adding Workflow Context to Action Cards\n\n`;
    md += `\`\`\`javascript\n`;
    md += `function createActionCard(action, workflowName, workflowId) {\n`;
    md += `    const card = document.createElement('div');\n`;
    md += `    card.className = 'workflow-card';\n`;
    md += `    \n`;
    md += `    card.innerHTML = \\\`\n`;
    md += `        <div class="workflow-card-header">\n`;
    md += `            <h3>\${action.name}</h3>\n`;
    md += `            <!-- ADD THIS: Workflow context badge -->\n`;
    md += `            <span class="workflow-context-badge" \n`;
    md += `                  onclick="navigateToWorkflow('\${workflowId}')">\n`;
    md += `                📦 \${workflowName}\n`;
    md += `            </span>\n`;
    md += `        </div>\n`;
    md += `        <p>\${action.intent}</p>\n`;
    md += `    \\\`;\n`;
    md += `    return card;\n`;
    md += `}\n`;
    md += `\`\`\`\n\n`;

    md += `### 2. Adding Breadcrumb Navigation\n\n`;
    md += `\`\`\`javascript\n`;
    md += `function updateBreadcrumbs(path) {\n`;
    md += `    const breadcrumbContainer = document.getElementById('breadcrumbs');\n`;
    md += `    const crumbs = [];\n`;
    md += `    \n`;
    md += `    // Always start with Home\n`;
    md += `    crumbs.push({ label: 'Home', url: '#/' });\n`;
    md += `    \n`;
    md += `    if (path.includes('/workflow/')) {\n`;
    md += `        crumbs.push({ label: 'Workflows', url: '#/workflows' });\n`;
    md += `        crumbs.push({ label: workflowName, url: path });\n`;
    md += `    } else if (path.includes('/actions')) {\n`;
    md += `        crumbs.push({ label: 'All Actions', url: '#/actions' });\n`;
    md += `        if (path.includes('/llm')) {\n`;
    md += `            crumbs.push({ label: 'LLM Actions', url: '#/actions/llm' });\n`;
    md += `        }\n`;
    md += `    }\n`;
    md += `    \n`;
    md += `    renderBreadcrumbs(breadcrumbContainer, crumbs);\n`;
    md += `}\n`;
    md += `\`\`\`\n\n`;

    md += `### 3. Adding Back Button with Context\n\n`;
    md += `\`\`\`javascript\n`;
    md += `function addBackButton(targetView, targetLabel) {\n`;
    md += `    const backButton = document.createElement('button');\n`;
    md += `    backButton.className = 'back-button';\n`;
    md += `    backButton.innerHTML = \\\`\n`;
    md += `        <svg><!-- back arrow icon --></svg>\n`;
    md += `        Back to \${targetLabel}\n`;
    md += `    \\\`;\n`;
    md += `    backButton.onclick = () => {\n`;
    md += `        window.location.hash = targetView;\n`;
    md += `    };\n`;
    md += `    return backButton;\n`;
    md += `}\n`;
    md += `\`\`\`\n\n`;

    md += `---\n\n`;

    md += `## 📊 Success Metrics\n\n`;
    md += `After implementing navigation improvements, track:\n\n`;
    md += `1. **User Engagement**\n`;
    md += `   - Average pages per session (should increase)\n`;
    md += `   - Time spent on site (should increase)\n`;
    md += `   - Bounce rate (should decrease)\n\n`;

    md += `2. **Navigation Efficiency**\n`;
    md += `   - Clicks to reach target page (should decrease)\n`;
    md += `   - Use of back button vs breadcrumbs\n`;
    md += `   - Search usage vs browsing\n\n`;

    md += `3. **User Satisfaction**\n`;
    md += `   - Can users find related items easily?\n`;
    md += `   - Do users understand workflow vs independent contexts?\n`;
    md += `   - Are navigation paths clear and intuitive?\n\n`;

    return md;
}

async function main() {
    console.log('🧭 Starting Navigation & User Flow Analysis...');
    console.log(`📍 Base URL: ${BASE_URL}\n`);

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        viewport: { width: 1920, height: 1080 }
    });
    const page = await context.newPage();

    try {
        const analysis = await analyzeNavigationPatterns(page);

        console.log('\n📝 Generating navigation report...');
        const report = generateNavigationReport();
        fs.writeFileSync(REPORT_FILE, report, 'utf8');

        const successfulTests = navigationTests.filter(t => t.success).length;
        const score = Math.round((successfulTests / navigationTests.length) * 100);

        console.log(`\n✅ Report saved to: ${REPORT_FILE}`);
        console.log(`\n📊 Summary:`);
        console.log(`   Navigation Health Score: ${score}/100`);
        console.log(`   Tests Passed: ${successfulTests}/${navigationTests.length}`);
        console.log(`   Issues Found: ${navigationTests.reduce((sum, t) => sum + t.issues.length, 0)}`);
        console.log(`   Recommendations: ${navigationTests.reduce((sum, t) => sum + t.recommendations.length, 0)}`);

    } catch (error) {
        console.error('❌ Error during analysis:', error);
    } finally {
        await browser.close();
    }
}

main();
