import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'index',
    'installation',
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      collapsible: false,
      link: {
        type: 'doc',
        id: 'getting-started/index',
      },
      items: [
        'getting-started/concepts',
        'getting-started/custom-functions',
        'getting-started/patterns',
      ],
    },
    {
      type: 'category',
      label: 'CLI Reference',
      collapsed: false,
      collapsible: false,
      link: {
        type: 'doc',
        id: 'cli-reference/index',
      },
      items: [
        'cli-reference/run',
        'cli-reference/batch',
        'cli-reference/utilities',
        'cli-reference/udfs',
        'cli-reference/schema',
        'cli-reference/skills',
        'cli-reference/troubleshooting',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      collapsed: false,
      collapsible: false,
      link: {
        type: 'doc',
        id: 'reference/index',
      },
      items: [
        'reference/architecture/index',
        {
          type: 'category',
          label: 'Configuration',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/configuration/index',
          },
          items: [
            'reference/configuration/templates',
            'reference/configuration/defaults',
          ],
        },
        {
          type: 'category',
          label: 'Context',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/context/index',
          },
          items: [
            'reference/context/field-references',
            'reference/context/context-scope',
            'reference/context/seed-data',
          ],
        },
        {
          type: 'category',
          label: 'Data I/O',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/data-io/index',
          },
          items: [
            'reference/data-io/input-formats',
            'reference/data-io/output-format',
            'reference/data-io/data-lineage',
            'reference/data-io/chunking',
          ],
        },
        {
          type: 'category',
          label: 'Prompts',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/prompts/index',
          },
          items: [
            'reference/prompts/prompt-store',
          ],
        },
        'reference/schemas/index',
        {
          type: 'category',
          label: 'Execution',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/execution/index',
          },
          items: [
            'reference/execution/guards',
            'reference/execution/artifacts',
            'reference/execution/context-handling',
            'reference/execution/run-modes',
            'reference/execution/granularity',
            'reference/execution/workflow-dependencies',
          ],
        },
        {
          type: 'category',
          label: 'Validation',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/validation/index',
          },
          items: [
            'reference/validation/reprompting',
            'reference/validation/output-validation',
          ],
        },
        {
          type: 'category',
          label: 'Tools',
          collapsed: false,
          collapsible: false,
          link: {
            type: 'doc',
            id: 'reference/tools/index',
          },
          items: [
            'reference/tools/udf-decorator',
          ],
        },
        'reference/documentation-site',
        'reference/editor-integration',
      ],
    },
  ],
};

export default sidebars;
