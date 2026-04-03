"use client"

import { useMemo } from "react"
import {
  Home,
  GitBranch,
  Play,
  Database,
  FileCode,
  MessageSquare,
  Wrench,
  ScrollText,
  Search,
  Boxes,
} from "lucide-react"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
  SidebarSeparator,
} from "@/components/ui/sidebar"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { useCatalogData } from "@/lib/catalog-context"
import { ThemeToggleSidebar } from "@/components/theme-toggle"

interface AppSidebarProps {
  activeSection: string
  onNavigate: (section: string) => void
  onSearchClick?: () => void
}

export function AppSidebar({ activeSection, onNavigate, onSearchClick }: AppSidebarProps) {
  const { stats, runs, generatedAt } = useCatalogData()

  const mainNav = useMemo(() => [
    { label: "Home", icon: Home, id: "home" },
    { label: "Workflows", icon: GitBranch, id: "workflows", badge: String(stats.total_workflows) },
    { label: "All Actions", icon: Boxes, id: "actions", badge: String(stats.total_actions) },
    { label: "Runs", icon: Play, id: "runs", badge: String(runs.length) },
    { label: "Data", icon: Database, id: "data" },
  ], [stats, runs])

  const catalogNav = [
    { label: "Schemas", icon: FileCode, id: "schemas" },
    { label: "Prompts", icon: MessageSquare, id: "prompts" },
    { label: "Tools", icon: Wrench, id: "tools" },
  ]

  const systemNav = useMemo(() => [
    { label: "Logs", icon: ScrollText, id: "logs", badge: String(stats.validation_errors) },
  ], [stats])

  const generatedDate = generatedAt ? generatedAt.split("T")[0] : ""
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-3 py-4">
        <div className="flex items-center gap-2.5 group-data-[collapsible=icon]:justify-center">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg overflow-hidden" style={{ background: '#111520' }}>
            <svg width="22" height="22" viewBox="-2 10 100 80" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="8" y="20" width="13" height="54" rx="4" fill="#94a3b8" transform="rotate(-30 14 68)"/>
              <rect x="28" y="22" width="13" height="56" rx="4" fill="#e2e8f0" opacity="0.5" transform="rotate(-15 34 76)"/>
              <rect x="50" y="22" width="13" height="60" rx="4" fill="#e2e8f0" opacity="0.7" transform="rotate(-5 56 80)"/>
              <rect x="72" y="18" width="15" height="68" rx="4" fill="#e2e8f0"/>
            </svg>
          </div>
          <div className="flex flex-col group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold tracking-tight text-foreground">Agent Actions</span>
            <span className="text-[10px] text-muted-foreground tracking-wide uppercase">Documentation</span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup className="group-data-[collapsible=icon]:hidden px-3 py-0">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search..."
              className="h-8 bg-secondary border-0 pl-8 text-xs placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-[hsl(var(--ring))] cursor-pointer"
              readOnly
              onClick={onSearchClick}
              onFocus={(e) => { e.target.blur(); onSearchClick?.() }}
            />
            <kbd className="absolute right-2 top-1.5 pointer-events-none hidden h-5 select-none items-center gap-1 rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground sm:flex">
              /
            </kbd>
          </div>
        </SidebarGroup>

        <SidebarSeparator className="group-data-[collapsible=icon]:hidden" />

        <SidebarGroup>
          <SidebarGroupLabel className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Navigate</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {mainNav.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton
                    isActive={activeSection === item.id}
                    onClick={() => onNavigate(item.id)}
                    tooltip={item.label}
                    className="h-8"
                  >
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                    {item.badge && (
                      <Badge
                        variant="secondary"
                        className="ml-auto h-5 min-w-5 justify-center rounded-md bg-secondary text-[10px] text-muted-foreground font-normal border-0"
                      >
                        {item.badge}
                      </Badge>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Catalog</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {catalogNav.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton
                    isActive={activeSection === item.id}
                    onClick={() => onNavigate(item.id)}
                    tooltip={item.label}
                    className="h-8"
                  >
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">System</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {systemNav.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton
                    isActive={activeSection === item.id}
                    onClick={() => onNavigate(item.id)}
                    tooltip={item.label}
                    className="h-8"
                  >
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                    {item.badge && (
                      <Badge
                        variant="destructive"
                        className="ml-auto h-5 min-w-5 justify-center rounded-md text-[10px] font-normal border-0"
                      >
                        {item.badge}
                      </Badge>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="px-3 py-3">
        <div className="group-data-[collapsible=icon]:hidden">
          <ThemeToggleSidebar />
        </div>
        <div className="group-data-[collapsible=icon]:hidden rounded-lg border border-border bg-secondary/30 px-3 py-2.5 mt-1">
          <div className="flex items-center gap-2">
            <div className="relative">
              <div className="h-2 w-2 rounded-full bg-[hsl(var(--success))]" />
              <div className="absolute inset-0 h-2 w-2 rounded-full bg-[hsl(var(--success))] animate-breathe" />
            </div>
            <span className="text-[11px] text-muted-foreground">All systems operational</span>
          </div>
          <div className="flex items-center gap-3 mt-2 pt-2 border-t border-border/50">
            <span className="text-[10px] font-mono text-muted-foreground/60">generated {generatedDate}</span>
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
