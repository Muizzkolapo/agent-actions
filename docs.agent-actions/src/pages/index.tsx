import type {ReactNode} from 'react';
import Layout from '@theme/Layout';
import styles from './index.module.css';

/* Code example HTML — kept as raw string so syntax-highlight spans render exactly
   as the designer's original markup (class names are scoped via .codeBody :global). */
const codeBodyHtml = `<span class="ln"> 1</span><span class="kw">name:</span> <span class="str">document-analysis</span>
<span class="ln"> 2</span><span class="kw">defaults:</span>
<span class="ln"> 3</span>  <span class="kw">model_vendor:</span> <span class="str">openai</span>
<span class="ln"> 4</span>  <span class="kw">model_name:</span> <span class="str">gpt-4o-mini</span>
<span class="ln"> 5</span>
<span class="ln"> 6</span><span class="kw">actions:</span>
<span class="ln"> 7</span>  - <span class="kw">name:</span> <span class="str">extract_facts</span>
<span class="ln"> 8</span>    <span class="kw">prompt:</span> <span class="fn">$prompts.Fact_Extraction</span>
<span class="ln"> 9</span>    <span class="kw">schema:</span> <span class="str">facts_schema</span>          <span class="cm"># validated</span>
<span class="ln">10</span>
<span class="ln">11</span>  - <span class="kw">name:</span> <span class="str">classify_type</span>
<span class="ln">12</span>    <span class="kw">dependencies:</span> <span class="str">extract_facts</span>   <span class="cm"># wired</span>
<span class="ln">13</span>    <span class="kw">prompt:</span> <span class="fn">$prompts.Classify_Type</span>
<span class="ln">14</span>
<span class="ln">15</span>  - <span class="kw">name:</span> <span class="str">generate_summary</span>
<span class="ln">16</span>    <span class="kw">dependencies:</span> <span class="str">classify_type</span>
<span class="ln">17</span>    <span class="kw">schema:</span> <span class="str">summary_schema</span>
<span class="ln">18</span>    <span class="kw">reprompt:</span>
<span class="ln">19</span>      <span class="kw">max_attempts:</span> <span class="str">3</span>             <span class="cm"># auto-retry</span>`;

export default function Home(): ReactNode {
  return (
    <Layout
      title="Orchestrate AI Agent Chains"
      description="The framework for orchestrating AI agents into reliable, composable action chains.">
      <div className={styles.page}>

        {/* ═══ HERO ═══ */}
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroBadge}>
              <span className={styles.dot} /> v1.0 — YAML-native LLM workflow orchestration
            </div>

            <div className={styles.heroMark}>
              <svg width="88" height="88" viewBox="0 0 100 100" fill="none">
                <rect className={styles.d1} x="8" y="20" width="13" height="54" rx="4" fill="var(--domino-accent)" transform="rotate(-30 14 68)" opacity="0"/>
                <rect className={styles.d2} x="28" y="22" width="13" height="56" rx="4" fill="var(--domino-main)" opacity="0" transform="rotate(-15 34 76)"/>
                <rect className={styles.d3} x="50" y="22" width="13" height="60" rx="4" fill="var(--domino-main)" opacity="0" transform="rotate(-5 56 80)"/>
                <rect className={styles.d4} x="72" y="18" width="15" height="68" rx="4" fill="var(--domino-main)" opacity="0"/>
              </svg>
            </div>

            <h1 className={styles.heroH1}>
              One action tips.<br/>
              <span className={styles.gradient}>The rest cascade.</span>
            </h1>

            <p className={styles.heroSub}>
              A framework for orchestrating AI agents into reliable, composable action chains. Define agents, wire them together, ship.
            </p>

            <div className={styles.heroActions}>
              <a className={`${styles.btn} ${styles.btnPrimary}`} href="/docs/">
                <svg viewBox="0 0 16 16" fill="currentColor"><path d="M3 3h10v10H3z" opacity="0"/><path d="M8 1.5l6.5 5V14H10V9H6v5H1.5V6.5z"/></svg>
                Get Started
              </a>
              <a className={`${styles.btn} ${styles.btnSecondary}`} href="https://github.com/Muizzkolapo/agent-actions">
                <svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                GitHub
              </a>
            </div>

            <div className={styles.heroInstall}>
              <span className={styles.prompt}>$</span>
              pip install agent-actions
              <button className={styles.copyBtn} title="Copy">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
              </button>
            </div>
          </div>
        </section>


        {/* ═══ FEATURES ═══ */}
        <section className={styles.features}>
          <div className={styles.featuresInner}>
            <div className={styles.featuresHeader}>
              <div className={styles.featuresLabel}>Why agent-actions</div>
              <h2 className={styles.featuresH2}>Everything agents need to act.</h2>
              <p className={styles.featuresDesc}>A complete toolkit for building reliable AI agent chains that actually work in production.</p>
            </div>

            <div className={styles.featuresGrid}>
              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>
                  <svg width="18" height="18" viewBox="0 0 100 100" fill="none">
                    <rect x="8" y="20" width="13" height="54" rx="4" fill="var(--domino-accent)" transform="rotate(-30 14 68)"/>
                    <rect x="28" y="22" width="13" height="56" rx="4" fill="var(--domino-main)" opacity="0.45" transform="rotate(-15 34 76)"/>
                    <rect x="50" y="22" width="13" height="60" rx="4" fill="var(--domino-main)" opacity="0.65" transform="rotate(-5 56 80)"/>
                    <rect x="72" y="18" width="15" height="68" rx="4" fill="var(--domino-main)"/>
                  </svg>
                </div>
                <h3>Action Composition</h3>
                <p>Define actions in YAML with explicit dependencies. The framework resolves execution order — each domino knows when to fall.</p>
              </div>

              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--icon-stroke)" strokeWidth="2" strokeLinecap="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                </div>
                <h3>Schema Validation</h3>
                <p>Every LLM output validated against declared schemas. Failed validations trigger auto-retry with error context.</p>
              </div>

              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--icon-stroke)" strokeWidth="2" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
                </div>
                <h3>Context Scoping</h3>
                <p>Control what each action sees. Observe sends fields to the LLM, passthrough carries data without tokens.</p>
              </div>

              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--icon-stroke)" strokeWidth="2" strokeLinecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </div>
                <h3>Built-in Retry</h3>
                <p>Automatic reprompting with configurable max attempts. A failed domino doesn&apos;t break the chain — it tries again.</p>
              </div>

              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--icon-stroke)" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
                </div>
                <h3>Any LLM Provider</h3>
                <p>OpenAI, Anthropic, Ollama, or your own. Swap providers per-agent without touching chain logic.</p>
              </div>

              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--icon-stroke)" strokeWidth="2" strokeLinecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                </div>
                <h3>Batch Execution</h3>
                <p>One flag enables provider batch APIs for 50% cost savings. Retry chains track failures across attempts automatically.</p>
              </div>
            </div>
          </div>
        </section>

        {/* ═══ CODE ═══ */}
        <section className={styles.codeSection}>
          <div className={styles.codeInner}>
            <div className={styles.codeText}>
              <div className={styles.featuresLabel}>Quick Start</div>
              <h2 className={styles.codeH2}>Three actions.<br/>One YAML file.</h2>
              <p className={styles.codeDesc}>Define actions with dependencies, validate outputs against schemas, and auto-retry failures. No glue code — just config.</p>
              <a className={`${styles.btn} ${styles.btnSecondary}`} href="/docs/" style={{display: 'inline-flex'}}>Read the docs →</a>
            </div>
            <div className={styles.codeWindow}>
              <div className={styles.codeTitlebar}>
                <div className={styles.codeDot}/><div className={styles.codeDot}/><div className={styles.codeDot}/>
                <span className={styles.codeFilename}>workflow.yaml</span>
              </div>
              <div
                className={styles.codeBody}
                dangerouslySetInnerHTML={{__html: codeBodyHtml}}
              />
            </div>
          </div>
        </section>

        {/* ═══ CTA ═══ */}
        <section className={styles.cta}>
          <div className={styles.ctaInner}>
            <div style={{marginBottom: '24px'}}>
              <svg width="48" height="48" viewBox="0 0 100 100" fill="none">
                <rect x="8" y="20" width="13" height="54" rx="4" fill="var(--domino-accent)" transform="rotate(-30 14 68)"/>
                <rect x="28" y="22" width="13" height="56" rx="4" fill="var(--domino-main)" opacity="0.45" transform="rotate(-15 34 76)"/>
                <rect x="50" y="22" width="13" height="60" rx="4" fill="var(--domino-main)" opacity="0.65" transform="rotate(-5 56 80)"/>
                <rect x="72" y="18" width="15" height="68" rx="4" fill="var(--domino-main)"/>
              </svg>
            </div>
            <h2 className={styles.ctaH2}>Start the cascade.</h2>
            <p className={styles.ctaDesc}>Build reliable AI agent pipelines with YAML-native workflows, schema validation, and multi-provider orchestration.</p>
            <div style={{display: 'flex', gap: '12px', justifyContent: 'center'}}>
              <a className={`${styles.btn} ${styles.btnPrimary}`} href="/docs/">Get Started</a>
              <a className={`${styles.btn} ${styles.btnSecondary}`} href="https://github.com/Muizzkolapo/agent-actions">Give a star On github</a>
            </div>
          </div>
        </section>

      </div>
    </Layout>
  );
}
