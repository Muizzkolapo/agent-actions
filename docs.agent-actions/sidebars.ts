import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'index',
    'installation',
    {
      type: 'category',
      label: 'Tutorials',
      collapsed: false,
      collapsible: false,
      customProps: { className: 'sidebar-item-tutorials' },
      link: {
        type: 'doc',
        id: 'tutorials/index',
      },
      items: [
        'tutorials/concepts',
      ],
    },
    {
      type: 'category',
      label: 'Guides',
      collapsed: false,
      collapsible: false,
      customProps: { className: 'sidebar-item-guides' },
      link: {
        type: 'doc',
        id: 'guides/index',
      },
      items: [
        'guides/design-patterns',
        'guides/custom-tools',
        'guides/human-in-the-loop',
        'guides/editor-setup',
        'guides/troubleshooting',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      collapsed: false,
      collapsible: false,
      customProps: { className: 'sidebar-item-reference' },
      link: {
        type: 'doc',
        id: 'reference/index',
      },
      items: [
        {
          type: 'category',
          label: 'CLI',
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-cli' },
          link: {
            type: 'doc',
            id: 'reference/cli/index',
          },
          items: [
            'reference/cli/run',
            'reference/cli/batch',
            'reference/cli/inspect',
            'reference/cli/utilities',
            'reference/cli/preview',
            'reference/cli/tools',
            'reference/cli/schema',
            'reference/cli/skills',
            'reference/cli/troubleshooting',
          ],
        },
        {
          type: 'category',
          label: 'Configuration',
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-configuration' },
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
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-context' },
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
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-dataio' },
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
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-prompts' },
          link: {
            type: 'doc',
            id: 'reference/prompts/index',
          },
          items: [
            'reference/prompts/prompt-store',
            'reference/prompts/dispatch',
          ],
        },
        'reference/schemas/index',
        {
          type: 'category',
          label: 'Execution',
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-execution' },
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
            'reference/execution/retry',
            'reference/execution/versions',
          ],
        },
        {
          type: 'category',
          label: 'Validation',
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-validation' },
          link: {
            type: 'doc',
            id: 'reference/validation/index',
          },
          items: [
            'reference/validation/reprompting',
            'reference/validation/output-validation',
          ],
        },
        'reference/tools/index',
        {
          type: 'category',
          label: 'Architecture',
          collapsed: true,
          collapsible: true,
          customProps: { className: 'sidebar-item-architecture' },
          link: {
            type: 'doc',
            id: 'reference/architecture/index',
          },
          items: [
            'reference/architecture/internal-defaults',
            'reference/architecture/logging',
          ],
        },
        'reference/inspect',
        'reference/documentation-site',
      ],
    },
    {
      type: 'category',
      label: 'API',
      collapsed: false,
      collapsible: false,
      customProps: { className: 'sidebar-item-api' },
      link: {
        type: 'doc',
        id: 'api/index',
      },
      items: [
        'api/logging',
      ],
    },
  ],
};

export default sidebars;
