import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */
const sidebars: SidebarsConfig = {
  // Manual sidebar configuration for better organization
  docsSidebar: [
    'index',
    'installation',
    'getting-started',
    'cli-reference',
    {
      type: 'category',
      label: 'Platform',
      collapsed: false,
      items: [
        'platform/index',
        'platform/project-structure',
      ],
    },
    {
      type: 'category',
      label: 'Core Concepts',
      collapsed: false,
      items: [
        'core-concepts/index',
        'core-concepts/agents',
        'core-concepts/workflows',
        'core-concepts/tool-actions',
        'core-concepts/schemas',
        'core-concepts/configuration-hierarchy',
        'core-concepts/tokenizers',
        'core-concepts/error-handling',
      ],
    },
    {
      type: 'category',
      label: 'Examples',
      collapsed: false,
      items: [
        'examples/index',
        {
          type: 'category',
          label: 'Configuration Examples',
          items: [
            'examples/configurations/index',
            'examples/configurations/project-only',
            'examples/configurations/workflow-overrides',
            'examples/configurations/action-overrides',
            'examples/configurations/mixed-hierarchy',
            'examples/configurations/environment-variables',
            'examples/configurations/tool-actions',
            'examples/configurations/batch-mode',
            'examples/configurations/reprompting-validators',
          ],
        },
        'examples/custom-validators',
      ],
    },
    {
      type: 'category',
      label: 'Guides',
      collapsed: false,
      items: [
        'guides/ide-setup',
        'guides/reprompting',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      collapsed: false,
      items: [
        'reference/configuration-schema',
        'reference/configuration-fields',
      ],
    },
    // Future categories can be added here
    /*
    {
      type: 'category',
      label: 'API Reference',
      items: ['api/agents', 'api/tasks', 'api/integrations'],
    },
    */
  ],
};

export default sidebars;
