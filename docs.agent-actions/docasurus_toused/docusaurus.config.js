// @ts-check
// Docusaurus Configuration for Charcoal/Black Minimalist Theme

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Your Tool',
  tagline: 'Build faster, ship cleaner',
  favicon: 'img/favicon.ico',

  url: 'https://your-tool.dev',
  baseUrl: '/',

  organizationName: 'your-org',
  projectName: 'your-tool',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  // Add custom fonts
  stylesheets: [
    {
      href: 'https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,300;8..60,400;8..60,600&family=JetBrains+Mono:wght@400;500&family=Instrument+Sans:wght@400;500;600&display=swap',
      type: 'text/css',
    },
  ],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl: 'https://github.com/your-org/your-tool/tree/main/',
          // Use docs as the landing page
          routeBasePath: '/',
        },
        blog: {
          showReadingTime: true,
          editUrl: 'https://github.com/your-org/your-tool/tree/main/',
        },
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Enable light/dark mode toggle
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
      },

      // Announcement bar (optional)
      // announcementBar: {
      //   id: 'announcement',
      //   content: 'v2.4.1 is now available',
      //   backgroundColor: '#111',
      //   textColor: '#888',
      //   isCloseable: true,
      // },

      navbar: {
        title: 'YOUR TOOL',
        logo: {
          alt: 'Your Tool Logo',
          src: 'img/logo.svg',
          srcDark: 'img/logo-dark.svg',
        },
        items: [
          {
            type: 'doc',
            docId: 'introduction',
            position: 'left',
            label: 'Docs',
          },
          {
            to: '/api',
            label: 'API',
            position: 'left',
          },
          {
            to: '/blog',
            label: 'Blog',
            position: 'left',
          },
          {
            href: 'https://github.com/your-org/your-tool/discussions',
            label: 'Community',
            position: 'left',
          },
          {
            href: 'https://github.com/your-org/your-tool',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },

      // Disable the default footer for minimal look
      // Or customize it
      footer: {
        style: 'dark',
        copyright: `© ${new Date().getFullYear()} Your Tool`,
      },

      // Table of contents settings
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 4,
      },

      // Code block theme
      prism: {
        theme: require('./src/prism-theme-light'),
        darkTheme: require('./src/prism-theme-dark'),
        additionalLanguages: ['bash', 'json', 'typescript'],
      },

      // Algolia search (optional - configure with your credentials)
      // algolia: {
      //   appId: 'YOUR_APP_ID',
      //   apiKey: 'YOUR_SEARCH_API_KEY',
      //   indexName: 'your-tool',
      //   contextualSearch: true,
      // },
    }),
};

module.exports = config;
