import React from 'react';
import ComponentCreator from '@docusaurus/ComponentCreator';

export default [
  {
    path: '/markdown-page',
    component: ComponentCreator('/markdown-page', '3d7'),
    exact: true
  },
  {
    path: '/docs',
    component: ComponentCreator('/docs', '3c8'),
    routes: [
      {
        path: '/docs',
        component: ComponentCreator('/docs', '65d'),
        routes: [
          {
            path: '/docs',
            component: ComponentCreator('/docs', '25e'),
            routes: [
              {
                path: '/docs/',
                component: ComponentCreator('/docs/', 'af3'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/api/',
                component: ComponentCreator('/docs/api/', 'b31'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/api/logging',
                component: ComponentCreator('/docs/api/logging', '01f'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/guides/',
                component: ComponentCreator('/docs/guides/', '32a'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/guides/custom-tools',
                component: ComponentCreator('/docs/guides/custom-tools', '4b3'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/guides/design-patterns',
                component: ComponentCreator('/docs/guides/design-patterns', '094'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/guides/editor-setup',
                component: ComponentCreator('/docs/guides/editor-setup', '281'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/guides/troubleshooting',
                component: ComponentCreator('/docs/guides/troubleshooting', 'b6c'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/installation',
                component: ComponentCreator('/docs/installation', '034'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/',
                component: ComponentCreator('/docs/reference/', 'de6'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/architecture/',
                component: ComponentCreator('/docs/reference/architecture/', 'db5'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/architecture/logging',
                component: ComponentCreator('/docs/reference/architecture/logging', '6dc'),
                exact: true
              },
              {
                path: '/docs/reference/cli/',
                component: ComponentCreator('/docs/reference/cli/', 'a86'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/batch',
                component: ComponentCreator('/docs/reference/cli/batch', 'a68'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/inspect',
                component: ComponentCreator('/docs/reference/cli/inspect', '8a9'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/run',
                component: ComponentCreator('/docs/reference/cli/run', '532'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/schema',
                component: ComponentCreator('/docs/reference/cli/schema', '54a'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/skills',
                component: ComponentCreator('/docs/reference/cli/skills', 'ca3'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/tools',
                component: ComponentCreator('/docs/reference/cli/tools', 'd5a'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/troubleshooting',
                component: ComponentCreator('/docs/reference/cli/troubleshooting', '9e4'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/cli/utilities',
                component: ComponentCreator('/docs/reference/cli/utilities', '89a'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/configuration/',
                component: ComponentCreator('/docs/reference/configuration/', 'b38'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/configuration/defaults',
                component: ComponentCreator('/docs/reference/configuration/defaults', '6c5'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/configuration/templates',
                component: ComponentCreator('/docs/reference/configuration/templates', '429'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/context/',
                component: ComponentCreator('/docs/reference/context/', '768'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/context/context-scope',
                component: ComponentCreator('/docs/reference/context/context-scope', 'af1'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/context/field-references',
                component: ComponentCreator('/docs/reference/context/field-references', '983'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/context/seed-data',
                component: ComponentCreator('/docs/reference/context/seed-data', '587'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/data-io/',
                component: ComponentCreator('/docs/reference/data-io/', 'db6'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/data-io/chunking',
                component: ComponentCreator('/docs/reference/data-io/chunking', 'f49'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/data-io/data-lineage',
                component: ComponentCreator('/docs/reference/data-io/data-lineage', '160'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/data-io/input-formats',
                component: ComponentCreator('/docs/reference/data-io/input-formats', 'a20'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/data-io/output-format',
                component: ComponentCreator('/docs/reference/data-io/output-format', '5aa'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/documentation-site',
                component: ComponentCreator('/docs/reference/documentation-site', '1fa'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/',
                component: ComponentCreator('/docs/reference/execution/', 'f38'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/artifacts',
                component: ComponentCreator('/docs/reference/execution/artifacts', '97d'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/context-handling',
                component: ComponentCreator('/docs/reference/execution/context-handling', '2e2'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/granularity',
                component: ComponentCreator('/docs/reference/execution/granularity', '3e1'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/guards',
                component: ComponentCreator('/docs/reference/execution/guards', 'd9a'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/retry',
                component: ComponentCreator('/docs/reference/execution/retry', '031'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/run-modes',
                component: ComponentCreator('/docs/reference/execution/run-modes', '4ce'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/versions',
                component: ComponentCreator('/docs/reference/execution/versions', 'f57'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/execution/workflow-dependencies',
                component: ComponentCreator('/docs/reference/execution/workflow-dependencies', '1c8'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/inspect',
                component: ComponentCreator('/docs/reference/inspect', '5a8'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/prompts/',
                component: ComponentCreator('/docs/reference/prompts/', '541'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/prompts/dispatch',
                component: ComponentCreator('/docs/reference/prompts/dispatch', 'ff1'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/prompts/prompt-store',
                component: ComponentCreator('/docs/reference/prompts/prompt-store', '9d2'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/schemas/',
                component: ComponentCreator('/docs/reference/schemas/', 'd1f'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/tools/',
                component: ComponentCreator('/docs/reference/tools/', 'eed'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/validation/',
                component: ComponentCreator('/docs/reference/validation/', 'e1c'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/validation/output-validation',
                component: ComponentCreator('/docs/reference/validation/output-validation', '490'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/reference/validation/reprompting',
                component: ComponentCreator('/docs/reference/validation/reprompting', '9ab'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/tutorials/',
                component: ComponentCreator('/docs/tutorials/', 'b5b'),
                exact: true,
                sidebar: "docsSidebar"
              },
              {
                path: '/docs/tutorials/concepts',
                component: ComponentCreator('/docs/tutorials/concepts', '6c0'),
                exact: true,
                sidebar: "docsSidebar"
              }
            ]
          }
        ]
      }
    ]
  },
  {
    path: '/',
    component: ComponentCreator('/', 'e5f'),
    exact: true
  },
  {
    path: '*',
    component: ComponentCreator('*'),
  },
];
