import type { Config } from 'tailwindcss'

// Graphite design tokens live in app/globals.css. Names here map 1:1 onto them,
// except where a shadcn/ui name already covers the same token:
//   --bg → background   --surface → card   --text → foreground
//   --muted → muted-foreground   --hover → accent   --border-input → input
const config: Config = {
  darkMode: ['class'],
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    '*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-geist)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-geist-mono)', 'ui-monospace', 'monospace'],
      },
      colors: {
        background: 'hsl(var(--background) / <alpha-value>)',
        foreground: 'hsl(var(--foreground) / <alpha-value>)',
        card: {
          DEFAULT: 'hsl(var(--card) / <alpha-value>)',
          foreground: 'hsl(var(--card-foreground) / <alpha-value>)',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover) / <alpha-value>)',
          foreground: 'hsl(var(--popover-foreground) / <alpha-value>)',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary) / <alpha-value>)',
          foreground: 'hsl(var(--primary-foreground) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary) / <alpha-value>)',
          foreground: 'hsl(var(--secondary-foreground) / <alpha-value>)',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted-bg) / <alpha-value>)',
          foreground: 'hsl(var(--muted-foreground) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'hsl(var(--hover) / <alpha-value>)',
          foreground: 'hsl(var(--accent-foreground) / <alpha-value>)',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive) / <alpha-value>)',
          foreground: 'hsl(var(--destructive-foreground) / <alpha-value>)',
        },
        border: 'hsl(var(--border) / <alpha-value>)',
        input: 'hsl(var(--input) / <alpha-value>)',
        ring: 'hsl(var(--ring) / <alpha-value>)',
        chart: {
          '1': 'hsl(var(--chart-1) / <alpha-value>)',
          '2': 'hsl(var(--chart-2) / <alpha-value>)',
          '3': 'hsl(var(--chart-3) / <alpha-value>)',
          '4': 'hsl(var(--chart-4) / <alpha-value>)',
          '5': 'hsl(var(--chart-5) / <alpha-value>)',
        },
        sidebar: {
          DEFAULT: 'hsl(var(--sidebar-background) / <alpha-value>)',
          foreground: 'hsl(var(--sidebar-foreground) / <alpha-value>)',
          primary: 'hsl(var(--sidebar-primary) / <alpha-value>)',
          'primary-foreground': 'hsl(var(--sidebar-primary-foreground) / <alpha-value>)',
          accent: 'hsl(var(--sidebar-accent) / <alpha-value>)',
          'accent-foreground': 'hsl(var(--sidebar-accent-foreground) / <alpha-value>)',
          border: 'hsl(var(--sidebar-border) / <alpha-value>)',
          ring: 'hsl(var(--sidebar-ring) / <alpha-value>)',
        },

        // Structural
        surface: 'hsl(var(--surface) / <alpha-value>)',
        'surface-2': 'hsl(var(--surface-2) / <alpha-value>)',
        well: 'hsl(var(--well) / <alpha-value>)',
        hover: 'hsl(var(--hover) / <alpha-value>)',
        selected: 'hsl(var(--selected) / <alpha-value>)',
        grid: 'hsl(var(--grid) / <alpha-value>)',
        track: 'hsl(var(--track) / <alpha-value>)',
        'foreground-2': 'hsl(var(--text-2) / <alpha-value>)',
        'foreground-3': 'hsl(var(--text-3) / <alpha-value>)',
        'muted-2': 'hsl(var(--muted-2) / <alpha-value>)',
        'border-2': 'hsl(var(--border-2) / <alpha-value>)',
        'border-soft': 'hsl(var(--border-soft) / <alpha-value>)',
        'primary-hover': 'hsl(var(--primary-hover) / <alpha-value>)',
        'on-primary': 'hsl(var(--on-primary) / <alpha-value>)',

        // Graphite accent — interactive, selected, focused
        'accent-t': 'hsl(var(--accent-t) / <alpha-value>)',
        'accent-bright': 'hsl(var(--accent-bright) / <alpha-value>)',
        'accent-a12': 'hsl(var(--accent-a12) / <alpha-value>)',
        'accent-a30': 'hsl(var(--accent-a30) / <alpha-value>)',
        'accent-soft-a50': 'hsl(var(--accent-soft-a50) / <alpha-value>)',
        'accent-soft-a70': 'hsl(var(--accent-soft-a70) / <alpha-value>)',

        // Status — base tokens are fills, `-t` variants are the text-safe pairs
        info: 'hsl(var(--info) / <alpha-value>)',
        'info-t': 'hsl(var(--info-t) / <alpha-value>)',
        'info-a12': 'hsl(var(--info-a12) / <alpha-value>)',
        success: 'hsl(var(--success) / <alpha-value>)',
        'success-t': 'hsl(var(--success-t) / <alpha-value>)',
        'success-a12': 'hsl(var(--success-a12) / <alpha-value>)',
        warning: 'hsl(var(--warning) / <alpha-value>)',
        'warning-t': 'hsl(var(--warning-t) / <alpha-value>)',
        'warning-a12': 'hsl(var(--warning-a12) / <alpha-value>)',
        danger: 'hsl(var(--danger) / <alpha-value>)',
        'danger-t': 'hsl(var(--danger-t) / <alpha-value>)',
        'danger-a12': 'hsl(var(--danger-a12) / <alpha-value>)',
        'danger-fill': 'hsl(var(--danger-fill) / <alpha-value>)',
        'on-danger': 'hsl(var(--on-danger) / <alpha-value>)',

        // Category series — charts and type tags only
        llm: 'hsl(var(--llm) / <alpha-value>)',
        'llm-t': 'hsl(var(--llm-t) / <alpha-value>)',
        tool: 'hsl(var(--tool) / <alpha-value>)',
        'tool-t': 'hsl(var(--tool-t) / <alpha-value>)',
        'type-array': 'hsl(var(--type-array) / <alpha-value>)',
        'type-object': 'hsl(var(--type-object) / <alpha-value>)',
      },
      borderRadius: {
        control: '6px',
        card: '10px',
        pill: '9999px',
        sm: '4px',
        md: '6px',
        lg: '10px',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
        'collapsible-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-collapsible-content-height)' },
        },
        'collapsible-up': {
          from: { height: 'var(--radix-collapsible-content-height)' },
          to: { height: '0' },
        },
        'fade-in-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'view-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'none' },
        },
        'panel-in': {
          from: { opacity: '0', transform: 'translateX(14px)' },
          to: { opacity: '1', transform: 'none' },
        },
        'item-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'none' },
        },
        breathe: {
          '0%, 100%': { opacity: '0.45', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.3)' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'collapsible-down': 'collapsible-down 0.2s ease-out',
        'collapsible-up': 'collapsible-up 0.2s ease-out',
        'fade-in-up': 'fade-in-up 0.32s cubic-bezier(0.22,0.8,0.26,1) both',
        'view-in': 'view-in 0.32s cubic-bezier(0.22,0.8,0.26,1) both',
        'panel-in': 'panel-in 0.28s cubic-bezier(0.22,0.8,0.26,1) both',
        'item-in': 'item-in 0.34s cubic-bezier(0.22,0.8,0.26,1) both',
        breathe: 'breathe 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [require('tailwindcss-animate'), require('@tailwindcss/typography')],
}
export default config
