"use client"

import { useMemo } from "react"
import {
  Home,
  GitBranch,
  Boxes,
  Play,
  Database,
  FileCode,
  MessageSquare,
  Wrench,
  ScrollText,
  Search,
  type LucideIcon,
} from "lucide-react"
import { Logo } from "@/components/logo"
import { useCatalogData } from "@/lib/catalog-context"
import { deriveHealth } from "@/lib/health"

interface NavItem {
  id: string
  label: string
  icon: LucideIcon
  badge?: string
  badgeTitle?: string
}

interface AppSidebarProps {
  activeSection: string
  collapsed: boolean
  onNavigate: (section: string) => void
  onSearchClick: () => void
  onShowErrors: () => void
  projectName: string
}

/**
 * Sized so all nine nav items fit at 100vh without scrolling. Adding a row means
 * removing height elsewhere — rows below 30px are already tight for a touch target.
 */
export function AppSidebar({
  activeSection,
  collapsed,
  onNavigate,
  onSearchClick,
  onShowErrors,
  projectName,
}: AppSidebarProps) {
  const data = useCatalogData()
  const { stats, runs } = data
  const health = useMemo(() => deriveHealth(data), [data])

  const navMain: NavItem[] = [
    { id: "home", label: "Home", icon: Home },
    { id: "workflows", label: "Workflows", icon: GitBranch, badge: String(stats.total_workflows) },
    { id: "actions", label: "All actions", icon: Boxes, badge: String(stats.total_actions) },
    { id: "runs", label: "Runs", icon: Play, badge: String(runs.length) },
    { id: "data", label: "Data", icon: Database },
  ]
  const navCatalog: NavItem[] = [
    { id: "schemas", label: "Schemas", icon: FileCode },
    { id: "prompts", label: "Prompts", icon: MessageSquare },
    { id: "tools", label: "Tools", icon: Wrench },
  ]

  return (
    <div
      className="flex shrink-0 flex-col overflow-hidden border-r border-border bg-background transition-[width] duration-200"
      style={{ width: collapsed ? 60 : 252 }}
    >
      <div className="shrink-0 px-3.5 pb-2.5 pt-3.5">
        <button
          onClick={() => onNavigate("home")}
          className="flex w-full items-center gap-2.5 text-left hover:opacity-80"
        >
          <Logo />
          {!collapsed && (
            <span className="flex min-w-0 flex-col whitespace-nowrap">
              <span className="text-[13.5px] font-semibold tracking-[-0.01em] text-foreground">
                Agent Actions
              </span>
              <span className="truncate font-mono text-xs text-muted-foreground">{projectName}</span>
            </span>
          )}
        </button>
      </div>

      {!collapsed && (
        <div className="shrink-0 px-3.5 pb-2">
          <button
            onClick={onSearchClick}
            className="relative flex h-8 w-full items-center justify-between whitespace-nowrap rounded-control border border-border-soft bg-surface-2 pl-7 pr-[7px] text-xs text-muted-foreground hover:border-border-2 hover:text-foreground-3"
          >
            <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5" strokeWidth={1.9} />
            <span>Jump to…</span>
            <kbd className="rounded-sm border border-border bg-surface px-1.5 font-mono text-[10px] leading-[16px] text-muted-foreground">
              ⌘K
            </kbd>
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden px-2.5 py-1">
        <NavGroup label="Navigate" collapsed={collapsed}>
          {navMain.map((item) => (
            <NavButton
              key={item.id}
              item={item}
              active={activeSection === item.id}
              collapsed={collapsed}
              onClick={() => onNavigate(item.id)}
            />
          ))}
        </NavGroup>

        <NavGroup label="Catalog" collapsed={collapsed}>
          {navCatalog.map((item) => (
            <NavButton
              key={item.id}
              item={item}
              active={activeSection === item.id}
              collapsed={collapsed}
              onClick={() => onNavigate(item.id)}
            />
          ))}
        </NavGroup>

        <NavGroup label="System" collapsed={collapsed}>
          <NavButton
            item={{
              id: "logs",
              label: "Logs",
              icon: ScrollText,
              badge: health.errors > 0 ? health.errors.toLocaleString() : undefined,
              badgeTitle: "Problems needing attention — not the same count as the event stream's error rows",
            }}
            active={activeSection === "logs"}
            collapsed={collapsed}
            onClick={() => onNavigate("logs")}
            alarmBadge
          />
        </NavGroup>
      </div>

      <div className="shrink-0 px-3.5 pb-3 pt-2">
        <button
          onClick={health.errors > 0 ? onShowErrors : () => onNavigate("logs")}
          className="flex h-8 w-full items-center gap-2 rounded-control border border-border bg-surface px-2.5 text-left hover:bg-hover"
          title={
            health.errors > 0
              ? "Failed runs and actions plus validation findings. The Logs page counts event rows by level, so its total differs."
              : "Open Logs"
          }
        >
          <span
            className={`h-[7px] w-[7px] shrink-0 rounded-pill ${
              health.errors > 0 ? "bg-danger" : "bg-success"
            }`}
          />
          {!collapsed && (
            <span
              className={`truncate whitespace-nowrap text-xs font-medium ${
                health.errors > 0 ? "text-danger-t" : "text-foreground-3"
              }`}
            >
              {health.errors > 0
                ? `${health.errors.toLocaleString()} error${health.errors === 1 ? "" : "s"} need attention`
                : "All systems operational"}
            </span>
          )}
        </button>
      </div>
    </div>
  )
}

function NavGroup({
  label,
  collapsed,
  children,
}: {
  label: string
  collapsed: boolean
  children: React.ReactNode
}) {
  return (
    <div>
      {!collapsed && (
        <div className="whitespace-nowrap px-2.5 pb-[5px] pt-[3px] text-xs font-medium text-muted-2">
          {label}
        </div>
      )}
      {children}
    </div>
  )
}

function NavButton({
  item,
  active,
  collapsed,
  onClick,
  alarmBadge = false,
}: {
  item: NavItem
  active: boolean
  collapsed: boolean
  onClick: () => void
  alarmBadge?: boolean
}) {
  const Icon = item.icon
  return (
    <button
      onClick={onClick}
      title={item.label}
      className={`mb-px flex h-8 w-full items-center gap-2.5 rounded-control px-2.5 text-sm font-medium hover:bg-hover ${
        active ? "bg-selected text-foreground" : "text-foreground-3"
      }`}
    >
      <Icon
        className={`h-4 w-4 shrink-0 ${active ? "text-foreground" : "text-muted-foreground"}`}
        strokeWidth={1.9}
      />
      {!collapsed && <span className="flex-1 whitespace-nowrap text-left">{item.label}</span>}
      {!collapsed && item.badge && (
        <span
          title={item.badgeTitle}
          className={
            alarmBadge
              ? "shrink-0 rounded-sm bg-danger-a12 px-1.5 py-px font-mono text-[10px] text-danger-t"
              : "min-w-5 shrink-0 rounded-pill border border-border bg-surface px-[7px] text-center text-[11px] font-medium leading-[18px] text-foreground-3"
          }
        >
          {item.badge}
        </span>
      )}
    </button>
  )
}
