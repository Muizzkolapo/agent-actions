/**
 * Maps VS Code theme tokens to HSL component variables used by shared UI
 * (query preview, DAG webview). Call `initVscodeThemeSync()` once at webview startup.
 */

function colorToHsl(raw: string): string | null {
  let r: number, g: number, b: number;
  const hex = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i);
  if (hex) {
    const h = hex[1];
    if (h.length === 3) {
      r = parseInt(h[0] + h[0], 16);
      g = parseInt(h[1] + h[1], 16);
      b = parseInt(h[2] + h[2], 16);
    } else if (h.length >= 6) {
      r = parseInt(h.slice(0, 2), 16);
      g = parseInt(h.slice(2, 4), 16);
      b = parseInt(h.slice(4, 6), 16);
    } else return null;
  } else {
    const rgb = raw.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    if (rgb) {
      r = parseInt(rgb[1], 10);
      g = parseInt(rgb[2], 10);
      b = parseInt(rgb[3], 10);
    } else return null;
  }
  const rn = r / 255,
    gn = g / 255,
    bn = b / 255;
  const max = Math.max(rn, gn, bn),
    min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  let hue = 0,
    sat = 0;
  if (max !== min) {
    const d = max - min;
    sat = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === rn) hue = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
    else if (max === gn) hue = ((bn - rn) / d + 2) / 6;
    else hue = ((rn - gn) / d + 4) / 6;
  }
  return `${Math.round(hue * 360)} ${Math.round(sat * 100)}% ${Math.round(l * 100)}%`;
}

const VSCODE_THEME_MAP: [string, ...string[]][] = [
  ["--background", "--vscode-editor-background"],
  ["--foreground", "--vscode-editor-foreground"],
  ["--card", "--vscode-editorWidget-background", "--vscode-sideBar-background", "--vscode-editor-background"],
  ["--card-foreground", "--vscode-editor-foreground"],
  ["--card-elevated", "--vscode-editorHoverWidget-background", "--vscode-tab-activeBackground", "--vscode-editorWidget-background"],
  ["--popover", "--vscode-editorWidget-background"],
  ["--popover-foreground", "--vscode-editor-foreground"],
  ["--primary", "--vscode-textLink-foreground"],
  ["--primary-foreground", "--vscode-button-foreground", "--vscode-editor-background"],
  ["--secondary", "--vscode-input-background", "--vscode-editor-background"],
  ["--secondary-foreground", "--vscode-input-foreground", "--vscode-editor-foreground"],
  ["--muted", "--vscode-input-background", "--vscode-editor-background"],
  ["--muted-foreground", "--vscode-descriptionForeground"],
  ["--accent", "--vscode-list-hoverBackground", "--vscode-editor-background"],
  ["--accent-foreground", "--vscode-editor-foreground"],
  ["--destructive", "--vscode-errorForeground"],
  ["--border", "--vscode-panel-border", "--vscode-editorWidget-border"],
  ["--border-strong", "--vscode-contrastBorder", "--vscode-panel-border"],
  ["--input", "--vscode-input-background"],
  ["--ring", "--vscode-focusBorder"],
  ["--success", "--vscode-testing-iconPassed", "--vscode-debugIcon-startForeground"],
  ["--warning", "--vscode-editorWarning-foreground"],
];

function syncVscodeTheme() {
  const cs = getComputedStyle(document.documentElement);
  const el = document.documentElement;
  for (const [target, ...sources] of VSCODE_THEME_MAP) {
    for (const src of sources) {
      const raw = cs.getPropertyValue(src).trim();
      if (raw) {
        const hsl = colorToHsl(raw);
        if (hsl) {
          el.style.setProperty(target, hsl);
          break;
        }
      }
    }
  }
  const isDark =
    document.body.classList.contains("vscode-dark") ||
    document.body.classList.contains("vscode-high-contrast");
  el.style.setProperty("color-scheme", isDark ? "dark" : "light");
}

let observerInstalled = false;

export function initVscodeThemeSync(): void {
  syncVscodeTheme();
  if (observerInstalled || typeof MutationObserver === "undefined") {
    return;
  }
  observerInstalled = true;
  let lastBodyClass = document.body.className;
  let rafPending = false;
  new MutationObserver(() => {
    const cls = document.body.className;
    if (cls === lastBodyClass) return;
    lastBodyClass = cls;
    if (!rafPending) {
      rafPending = true;
      requestAnimationFrame(() => {
        rafPending = false;
        syncVscodeTheme();
      });
    }
  }).observe(document.body, {
    attributes: true,
    attributeFilter: ["class"],
  });
}
