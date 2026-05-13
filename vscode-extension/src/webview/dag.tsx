import "@xyflow/react/dist/style.css";
import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";
import {
  adaptVsCodeDagInputsToDAGActions,
  type VsCodeDagActionInput,
} from "@/lib/dag-transformer";
import { WorkflowDAGRuntime } from "@/components/workflow-dag";
import { initVscodeThemeSync } from "./themeSync";

initVscodeThemeSync();

declare global {
  interface Window {
    acquireVsCodeApi: () => {
      postMessage: (msg: unknown) => void;
      getState: () => unknown;
      setState: (state: unknown) => void;
    };
  }
}

const vscode = window.acquireVsCodeApi();

const LARGE_NODE_THRESHOLD = 500;

interface DagUpdatePayload {
  workflowName: string;
  layout: "vertical" | "horizontal";
  actions: Array<{
    name: string;
    deps: string[];
    kind: "llm" | "tool" | "unknown";
    status?: VsCodeDagActionInput["status"];
    model?: string;
    impl?: string;
    intent?: string;
    inputs?: string[];
    observe?: string[];
    outputs?: string[];
    outputFields?: string[];
    drops?: string[];
  }>;
}

function directionFromLayout(layout: DagUpdatePayload["layout"]): "LR" | "TB" {
  return layout === "horizontal" ? "LR" : "TB";
}

function App() {
  const [payload, setPayload] = useState<DagUpdatePayload>({
    workflowName: "",
    layout: "vertical",
    actions: [],
  });

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const msg = event.data;
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "dag:update" && msg.payload) {
        setPayload(msg.payload as DagUpdatePayload);
      }
    };
    window.addEventListener("message", handler);
    vscode.postMessage({ type: "ready" });
    return () => window.removeEventListener("message", handler);
  }, []);

  const inputs: VsCodeDagActionInput[] = useMemo(
    () =>
      payload.actions.map((a) => ({
        name: a.name,
        dependencies: a.deps,
        kind: a.kind,
        status: a.status,
        model: a.model,
        impl: a.impl,
        intent: a.intent,
        inputs: a.inputs,
        observe: a.observe,
        outputs: a.outputs,
        outputFields: a.outputFields,
        drops: a.drops,
      })),
    [payload.actions],
  );

  const dagActions = useMemo(() => adaptVsCodeDagInputsToDAGActions(inputs), [inputs]);

  const isLarge = dagActions.length > LARGE_NODE_THRESHOLD;
  const direction = directionFromLayout(payload.layout);

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      {isLarge && (
        <div
          className="shrink-0 border-b px-3 py-2 text-xs"
          style={{
            borderColor: "hsl(var(--border) / 0.55)",
            background: "hsl(var(--card))",
            color: "hsl(var(--muted-foreground))",
          }}
          role="status"
        >
          Large workflow ({dagActions.length} actions). Minimap is off to keep the panel responsive.
        </div>
      )}
      <div className="min-h-0 flex-1 w-full">
        <ReactFlowProvider>
          <WorkflowDAGRuntime
            dagActions={dagActions}
            direction={direction}
            disableMinimap={isLarge}
            onNodeClick={(name) => vscode.postMessage({ type: "openAction", actionName: name })}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
}

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
  root.render(<App />);
} catch (e) {
  showFatal(e);
}
