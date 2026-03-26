import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

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
  themes: ['@docusaurus/theme-mermaid'],
  stylesheets: [
    {
      href: 'https://fonts.googleapis.com/css2?family=Lexend+Deca:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap',
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
      style: 'dark',
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
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    mermaid: {
      theme: {
        light: 'neutral',
        dark: 'dark',
      },
      options: {
        fontFamily: '"Space Grotesk", "Inter", -apple-system, sans-serif',
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
