import React from "react"
import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { CatalogProvider } from "@/lib/catalog-context"
import { ThemeProvider } from "@/components/theme-provider"

import './globals.css'

const geist = Geist({
  subsets: ['latin'],
  variable: '--font-geist',
  weight: ['400', '500', '600', '700'],
})
const geistMono = Geist_Mono({
  subsets: ['latin'],
  variable: '--font-geist-mono',
  weight: ['400', '500', '600', '700'],
})

export const metadata: Metadata = {
  title: 'Agent Actions Docs',
  description: 'Navigate AI agent workflows, run history, events, and data exploration',
  icons: {
    icon: '/favicon.svg',
  },
}

export const viewport: Viewport = {
  // Painted before the stylesheet loads, so it cannot read a token. Mirrors --bg.
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#F7F7F8' },
    { media: '(prefers-color-scheme: dark)', color: '#09090B' },
  ],
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geist.variable} ${geistMono.variable} font-sans antialiased`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <CatalogProvider>{children}</CatalogProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
