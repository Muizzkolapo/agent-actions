import type {PrismTheme} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// Custom agac instrument palette — high-contrast dark theme on #0d1115.
// Each token type uses a distinct hue so they're visually separable at a glance.
// prism-react-renderer applies inline styles, so CSS overrides don't work.
const agacPrismTheme: PrismTheme = {
  plain: {
    color: '#e2e8ec',           // bright cool white — default/fallback text
    backgroundColor: '#1a2028',
  },
  styles: [
    { types: ['comment', 'prolog', 'doctype', 'cdata'], style: { color: '#6e7a81', fontStyle: 'italic' as const } },
    { types: ['keyword', 'boolean', 'important', 'atrule'], style: { color: '#ff6e4a' } },   // hot coral — commands/keywords
    { types: ['string', 'char', 'attr-value', 'regex', 'template-string', 'inserted', 'selector'], style: { color: '#5ef0a6' } },  // vivid mint green — strings
    { types: ['number'], style: { color: '#6eb8ff' } },           // sky blue — numbers
    { types: ['function', 'builtin'], style: { color: '#c9a0ff' } },  // lavender — functions
    { types: ['class-name', 'maybe-class-name', 'tag'], style: { color: '#ffb454' } },  // amber — types/tags
    { types: ['punctuation', 'operator', 'symbol'], style: { color: '#7c878e' } },  // muted — stays quiet
    { types: ['property', 'attr-name', 'variable', 'parameter', 'constant'], style: { color: '#5ccfe6' } },  // cyan — keys/properties (distinct from plain white)
    { types: ['deleted'], style: { color: '#ff5a68' } },
    { types: ['changed'], style: { color: '#ffb454' } },
  ],
};

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Agent Actions',
  tagline: 'YAML-native multi-agent DAG workflows with schema-first validation',
  favicon: 'img/favicon.svg',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Enable Mermaid diagrams
  markdown: {
    mermaid: true,
  },
  themes: [
    '@docusaurus/theme-mermaid',
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        indexBlog: false,
        docsRouteBasePath: '/docs',
        highlightSearchTermsOnTargetPage: true,
        searchResultLimits: 8,
        explicitSearchResultPath: true,
      },
    ],
  ],
  stylesheets: [
    {
      // agac reskin fonts: Space Grotesk (display) + Hanken Grotesk (body) + JetBrains Mono (data)
      href: 'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Hanken+Grotesk:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap',
      type: 'text/css',
    },
  ],

  // Set the production url of your site here
  url: 'https://docs.runagac.com',
  // Custom domain — baseUrl is root when using a custom domain
  baseUrl: '/',

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'Muizzkolapo', // Usually your GitHub org/user name.
  projectName: 'agent-actions', // Usually your repo name.

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/Muizzkolapo/agent-actions/tree/main/agentaction-docs/',
        },
        blog: {
          showReadingTime: true,
          feedOptions: {
            type: ['rss', 'atom'],
            xslt: true,
          },
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/Muizzkolapo/agent-actions/tree/main/agentaction-docs/',
          // Useful options to enforce blogging best practices
          onInlineTags: 'warn',
          onInlineAuthors: 'warn',
          onUntruncatedBlogPosts: 'warn',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // Replace with your project's social card
    image: 'img/social-card.jpg',

    // Enable light/dark mode toggle
    colorMode: {
      defaultMode: 'dark',
      // Static design is dark-first; light is tuned to match its light tokens.
      disableSwitch: false,
      respectPrefersColorScheme: false,
    },

    // Table of contents settings
    tableOfContents: {
      minHeadingLevel: 2,
      maxHeadingLevel: 4,
    },

    navbar: {
      title: 'agent-actions',
      logo: {
        alt: 'Agent Actions Logo',
        src: 'img/logo-mark-light.svg',
        srcDark: 'img/logo-mark-dark.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Documentation',
        },
        {
          href: 'https://github.com/Muizzkolapo/agent-actions',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      /* style: 'light' — footer colors are fully controlled by custom.css
         using theme-aware CSS vars. Avoid 'dark' which injects Infima's
         forced-dark overrides that collide with our custom tokens. */
      style: 'light',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Quick Start',
              to: '/docs/',
            },
            {
              label: 'Key Concepts',
              to: '/docs/tutorials/concepts',
            },
            {
              label: 'Design Patterns',
              to: '/docs/guides/design-patterns',
            },
            {
              label: 'CLI Reference',
              to: '/docs/reference/cli',
            },
          ],
        },
        {
          title: 'Project',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/Muizzkolapo/agent-actions',
            },
            {
              label: 'Issues',
              href: 'https://github.com/Muizzkolapo/agent-actions/issues',
            },
            {
              label: 'Changelog',
              href: 'https://github.com/Muizzkolapo/agent-actions/releases',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'Discussions',
              href: 'https://github.com/Muizzkolapo/agent-actions/discussions',
            },
            {
              label: 'Contributing',
              href: 'https://github.com/Muizzkolapo/agent-actions/blob/main/CONTRIBUTING.md',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Agent Actions.`,
    },
    prism: {
      // Both themes use the agac instrument palette — code blocks are always-dark
      theme: agacPrismTheme,
      darkTheme: agacPrismTheme,
    },
    mermaid: {
      theme: {
        light: 'neutral',
        dark: 'dark',
      },
      options: {
        fontFamily: '"Space Grotesk", system-ui, sans-serif',
        fontSize: 15,
        flowchart: {
          curve: 'basis',
          padding: 20,
          nodeSpacing: 60,
          rankSpacing: 60,
          htmlLabels: true,
          useMaxWidth: false,
        },
      },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
