import type { CatalogData } from "./transformers"
import type { ValidationGroup } from "./mock-data"

export interface HealthSummary {
  errors: number
  warnings: number
  total: number
  errorGroups: ValidationGroup[]
  warningGroups: ValidationGroup[]
}

function sum(groups: ValidationGroup[]): number {
  return groups.reduce((n, g) => n + g.count, 0)
}

/**
 * Problems worth acting on: schema validation findings, plus the runs and
 * actions that failed. Home's health card and the sidebar badge both read this,
 * so those two always agree.
 *
 * This is deliberately NOT the Logs page's population. Logs counts rows in the
 * event stream by level; this counts distinct problems, drawn partly from run
 * records that are not log rows at all. The two numbers differ on a healthy
 * project and both are right — which is why each names what it counts on screen
 * rather than being labelled "errors" twice.
 */
export function deriveHealth(data: CatalogData): HealthSummary {
  const errorGroups = [...data.validationErrorGroups, ...data.runtimeErrorGroups]
  const warningGroups = [...data.validationWarningGroups, ...data.runtimeWarningGroups]
  const errors = sum(errorGroups)
  const warnings = sum(warningGroups)
  return { errors, warnings, total: errors + warnings, errorGroups, warningGroups }
}
