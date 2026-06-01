// home.jsx — docs landing
function InstallButton() {
  const [copied, setCopied] = React.useState(false);
  const cmd = 'pip install agent-actions';
  const copy = () => {
    navigator.clipboard && navigator.clipboard.writeText(cmd).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button className={'btn btn-ghost' + (copied ? ' copied' : '')} onClick={copy} title="Copy to clipboard">
      <Icon name={copied ? 'check' : 'terminal'} size={14} />
      {copied ? 'copied' : cmd}
      <Icon name={copied ? 'check' : 'copy'} size={13} style={{ marginLeft: 4, opacity: 0.6 }} />
    </button>
  );
}

function HomeView({ onNav }) {
  return (
    <div className="home">
      <div className="home-inner">
        <section className="hero">
          <div className="hero-grid">
            <div>
              <div className="hero-eyebrow">
                <span className="dot"></span> v1.0 · YAML-native agent orchestration
              </div>
              <h1 className="hero-title">
                One action tips.<br />The rest <span className="sig">cascade.</span>
              </h1>
              <p className="hero-sub">
                agent-actions is an agentic workflow engine that runs in your terminal.
                Define an LLM pipeline in YAML — the engine handles orchestration,
                validation, and error recovery.
              </p>
              <div className="hero-actions">
                <a className="btn btn-primary" onClick={() => onNav('index')}>
                  <Icon name="play" size={14} /> Get started
                </a>
                <InstallButton />
              </div>
            </div>

            <CodeBlock files={[
              { name: 'workflow.yaml', lang: 'yaml',
                highlight: [11],
                code: `name: document-analysis
defaults:
  model_vendor: openai
  model_name: gpt-4o-mini

actions:
  - name: extract
    prompt: $prompts.Extract
    schema: facts_schema
  - name: summarize
    dependencies: extract
    prompt: $prompts.Summarize`,
              },
            ]} />
          </div>
        </section>

        <section className="features">
          <div className="feature">
            <div className="feature-idx">01</div>
            <div className="feature-ic"><Icon name="layers" size={20} /></div>
            <h3>Action composition</h3>
            <p>Define actions in YAML with explicit dependencies. The engine resolves the execution order — each domino knows when to fall.</p>
          </div>
          <div className="feature">
            <div className="feature-idx">02</div>
            <div className="feature-ic"><Icon name="check" size={20} /></div>
            <h3>Schema validation</h3>
            <p>Every LLM output is validated against a declared schema. Failed validations trigger auto-retry with error context.</p>
          </div>
          <div className="feature">
            <div className="feature-idx">03</div>
            <div className="feature-ic"><Icon name="repeat" size={20} /></div>
            <h3>Built-in retry</h3>
            <p>Automatic reprompting with configurable max attempts. A failed domino doesn’t break the chain — it tries again.</p>
          </div>
        </section>

        <section className="qnav">
          <div className="qnav-head">
            <div className="qnav-title">Find your branch</div>
            <div className="caps" style={{ color: 'var(--fg-3)' }}>6 providers · YAML-native</div>
          </div>
          <div className="qnav-grid">
            {[
              { path: 'get-started/', title: 'Get started', desc: 'Install agent-actions and run your first workflow in 30 seconds.', count: '2 docs', icon: 'play', id: 'installation' },
              { path: 'tutorials/', title: 'Key concepts', desc: 'Actions, dependencies, schemas, context scoping, and the execution DAG.', count: 'tutorial', icon: 'layers', id: 'tutorials/concepts' },
              { path: 'guides/', title: 'Design patterns', desc: 'Fan-out, consensus aggregation, gating, retries, and multi-provider chains.', count: '5 guides', icon: 'repeat', id: 'guides/design-patterns' },
              { path: 'reference/cli/', title: 'CLI reference', desc: 'Every command and flag for the agac binary, end to end.', count: 'reference', icon: 'terminal', id: 'reference/cli/index' },
            ].map((c) => (
              <a key={c.path} className="qnav-card" onClick={() => c.id && onNav(c.id)}>
                <div className="qnav-card-top">
                  <span className="path">{c.path}</span>
                  <Icon name={c.icon} size={16} style={{ color: 'var(--fg-3)' }} />
                </div>
                <h4>{c.title}</h4>
                <p>{c.desc}</p>
                <span className="count">{c.count}</span>
              </a>
            ))}
          </div>
        </section>
      </div>

      <footer className="foot">
        <div className="foot-inner">
          <span>agent-actions · MIT · runs in your terminal</span>
          <span>docs v1.0</span>
        </div>
      </footer>
    </div>
  );
}

Object.assign(window, { HomeView });
