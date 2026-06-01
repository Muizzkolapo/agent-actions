// components.jsx — agac docs components
const { useState, useEffect, useRef } = React;

/* ---------------- Icon (inline lucide-style, stroke 2) ---------------- */
const ICONS = {
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  arrowRight: '<path d="M5 12h14M12 5l7 7-7 7"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  warn: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4M12 17h.01"/>',
  bulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5C17.7 10.2 18 9 18 7.5a6 6 0 0 0-12 0c0 1.5.5 2.7 1.5 4 .8.8 1.3 1.5 1.5 2.5"/><path d="M9 18h6M10 22h4"/>',
  branch: '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
  box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>',
  hash: '<line x1="4" x2="20" y1="9" y2="9"/><line x1="4" x2="20" y1="15" y2="15"/><line x1="10" x2="8" y1="3" y2="21"/><line x1="16" x2="14" y1="3" y2="21"/>',
  external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  cycle: '<path d="M21 12a9 9 0 1 1-9-9"/><path d="M21 3v6h-6"/>',
  gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  plug: '<path d="M12 22v-5M9 8V2M15 8V2M18 8v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
};
function Icon({ name, size = 16, style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={style} dangerouslySetInnerHTML={{ __html: ICONS[name] || '' }} />
  );
}

const LANG_COLOR = {
  ts: '#74b6ff', js: '#f0db4f', tsx: '#74b6ff', jsx: '#f0db4f',
  bash: '#54d98c', sh: '#54d98c', json: '#ffb267', toml: '#cba6ff',
};

/* ---------------- The CODE INSTRUMENT ---------------- */
function CodeBlock({ files, showLineNumbers = true }) {
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);
  const [ran, setRan] = useState(false);
  const file = files[active];

  useEffect(() => { setRan(false); }, [active]);

  const copy = () => {
    navigator.clipboard?.writeText(file.code).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };

  const lines = file.code.replace(/\n$/, '').split('\n');
  const annots = file.annotations || {};   // { lineNo: "note text" }
  const diff = file.diff || {};            // { lineNo: 'add'|'del' }

  return (
    <div className="cb">
      <div className="cb-head">
        <div className="cb-lights" aria-hidden="true">
          <span className="cb-light red"></span>
          <span className="cb-light amber"></span>
          <span className="cb-light green"></span>
        </div>
        {files.length > 1 ? (
          <div className="cb-tabs">
            {files.map((f, i) => (
              <button key={i} className={'cb-tab' + (i === active ? ' active' : '')}
                onClick={() => setActive(i)}>
                <span className="lang-dot" style={{ background: LANG_COLOR[f.lang] || '#8b969d' }}></span>
                {f.name}
              </button>
            ))}
          </div>
        ) : (
          <div className="cb-head-meta">
            {file.name}
          </div>
        )}
        <div className="cb-head-right">
          {file.lang ? <span className="cb-chip">{file.lang}</span> : null}
          {file.run ? (
            <button className="cb-btn run" onClick={() => setRan(true)}>
              <Icon name="play" size={12} /> run
            </button>
          ) : null}
          <button className={'cb-btn' + (copied ? ' copied' : '')} onClick={copy}>
            <Icon name={copied ? 'check' : 'copy'} size={12} />
            {copied ? 'copied' : 'copy'}
          </button>
        </div>
      </div>

      <div className="cb-body">
        {showLineNumbers ? (
          <div className="cb-gutter">
            {lines.map((_, i) => {
              const no = i + 1;
              return (
                <React.Fragment key={i}>
                  <span className="ln">{no}</span>
                  {annots[no] ? <span className="ln">&nbsp;</span> : null}
                </React.Fragment>
              );
            })}
          </div>
        ) : null}
        <div className="cb-code">
          {lines.map((ln, i) => {
            const no = i + 1;
            const d = diff[no];
            const isHi = (file.highlight || []).includes(no);
            const cls = 'cb-line' + (d === 'add' ? ' add' : d === 'del' ? ' del' : isHi ? ' hi' : '');
            return (
              <React.Fragment key={i}>
                <span className={cls}
                  dangerouslySetInnerHTML={{ __html: window.highlightLine(ln, file.lang) || '&nbsp;' }} />
                {annots[no] ? (
                  <span className="cb-annot">
                    <span className="branch">{'   └─ '}</span>
                    <span className="note">{annots[no]}</span>
                  </span>
                ) : null}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {file.output ? (
        <div className="cb-output">
          <div className="cb-output-head">
            <span className="live"></span>
            output
            {file.run && !ran ? <span style={{ color: 'var(--tok-punc)', marginLeft: 8, textTransform: 'none', letterSpacing: 0 }}>— press run</span> : null}
          </div>
          {(!file.run || ran) ? (
            <div className="cb-output-body" dangerouslySetInnerHTML={{ __html: file.output }} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ---------------- Callout ---------------- */
function Callout({ kind = 'note', title, children }) {
  const ic = kind === 'warn' ? 'warn' : kind === 'tip' ? 'bulb' : 'info';
  return (
    <div className={'callout ' + kind}>
      <div className="callout-ic"><Icon name={ic} size={18} /></div>
      <div className="callout-body">
        {title ? <span className="cap">{title}</span> : null}
        {children}
      </div>
    </div>
  );
}

/* ---------------- Tree nav (collapsible) ---------------- */
// open all categories that are ancestors of the active doc
function ancestorsOpen(tree, activeId) {
  const res = {};
  function rec(nodes) {
    let contains = false;
    nodes.forEach((n) => {
      if (n.children) {
        const childHas = rec(n.children);
        if (childHas || n.id === activeId) { res[n.id] = true; contains = true; }
      } else if (n.id === activeId) {
        contains = true;
      }
    });
    return contains;
  }
  rec(tree);
  return res;
}

function TreeNav({ tree, activeId, onNav }) {
  const [open, setOpen] = useState(() => ancestorsOpen(tree, activeId));
  useEffect(() => {
    setOpen((o) => ({ ...o, ...ancestorsOpen(tree, activeId) }));
  }, [activeId]);

  const rows = [];
  function walk(nodes, prefix) {
    nodes.forEach((node, i) => {
      const last = i === nodes.length - 1;
      const glyph = prefix + (last ? '└─ ' : '├─ ');
      const isDir = !!node.children;
      const isOpen = isDir && open[node.id];
      rows.push({ node, glyph, isDir, isOpen });
      if (isDir && isOpen) walk(node.children, prefix + (last ? '   ' : '│  '));
    });
  }
  walk(tree, '');

  const onRow = (node, isDir) => {
    if (isDir) {
      setOpen((o) => ({ ...o, [node.id]: !o[node.id] }));
      if (node.id) onNav(node.id);
    } else if (node.id) {
      onNav(node.id);
    }
  };

  return (
    <div className="tree">
      {rows.map(({ node, glyph, isDir, isOpen }, i) => (
        <div key={i}
          className={'tree-node' + (isDir ? ' is-dir' : '') + (isOpen ? ' open' : '') + (node.id === activeId ? ' active' : '')}
          onClick={() => onRow(node, isDir)}>
          <span className="tree-glyph">{glyph}</span>
          <span className="tree-label">{node.label}</span>
          <span className="arrow"><Icon name="chevronRight" size={12} /></span>
        </div>
      ))}
    </div>
  );
}

/* ---------------- TOC ---------------- */
function Toc({ items, activeId, onNav }) {
  return (
    <nav className="toc">
      <div className="toc-cap"><Icon name="hash" size={12} /> on this page</div>
      <div className="toc-list">
        {items.map((it) => (
          <a key={it.id} className={'toc-item' + (it.id === activeId ? ' active' : '')}
            onClick={() => onNav(it.id)}>
            <span className="rail"></span>{it.label}
          </a>
        ))}
      </div>
    </nav>
  );
}

Object.assign(window, { Icon, CodeBlock, Callout, TreeNav, Toc, LANG_COLOR, ICONS });
