import type {ReactNode} from 'react';
import {useState} from 'react';
import Layout from '@theme/Layout';
import styles from './index.module.css';

/* Code example — raw HTML so syntax-highlight spans render exactly */
const codeBodyHtml = `<span class="ln"> 1</span><span class="kw">name:</span> <span class="str">document-analysis</span>
<span class="ln"> 2</span><span class="kw">defaults:</span>
<span class="ln"> 3</span>  <span class="kw">model_vendor:</span> <span class="str">openai</span>
<span class="ln"> 4</span>  <span class="kw">model_name:</span> <span class="str">gpt-4o-mini</span>
<span class="ln"> 5</span>
<span class="ln"> 6</span><span class="kw">actions:</span>
<span class="ln"> 7</span>  - <span class="kw">name:</span> <span class="str">extract</span>
<span class="ln"> 8</span>    <span class="kw">prompt:</span> <span class="fn">$prompts.Extract</span>
<span class="ln"> 9</span>    <span class="kw">schema:</span> <span class="str">facts_schema</span>
<span class="ln">10</span>  - <span class="kw">name:</span> <span class="str">summarize</span>
<span class="hi"><span class="ln">11</span>    <span class="kw">dependencies:</span> <span class="str">extract</span></span>
<span class="ln">12</span>    <span class="kw">prompt:</span> <span class="fn">$prompts.Summarize</span>`;

function InstallButton(): ReactNode {
  const [copied, setCopied] = useState(false);
  const cmd = 'pip install agent-actions';
  const copy = () => {
    navigator.clipboard?.writeText(cmd).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      className={`${styles.btn} ${styles.btnGhost} ${copied ? styles.copied : ''}`}
      onClick={copy}
      title="Copy to clipboard"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>
      </svg>
      {copied ? 'copied' : cmd}
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{opacity: 0.6}}>
        {copied
          ? <path d="M20 6 9 17l-5-5"/>
          : <><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></>
        }
      </svg>
    </button>
  );
}

const QNAV_ITEMS = [
  { path: 'get-started/', title: 'Get started', desc: 'Install agent-actions and run your first workflow in 30 seconds.', count: '2 docs', href: '/docs/' },
  { path: 'tutorials/', title: 'Key concepts', desc: 'Actions, dependencies, schemas, context scoping, and the execution DAG.', count: 'tutorial', href: '/docs/tutorials/concepts' },
  { path: 'guides/', title: 'Design patterns', desc: 'Fan-out, consensus aggregation, gating, retries, and multi-provider chains.', count: '5 guides', href: '/docs/guides/design-patterns' },
  { path: 'reference/cli/', title: 'CLI reference', desc: 'Every command and flag for the agac binary, end to end.', count: 'reference', href: '/docs/reference/cli' },
];

export default function Home(): ReactNode {
  return (
    <Layout
      title="Orchestrate AI Agent Chains"
      description="The framework for orchestrating AI agents into reliable, composable action chains."
    >
      <div className={styles.page}>

        {/* ═══ HERO ═══ */}
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroGrid}>
              <div>
                <div className={styles.heroEyebrow}>
                  <span className={styles.dot} /> v1.0 · YAML-native agent orchestration
                </div>
                <h1 className={styles.heroH1}>
                  One action tips.<br />
                  The rest <span className={styles.sig}>cascade.</span>
                </h1>
                <p className={styles.heroSub}>
                  agent-actions is an agentic workflow engine that runs in your terminal.
                  Define an LLM pipeline in YAML — the engine handles orchestration,
                  validation, and error recovery.
                </p>
                <div className={styles.heroActions}>
                  <a className={`${styles.btn} ${styles.btnPrimary}`} href="/docs/">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <polygon points="6 3 20 12 6 21 6 3"/>
                    </svg>
                    Get started
                  </a>
                  <InstallButton />
                </div>
              </div>

              <div className={styles.codeWindow}>
                <div className={styles.codeTitlebar}>
                  <span className={`${styles.codeDot} ${styles.codeDotRed}`} />
                  <span className={`${styles.codeDot} ${styles.codeDotAmber}`} />
                  <span className={`${styles.codeDot} ${styles.codeDotGreen}`} />
                  <span className={styles.codeFilename}>workflow.yaml</span>
                  <span className={styles.codeLang}>yaml</span>
                </div>
                <div
                  className={styles.codeBody}
                  dangerouslySetInnerHTML={{__html: codeBodyHtml}}
                />
              </div>
            </div>
          </div>
        </section>

        {/* ═══ FEATURES ═══ */}
        <section className={styles.features}>
          <div className={styles.feature}>
            <span className={styles.featureIdx}>01</span>
            <div className={styles.featureIcon}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>
              </svg>
            </div>
            <h3>Action composition</h3>
            <p>Define actions in YAML with explicit dependencies. The engine resolves the execution order — each domino knows when to fall.</p>
          </div>
          <div className={styles.feature}>
            <span className={styles.featureIdx}>02</span>
            <div className={styles.featureIcon}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M20 6 9 17l-5-5"/>
              </svg>
            </div>
            <h3>Schema validation</h3>
            <p>Every LLM output is validated against a declared schema. Failed validations trigger auto-retry with error context.</p>
          </div>
          <div className={styles.feature}>
            <span className={styles.featureIdx}>03</span>
            <div className={styles.featureIcon}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>
              </svg>
            </div>
            <h3>Built-in retry</h3>
            <p>Automatic reprompting with configurable max attempts. A failed domino doesn&apos;t break the chain — it tries again.</p>
          </div>
        </section>

        {/* ═══ QUICK NAV ═══ */}
        <section className={styles.qnav}>
          <div className={styles.qnavHead}>
            <div className={styles.qnavTitle}>Find your branch</div>
            <div className={styles.qnavMeta}>6 providers · YAML-native</div>
          </div>
          <div className={styles.qnavGrid}>
            {QNAV_ITEMS.map((c) => (
              <a key={c.path} className={styles.qnavCard} href={c.href}>
                <div className={styles.qnavCardTop}>
                  <span className={styles.qnavPath}>{c.path}</span>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--fg-3)" strokeWidth="2" strokeLinecap="round">
                    <path d="m9 18 6-6-6-6"/>
                  </svg>
                </div>
                <h4>{c.title}</h4>
                <p>{c.desc}</p>
                <span className={styles.qnavCount}>{c.count}</span>
              </a>
            ))}
          </div>
        </section>

      </div>
    </Layout>
  );
}
