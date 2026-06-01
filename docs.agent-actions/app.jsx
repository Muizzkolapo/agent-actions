// app.jsx — shell, navigation, theme, tweaks
const { useState, useEffect, useRef } = React;

const NAV_TREE = [
  { id: 'index', label: 'overview' },
  { id: 'installation', label: 'installation' },
  { label: 'tutorials', id: 'tutorials/index', children: [
    { id: 'tutorials/concepts', label: 'key-concepts' },
  ] },
  { label: 'guides', id: 'guides/index', children: [
    { id: 'guides/design-patterns', label: 'design-patterns' },
    { id: 'guides/custom-tools', label: 'custom-tools' },
    { id: 'guides/human-in-the-loop', label: 'human-in-the-loop' },
    { id: 'guides/editor-setup', label: 'editor-setup' },
    { id: 'guides/troubleshooting', label: 'troubleshooting' },
  ] },
  { label: 'reference', id: 'reference/index', children: [
    { label: 'cli', id: 'reference/cli/index', children: [
      { id: 'reference/cli/run', label: 'run' },
      { id: 'reference/cli/batch', label: 'batch' },
      { id: 'reference/cli/inspect', label: 'inspect' },
      { id: 'reference/cli/utilities', label: 'utilities' },
      { id: 'reference/cli/preview', label: 'preview' },
      { id: 'reference/cli/tools', label: 'tools' },
      { id: 'reference/cli/schema', label: 'schema' },
      { id: 'reference/cli/skills', label: 'skills' },
      { id: 'reference/cli/troubleshooting', label: 'troubleshooting' },
    ] },
    { label: 'configuration', id: 'reference/configuration/index', children: [
      { id: 'reference/configuration/templates', label: 'templates' },
      { id: 'reference/configuration/defaults', label: 'defaults' },
    ] },
    { label: 'context', id: 'reference/context/index', children: [
      { id: 'reference/context/field-references', label: 'field-references' },
      { id: 'reference/context/context-scope', label: 'context-scope' },
      { id: 'reference/context/seed-data', label: 'seed-data' },
    ] },
    { label: 'data-io', id: 'reference/data-io/index', children: [
      { id: 'reference/data-io/input-formats', label: 'input-formats' },
      { id: 'reference/data-io/output-format', label: 'output-format' },
      { id: 'reference/data-io/data-lineage', label: 'data-lineage' },
      { id: 'reference/data-io/chunking', label: 'chunking' },
    ] },
    { label: 'prompts', id: 'reference/prompts/index', children: [
      { id: 'reference/prompts/prompt-store', label: 'prompt-store' },
      { id: 'reference/prompts/dispatch', label: 'dispatch' },
    ] },
    { id: 'reference/schemas/index', label: 'schemas' },
    { label: 'execution', id: 'reference/execution/index', children: [
      { id: 'reference/execution/guards', label: 'guards' },
      { id: 'reference/execution/artifacts', label: 'artifacts' },
      { id: 'reference/execution/context-handling', label: 'context-handling' },
      { id: 'reference/execution/run-modes', label: 'run-modes' },
      { id: 'reference/execution/granularity', label: 'granularity' },
      { id: 'reference/execution/retry', label: 'retry' },
      { id: 'reference/execution/versions', label: 'versions' },
    ] },
    { label: 'validation', id: 'reference/validation/index', children: [
      { id: 'reference/validation/reprompting', label: 'reprompting' },
      { id: 'reference/validation/output-validation', label: 'output-validation' },
    ] },
    { id: 'reference/tools/index', label: 'tools' },
    { label: 'architecture', id: 'reference/architecture/index', children: [
      { id: 'reference/architecture/internal-defaults', label: 'internal-defaults' },
      { id: 'reference/architecture/logging', label: 'logging' },
    ] },
    { id: 'reference/inspect', label: 'inspect' },
    { id: 'reference/documentation-site', label: 'documentation-site' },
  ] },
  { label: 'api', id: 'api/index', children: [
    { id: 'api/logging', label: 'logging' },
  ] },
];

const ACCENTS = {
  coral:   { signal: '#ff5c3d', hi: '#ff7559', dim: '#d8492c' },
  ember:   { signal: '#ff8a3d', hi: '#ffa05c', dim: '#e0701f' },
  lime:    { signal: '#b6e23d', hi: '#c8ec5f', dim: '#94bf20' },
  cyan:    { signal: '#3dd6e2', hi: '#5fe3ee', dim: '#1fb2bf' },
  magenta: { signal: '#ff5da2', hi: '#ff7bb3', dim: '#e03d85' },
};

function applyAccent(name) {
  const a = ACCENTS[name] || ACCENTS.coral;
  const r = document.documentElement;
  r.style.setProperty('--signal', a.signal);
  r.style.setProperty('--signal-hi', a.hi);
  r.style.setProperty('--signal-dim', a.dim);
  r.style.setProperty('--signal-soft', `color-mix(in srgb, ${a.signal} 13%, transparent)`);
  r.style.setProperty('--signal-line', `color-mix(in srgb, ${a.signal} 42%, transparent)`);
  r.style.setProperty('--code-line-hi', `color-mix(in srgb, ${a.signal} 9%, transparent)`);
}

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "coral",
  "grid": true
}/*EDITMODE-END*/;

const GITHUB_URL = 'https://github.com/Muizzkolapo/agent-actions';

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [screen, setScreen] = useState('home'); // 'home' | 'doc'
  const [activeDoc, setActiveDoc] = useState('index');
  const [searchOpen, setSearchOpen] = useState(false);

  // theme + accent + grid
  useEffect(() => { document.documentElement.setAttribute('data-theme', t.theme); }, [t.theme]);
  useEffect(() => { applyAccent(t.accent); }, [t.accent]);
  useEffect(() => {
    document.documentElement.style.setProperty('--grid-line',
      t.grid ? (t.theme === 'light' ? 'rgba(11,14,16,0.035)' : 'rgba(255,255,255,0.035)') : 'transparent');
  }, [t.grid, t.theme]);

  const goDoc = (id) => {
    setScreen('doc');
    setActiveDoc(id);
    window.scrollTo({ top: 0 });
  };
  const goHome = () => { setScreen('home'); window.scrollTo({ top: 0 }); };

  // open palette on "/" or ⌘K / Ctrl-K
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setSearchOpen(true); }
      else if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); setSearchOpen(true); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <React.Fragment>
      <TopBar theme={t.theme} onToggleTheme={() => setTweak('theme', t.theme === 'dark' ? 'light' : 'dark')} onHome={goHome} onSearch={() => setSearchOpen(true)} />

      {screen === 'home' ? (
        <HomeView onNav={goDoc} />
      ) : (
        <div className="app">
          <aside className="sidebar">
            <div className="tree-root-label">
              <Icon name="branch" size={13} />
              <span>agent-actions</span>
              <span style={{ color: 'var(--fg-3)' }}>·</span>
              <span className="dot" style={{ color: 'var(--add)' }}>v1.0</span>
            </div>
            <TreeNav tree={NAV_TREE} activeId={activeDoc} onNav={goDoc} />
          </aside>

          <main className="main">
            <DocPage docId={activeDoc} onNav={goDoc} />
          </main>
        </div>
      )}

      <SearchPalette tree={NAV_TREE} open={searchOpen} onClose={() => setSearchOpen(false)} onNav={goDoc} />

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakRadio label="Mode" value={t.theme} options={['dark', 'light']}
          onChange={(v) => setTweak('theme', v)} />
        <TweakColor label="Signal accent" value={ACCENTS[t.accent].signal}
          options={Object.values(ACCENTS).map((a) => a.signal)}
          onChange={(hex) => {
            const name = Object.keys(ACCENTS).find((k) => ACCENTS[k].signal === hex) || 'coral';
            setTweak('accent', name);
          }} />
        <TweakToggle label="Blueprint grid" value={t.grid}
          onChange={(v) => setTweak('grid', v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}

function TopBar({ theme, onToggleTheme, onHome, onSearch }) {
  return (
    <header className="topbar">
      <div className="brand" onClick={onHome}>
        <div className="brand-glyph">
          <svg width="20" height="20" viewBox="0 0 100 100" fill="none" aria-label="agent-actions">
            <rect x="8" y="20" width="13" height="54" rx="4" fill="#94a3b8" opacity="1" transform="rotate(-30 14 68)" />
            <rect x="28" y="22" width="13" height="56" rx="4" fill="currentColor" opacity="0.45" transform="rotate(-15 34 76)" />
            <rect x="50" y="22" width="13" height="60" rx="4" fill="currentColor" opacity="0.65" transform="rotate(-5 56 80)" />
            <rect x="72" y="18" width="15" height="68" rx="4" fill="currentColor" opacity="1" />
          </svg>
        </div>
        <div className="brand-name">agent<span className="tld">-actions</span></div>
      </div>
      <span className="brand-ver">v1.0</span>
      <div className="topbar-spacer"></div>
      <div className="cmdk" onClick={onSearch}>
        <Icon name="search" size={14} />
        <span>Search docs</span>
        <span className="kbd">/</span>
      </div>
      <a className="topbar-link" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">github</a>
      <button className="icon-btn" onClick={onToggleTheme} title="Toggle theme">
        <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />
      </button>
      <a className="icon-btn" href={GITHUB_URL} target="_blank" rel="noopener noreferrer" title="Repository"><Icon name="external" size={15} /></a>
    </header>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
