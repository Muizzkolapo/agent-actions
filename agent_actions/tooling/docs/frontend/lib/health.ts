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
 * Home's health card, the sidebar Logs badge and the Logs header stats all read
 * this. Counting the same groups the Logs page lists is what keeps them from
 * drifting apart — a monitoring dashboard that contradicts itself is worse than
 * one that shows nothing.
 */
export function deriveHealth(data: CatalogData): HealthSummary {
  const errorGroups = [...data.validationErrorGroups, ...data.runtimeErrorGroups]
  const warningGroups = [...data.validationWarningGroups, ...data.runtimeWarningGroups]
  const errors = sum(errorGroups)
  const warnings = sum(warningGroups)
  return { errors, warnings, total: errors + warnings, errorGroups, warningGroups }
}
