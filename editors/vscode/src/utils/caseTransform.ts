/**
 * Snake_case to camelCase transformation for Python API responses.
 */

export function snakeToCamel(str: string): string {
    return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

export function transformKeys<T>(obj: unknown): T {
    if (obj === null || obj === undefined) return obj as T;
    if (Array.isArray(obj)) return obj.map(transformKeys) as T;
    if (typeof obj === 'object') {
        const result: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(obj)) {
            result[snakeToCamel(key)] = transformKeys(value);
        }
        return result as T;
    }
    return obj as T;
}

/** Type-safe accessors for transformed data. */
export function getString(obj: Record<string, unknown>, key: string, fallback = ''): string {
    const val = obj[key];
    return typeof val === 'string' ? val : fallback;
}

export function getNumber(obj: Record<string, unknown>, key: string, fallback = 0): number {
    const val = obj[key];
    return typeof val === 'number' ? val : fallback;
}

export function getObject(obj: Record<string, unknown>, key: string): Record<string, unknown> {
    const val = obj[key];
    return typeof val === 'object' && val !== null && !Array.isArray(val)
        ? (val as Record<string, unknown>)
        : {};
}
