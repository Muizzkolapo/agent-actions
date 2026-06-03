/**
 * Homepage — src/pages/index.tsx
 * Ports the static site's landing (hero + cascade YAML window + features +
 * quicklinks) into Docusaurus. Wrapped in <Layout> so it gets the themed
 * navbar + footer. Styling lives in src/css/custom.css under `.agac-home`.
 *
 * Lives at the site root "/". Docs remain under "/docs/".
 */
import React, {useState} from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const I = (p: string) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    dangerouslySetInnerHTML={{__html: p}} />
);
const IC = {
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  branch: '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
};

function InstallButton() {
  const [copied, setCopied] = useState(false);
  const cmd = 'pip install agent-actions';
  return (
    <button
      className={'agac-btn agac-btn-ghost' + (copied ? ' copied' : '')}
      onClick={() => {
        if (navigator.clipboard) navigator.clipboard.writeText(cmd).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}>
      {I(copied ? IC.check : IC.terminal)}
      {copied ? 'copied' : cmd}
      {I(copied ? IC.check : IC.copy)}
    </button>
  );
}

const YAML_LINES: {h?: boolean; html: string}[] = [
  {html: '<span style="color:#9fb4bd">name</span><span style="color:#8b969d">:</span> document-analysis'},
  {html: '<span style="color:#9fb4bd">defaults</span><span style="color:#8b969d">:</span>'},
  {html: '  <span style="color:#9fb4bd">model_vendor</span><span style="color:#8b969d">:</span> openai'},
  {html: '  <span style="color:#9fb4bd">model_name</span><span style="color:#8b969d">:</span> gpt-4o-mini'},
  {html: ''},
  {html: '<span style="color:#9fb4bd">actions</span><span style="color:#8b969d">:</span>'},
  {html: '  <span style="color:#8b969d">-</span> <span style="color:#9fb4bd">name</span><span style="color:#8b969d">:</span> extract'},
  {html: '    <span style="color:#9fb4bd">prompt</span><span style="color:#8b969d">:</span> <span style="color:#7ee0a0">$prompts.Extract</span>'},
  {html: '    <span style="color:#9fb4bd">schema</span><span style="color:#8b969d">:</span> facts_schema'},
  {html: '  <span style="color:#8b969d">-</span> <span style="color:#9fb4bd">name</span><span style="color:#8b969d">:</span> summarize'},
  {h: true, html: '    <span style="color:#9fb4bd">dependencies</span><span style="color:#8b969d">:</span> extract'},
  {html: '    <span style="color:#9fb4bd">prompt</span><span style="color:#8b969d">:</span> <span style="color:#7ee0a0">$prompts.Summarize</span>'},
];

const FEATURES = [
  {ic: IC.layers, n: '01', t: 'Action composition', d: 'Define actions in YAML with explicit dependencies. The engine resolves the execution order — each domino knows when to fall.'},
  {ic: IC.check, n: '02', t: 'Schema validation', d: 'Every LLM output is validated against a declared schema. Failed validations trigger auto-retry with error context.'},
  {ic: IC.repeat, n: '03', t: 'Built-in retry', d: 'Automatic reprompting with configurable max attempts. A failed domino doesn’t break the chain — it tries again.'},
];

const QNAV = [
  {path: 'get-started/', ic: IC.play, t: 'Get started', d: 'Install agent-actions and run your first workflow in 30 seconds.', c: '2 docs', to: '/docs/installation'},
  {path: 'tutorials/', ic: IC.layers, t: 'Key concepts', d: 'Actions, dependencies, schemas, context scoping, and the execution DAG.', c: 'tutorial', to: '/docs/tutorials/concepts'},
  {path: 'guides/', ic: IC.repeat, t: 'Design patterns', d: 'Fan-out, consensus aggregation, gating, retries, and multi-provider chains.', c: '5 guides', to: '/docs/guides/design-patterns'},
  {path: 'reference/cli/', ic: IC.terminal, t: 'CLI reference', d: 'Every command and flag for the agac binary, end to end.', c: 'reference', to: '/docs/reference/cli'},
];

export default function Home(): JSX.Element {
  return (
    <Layout title="agent-actions" description="YAML-native multi-agent DAG workflows with schema-first validation">
      <div className="agac-home">
        <div className="agac-home-inner">

          <section className="agac-hero">
            <div className="agac-hero-grid">
              <div>
                <div className="agac-eyebrow"><span className="dot"></span> v1.0 · YAML-native agent orchestration</div>
                <h1 className="agac-hero-title">One action tips.<br />The rest <span className="sig">cascade.</span></h1>
                <p className="agac-hero-sub">
                  agent-actions is an agentic workflow engine that runs in your terminal.
                  Define an LLM pipeline in YAML — the engine handles orchestration,
                  validation, and error recovery.
                </p>
                <div className="agac-actions">
                  <Link className="agac-btn agac-btn-primary" to="/docs/">{I(IC.play)} Get started</Link>
                  <InstallButton />
                </div>
              </div>

              <div className="agac-code">
                <div className="agac-code-head">
                  <span className="agac-lights">
                    <span className="agac-light" style={{background: '#ff5f57'}}></span>
                    <span className="agac-light" style={{background: '#febc2e'}}></span>
                    <span className="agac-light" style={{background: '#28c840'}}></span>
                  </span>
                  <span className="agac-code-name">workflow.yaml</span>
                </div>
                <div className="agac-code-body">
                  <div className="agac-gutter">
                    {YAML_LINES.map((_, i) => <span key={i}>{i + 1}</span>)}
                  </div>
                  <pre className="agac-code-pre"><code>
                    {YAML_LINES.map((ln, i) => (
                      <span key={i} className={'agac-code-line' + (ln.h ? ' hi' : '')}
                        dangerouslySetInnerHTML={{__html: ln.html || '&nbsp;'}} />
                    ))}
                  </code></pre>
                </div>
              </div>
            </div>
          </section>

          <section className="agac-features">
            {FEATURES.map((f) => (
              <div className="agac-feature" key={f.n}>
                <span className="agac-feature-idx">{f.n}</span>
                <div className="agac-feature-ic">{I(f.ic)}</div>
                <h3>{f.t}</h3>
                <p>{f.d}</p>
              </div>
            ))}
          </section>

          <section className="agac-qnav">
            <div className="agac-qnav-head">
              <div className="agac-qnav-title">Find your branch</div>
              <div className="agac-qnav-cap">6 providers · YAML-native</div>
            </div>
            <div className="agac-qnav-grid">
              {QNAV.map((c) => (
                <Link className="agac-qnav-card" to={c.to} key={c.path}>
                  <div className="agac-qnav-card-top">
                    <span className="path">{c.path}</span>
                    {I(c.ic)}
                  </div>
                  <h4>{c.t}</h4>
                  <p>{c.d}</p>
                  <span className="count">{c.c}</span>
                </Link>
              ))}
            </div>
          </section>

        </div>
      </div>
    </Layout>
  );
}
