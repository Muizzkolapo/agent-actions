import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { DataCard, type ActionInfo } from "@/components/ui/data-card";

// Webview entry — mounts the docs DataCard and pushes records straight
// through. Only navigational chrome and integrity diagnostics are added
// here; record content is never aggregated or filtered.

declare global {
  interface Window {
    acquireVsCodeApi: () => {
      postMessage: (msg: unknown) => void;
      getState: () => unknown;
      setState: (state: unknown) => void;
    };
    __INITIAL_PREVIEW__?: PreviewPayload;
  }
}

interface PreviewPayload {
  records: unknown[];
  totalCount: number;
  nodeName: string;
  files: string[];
  storagePath: string;
  backendType: string;
  workflowName: string;
  workflowPath: string;
  limit: number;
  offset: number;
  actionInfo?: ActionInfo;
  /** Set when host detects records.length disagrees with backend-reported
   * totalCount (either direction). The masthead chip surfaces the lie so
   * we don't paper over stale storage counts. */
  countDrift?: { reported: number; actual: number };
}

const vscode = window.acquireVsCodeApi();

const Tick = () => <span className="toolbar-tick" aria-hidden>│</span>;

function App({ initial }: { initial: PreviewPayload }) {
  const [data, setData] = useState<PreviewPayload>(initial);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const msg = event.data;
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "preview:update" && msg.payload) {
        setData(msg.payload as PreviewPayload);
      }
    };
    window.addEventListener("message", handler);
    vscode.postMessage({ type: "ready" });
    return () => window.removeEventListener("message", handler);
  }, []);

  // When the backend lies about totalCount (e.g., stale record_count
  // column in target_data), trust records.length for the page-end so the
  // displayed range never reads "1–0 / 0" while the drift chip warns.
  const observedTotal = Math.max(data.totalCount, data.offset + data.records.length);
  const pageStart = data.offset + 1;
  const pageEnd = data.offset + data.records.length;
  const totalPages = Math.max(1, Math.ceil(observedTotal / Math.max(1, data.limit)));
  const currentPage = Math.floor(data.offset / Math.max(1, data.limit)) + 1;
  const canPrev = data.offset > 0;
  const canNext = data.offset + data.records.length < data.totalCount;

  const annotated = useMemo(
    () =>
      data.records.map((r, i) => {
        const obj = (typeof r === "object" && r !== null ? r : {}) as Record<string, unknown>;
        const idHint =
          (typeof obj.target_id === "string" && obj.target_id) ||
          (typeof obj.source_guid === "string" && obj.source_guid) ||
          "rec";
        return {
          record: obj,
          key: `${idHint}::${data.offset + i}`,
          index: data.offset + i + 1,
        };
      }),
    [data.records, data.offset],
  );

  return (
    <div className="min-h-screen">
      {/* ── Masthead ─────────────────────────────────────────────────── */}
      <header
        className="sticky top-0 z-10 border-b"
        style={{
          background: "var(--vscode-editor-background)",
          borderColor: "hsl(var(--border) / 0.55)",
        }}
      >
        <div className="flex items-center gap-2 px-3 py-1.5 flex-wrap min-h-[34px]">
          <span className="toolbar-action truncate">{data.nodeName}</span>

          {data.workflowName && (
            <>
              <Tick />
              <span className="toolbar-chip truncate" title={data.workflowName}>
                {data.workflowName}
              </span>
            </>
          )}

          <Tick />
          <span className="toolbar-meta tabular-nums">
            {data.totalCount.toLocaleString()} rec
          </span>

          {data.countDrift && (
            <span
              className="drift-chip"
              role="alert"
              title={
                `Storage reported ${data.countDrift.reported.toLocaleString()} record` +
                (data.countDrift.reported === 1 ? "" : "s") +
                ` but ${data.countDrift.actual.toLocaleString()} were returned. ` +
                `target_data.record_count column is likely stale relative to the JSON data array. ` +
                `Showing all returned records.`
              }
            >
              <span className="drift-mark" aria-hidden>⚠</span>
              <span>
                count drift{" "}
                <span className="tabular-nums">
                  {data.countDrift.reported.toLocaleString()} → {data.countDrift.actual.toLocaleString()}
                </span>
              </span>
            </span>
          )}

          {data.backendType && (
            <>
              <Tick />
              <span className="toolbar-meta">{data.backendType}</span>
            </>
          )}

          <div className="ml-auto flex items-center gap-1.5">
            <span className="toolbar-pageinfo tabular-nums" aria-live="polite">
              <span className="opacity-50">{pageStart}</span>
              <span className="opacity-30 mx-[2px]">–</span>
              <span className="opacity-50">{pageEnd}</span>
              <span className="mx-[6px] opacity-30">/</span>
              <span>{observedTotal.toLocaleString()}</span>
            </span>
            <Tick />
            <span className="toolbar-meta tabular-nums" title={`Page ${currentPage} of ${totalPages}`}>
              p{currentPage}/{totalPages}
            </span>
            <button
              type="button"
              className="nav-btn"
              disabled={!canPrev}
              onClick={() => vscode.postMessage({ type: "paginate", direction: "previous" })}
              aria-label="Previous page"
              title="Previous page"
            >
              ‹
            </button>
            <button
              type="button"
              className="nav-btn"
              disabled={!canNext}
              onClick={() => vscode.postMessage({ type: "paginate", direction: "next" })}
              aria-label="Next page"
              title="Next page"
            >
              ›
            </button>
          </div>
        </div>
      </header>

      {/* ── Records ──────────────────────────────────────────────────── */}
      <main className="px-3 py-3">
        <div className="flex flex-col gap-2">
          {annotated.map(({ record, key, index }, i) => (
            <DataCard
              key={key}
              record={record}
              index={index}
              defaultOpen={i === 0}
              actionInfo={data.actionInfo}
            />
          ))}
        </div>

        {annotated.length === 0 && (
          <div className="empty-state">no records · 0 returned</div>
        )}
      </main>
    </div>
  );
}

/* ── VS Code theme sync ──────────────────────────────────────────────── */
// Reads VS Code's native CSS variables (auto-updated on theme change) and
// converts them to HSL component format so our variable-based CSS adapts
// to any installed theme — light, dark, or high-contrast.

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

// Run immediately; re-sync when VS Code flips the body class on theme change.
syncVscodeTheme();
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

/* ── Bootstrap ───────────────────────────────────────────────────────── */

const initial: PreviewPayload = window.__INITIAL_PREVIEW__ ?? {
  records: [],
  totalCount: 0,
  nodeName: "",
  files: [],
  storagePath: "",
  backendType: "",
  workflowName: "",
  workflowPath: "",
  limit: 50,
  offset: 0,
};

function showFatal(err: unknown) {
  const msg = err instanceof Error ? err.stack || err.message : String(err);
  const el = document.getElementById("root");
  if (el) {
    el.innerHTML =
      '<pre style="color:#f88;background:#222;padding:16px;font-family:monospace;font-size:12px;white-space:pre-wrap;border-radius:6px;margin:16px;">' +
      msg.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c]!) +
      "</pre>";
  }
}

window.addEventListener("error", (ev) => showFatal(ev.error || ev.message));
window.addEventListener("unhandledrejection", (ev) => showFatal(ev.reason));

try {
  const root = createRoot(document.getElementById("root")!);
  root.render(<App initial={initial} />);
} catch (e) {
  showFatal(e);
}
