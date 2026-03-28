/**
 * Centralized data-card utilities — shared field classification, metadata
 * filtering, and value formatting for Table view, Card view, and (via
 * mirrored Python constants) the HITL approval UI and LSP hover.
 *
 * Single source of truth for which fields are "metadata" vs "content".
 */

// ── Metadata keys (mirrored in agent_actions/tooling/rendering/data_card.py) ──
export const METADATA_KEYS = new Set([
  "source_guid",
  "lineage",
  "node_id",
  "metadata",
  "target_id",
  "parent_target_id",
  "root_target_id",
  "chunk_info",
  "_recovery",
  "_unprocessed",
  "_file",
])

// Keys surfaced in the card header — the record's identity
export const IDENTITY_KEYS = new Set(["source_guid", "target_id"])

// Fields that contain long-form prose — rendered full-width, proportional font
const LONG_FORM_HINTS = new Set([
  "reasoning",
  "classification_reasoning",
  "description",
  "summary",
  "explanation",
  "rationale",
  "comment",
  "notes",
])

export type FieldRole = "identity" | "content" | "metadata"

export function classifyField(key: string): FieldRole {
  if (IDENTITY_KEYS.has(key)) return "identity"
  if (METADATA_KEYS.has(key)) return "metadata"
  return "content"
}

export interface ClassifiedField {
  key: string
  value: unknown
  role: FieldRole
}

/**
 * Partition a record into identity / content / metadata field groups,
 * preserving insertion order within each group.
 */
export function classifyRecord(
  record: Record<string, unknown>,
): { identity: ClassifiedField[]; content: ClassifiedField[]; metadata: ClassifiedField[] } {
  const identity: ClassifiedField[] = []
  const content: ClassifiedField[] = []
  const metadata: ClassifiedField[] = []

  for (const [key, value] of Object.entries(record)) {
    const role = classifyField(key)
    const entry = { key, value, role }
    if (role === "identity") identity.push(entry)
    else if (role === "content") content.push(entry)
    else metadata.push(entry)
  }

  return { identity, content, metadata }
}

// ── Value display helpers ──────────────────────────────────────────────────

export type ValueType = "null" | "boolean" | "number" | "object" | "string"

export function getValueType(value: unknown): ValueType {
  if (value === null || value === undefined) return "null"
  if (typeof value === "boolean") return "boolean"
  if (typeof value === "number") return "number"
  if (typeof value === "object") return "object"
  return "string"
}

/**
 * Format a value to a display string, with optional truncation.
 * Pass `maxLength: 0` for no truncation.
 */
export function formatValue(value: unknown, maxLength = 120): string {
  if (value === null || value === undefined) return "null"
  if (typeof value === "boolean") return String(value)
  if (typeof value === "number") return value.toLocaleString()
  if (typeof value === "object") {
    const str = JSON.stringify(value)
    if (maxLength > 0 && str.length > maxLength) return str.slice(0, maxLength) + "\u2026"
    return str
  }
  const str = String(value)
  if (maxLength > 0 && str.length > maxLength) return str.slice(0, maxLength) + "\u2026"
  return str
}

/** True when an array is short enough to render as inline pills. */
export function isInlineArray(value: unknown): boolean {
  if (!Array.isArray(value)) return false
  if (value.length === 0 || value.length > 3) return false
  return value.every((v) => typeof v === "string" || typeof v === "number")
}

/** True when a field key hints at long-form prose content. */
export function isLongFormField(key: string): boolean {
  const lower = key.toLowerCase()
  for (const hint of LONG_FORM_HINTS) {
    if (lower === hint || lower.endsWith("_" + hint)) return true
  }
  return false
}

/** True when a string value is short enough for inline display. */
export function isShortValue(value: unknown): boolean {
  if (typeof value !== "string") return typeof value !== "object" || value === null
  return value.length <= 80
}

/**
 * Humanize a snake_case or camelCase key into a readable label.
 */
export function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Pick the best "headline" field from a record's content fields.
 * Prefers fields named title/name/subject, then falls back to first
 * long string value.
 */
export function pickHeadlineField(
  contentFields: ClassifiedField[],
): ClassifiedField | null {
  const headlineKeys = ["title", "name", "subject", "heading", "label"]
  for (const hk of headlineKeys) {
    const found = contentFields.find(
      (f) => f.key.toLowerCase() === hk && typeof f.value === "string" && f.value.length > 0,
    )
    if (found) return found
  }
  // Fallback: first string field with >20 chars
  return (
    contentFields.find(
      (f) => typeof f.value === "string" && f.value.length > 20,
    ) ?? null
  )
}
