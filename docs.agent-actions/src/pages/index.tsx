import type {ReactNode} from 'react';
import {Fragment} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import CodeBlock from '@theme/CodeBlock';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import LogoMark from '@site/static/img/logo-mark-current.svg';
import styles from './index.module.css';

const workflowYaml = `name: document-analysis
defaults:
  model_vendor: openai
  model_name: gpt-4o-mini

actions:
  - name: extract_facts
    prompt: $prompts.Fact_Extraction      # prompt store
    schema: facts_schema                  # output validated

  - name: classify_type
    dependencies: extract_facts           # explicit data flow
    prompt: $prompts.Classify_Type
    schema: { type: string, confidence: number }

  - name: generate_summary
    dependencies: classify_type
    context_scope:
      observe:                            # token control
        - extract_facts.facts
        - classify_type.type
      passthrough: [source.id]            # carried, no tokens
    prompt: $prompts.Generate_Summary
    schema: summary_schema
    reprompt:
      max_attempts: 3                     # auto-retry`;

function HomepageHeader() {
  return (
    <header className={styles.heroBanner}>
      <LogoMark className={styles.heroMark} role="img" />
      <div className={styles.heroTagline}>YAML-Native Orchestration</div>
      <Heading as="h1" className={styles.heroTitle}>
        Multi-step Agentic workflows{' '}
        <span className={styles.heroAccent}>defined in YAML</span>
      </Heading>
      <p className={styles.heroDesc}>
        Chain LLM actions with explicit dependencies, validate every output
        against schemas, and retry failures automatically. One config file
        runs across 7+ providers in sync or batch mode.
      </p>
      <div className={styles.heroActions}>
        <Link className={styles.btnPrimary} to="/docs/installation">
          Get Started -&gt;
        </Link>
        <Link
          className={styles.btnSecondary}
          href="https://github.com/Muizzkolapo/agent-actions">
          View on GitHub
        </Link>
      </div>
      <div className={styles.heroInstall}>
        <span className={styles.heroInstallPrompt}>$</span>
        <span className={styles.heroInstallCmd}> pip install agent-actions</span>
      </div>
    </header>
  );
}

const pipelineSteps = [
  {name: 'Source', detail: 'CSV / JSON', type: 'endpoint' as const},
  {name: 'extract_facts', detail: 'schema validated', type: 'action' as const},
  {name: 'classify_type', detail: 'schema validated', type: 'action' as const},
  {
    name: 'generate_summary',
    detail: '3\u00d7 auto-retry',
    type: 'action' as const,
  },
  {name: 'Output', detail: 'Structured JSON', type: 'endpoint' as const},
];

function WorkflowShowcase() {
  return (
    <section className={styles.showcase}>
      <div className={styles.showcaseInner}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionTag}>How it works</span>
          <Heading as="h2" className={styles.sectionTitle}>
            Define agentic workflows, not glue code
          </Heading>
          <p className={styles.sectionDesc}>
            Declare actions, dependencies, and schemas in YAML. The framework
            resolves execution order, validates every output, and retries
            failures automatically.
          </p>
        </div>

        <div className={styles.showcaseCode}>
          <CodeBlock language="yaml" title="workflow.yaml">
            {workflowYaml}
          </CodeBlock>
        </div>

        <div className={styles.pipeline}>
          {pipelineSteps.map((step, i) => (
            <Fragment key={step.name}>
              {i > 0 && (
                <div className={styles.pipelineArrow}>
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    fill="none"
                    aria-hidden="true">
                    <path
                      d="M4 10h12M12 6l4 4-4 4"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
              )}
              <div
                className={`${styles.pipelineNode} ${step.type === 'endpoint' ? styles.pipelineEndpoint : ''}`}>
                <span className={styles.pipelineName}>{step.name}</span>
                <span className={styles.pipelineDetail}>{step.detail}</span>
              </div>
            </Fragment>
          ))}
        </div>
      </div>
    </section>
  );
}

const capabilities = [
  {
    badge: 'VALIDATE',
    title: 'Schema Validation & Reprompting',
    description:
      'Every LLM output validated against declared schemas. Failed validations trigger automatic retry with error context and optional LLM critique.',
    snippet: 'schema: facts_schema\nreprompt: { max_attempts: 3 }',
  },
  {
    badge: 'SCOPE',
    title: 'Context Scoping',
    description:
      'Control what each action sees. observe sends fields to the LLM. passthrough carries data forward without tokens. drop excludes entirely.',
    snippet:
      'observe: [facts.summary]\npassthrough: [source.id]\ndrop: [source.raw_html]',
  },
  {
    badge: 'BATCH',
    title: 'Batch Execution',
    description:
      'One flag enables provider batch APIs for 50% cost savings. Retry chains track failures across attempts automatically.',
    snippet: 'run_mode: batch  # 50% cost savings',
  },
  {
    badge: 'VENDOR',
    title: '7+ LLM Providers',
    description:
      'OpenAI, Anthropic, Gemini, Groq, Mistral, Cohere, Ollama. Mix providers in a single workflow. Swap with one line.',
    snippet:
      '- model_vendor: groq       # extraction\n- model_vendor: anthropic  # generation',
  },
  {
    badge: 'PROMPT',
    title: 'Centralized Prompt Store',
    description:
      'Prompts live in Markdown files with Jinja2 templating. Version-controlled, diff-friendly, and reviewable by non-developers.',
    snippet: 'prompt: $prompts.Fact_Extraction',
  },
  {
    badge: 'CHECK',
    title: 'Pre-flight Validation',
    description:
      'Static analysis catches configuration errors before expensive LLM calls. Validates schemas, dependencies, templates, and field references.',
    snippet: '$ agac run --validate-only\n\u2705 All checks passed (3 actions)',
  },
];

function CapabilityGrid() {
  return (
    <section className={styles.capabilities}>
      <div className={styles.capInner}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionTag}>Capabilities</span>
          <Heading as="h2" className={styles.sectionTitle}>
            Built for production Agentic workflows
          </Heading>
          <p className={styles.sectionDesc}>
            Every feature exists because it was needed in production&mdash;processing
            thousands of records through multi-step pipelines daily.
          </p>
        </div>
        <div className={styles.capGrid}>
          {capabilities.map((cap) => (
            <div key={cap.title} className={styles.capCard}>
              <span className={styles.capBadge}>{cap.badge}</span>
              <h3 className={styles.capTitle}>{cap.title}</h3>
              <p className={styles.capDesc}>{cap.description}</p>
              <pre className={styles.capSnippet}>
                <code>{cap.snippet}</code>
              </pre>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="agent-actions - Docs"
      description="Declarative, YAML-native framework for production LLM workflows.">
      <HomepageHeader />
      <main>
        <WorkflowShowcase />
        <CapabilityGrid />
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
