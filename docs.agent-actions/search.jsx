// search.jsx — command palette (/ or ⌘K). Title + lazy full-text search.
const { useState, useEffect, useRef } = React;

const SEARCH_SECTION = { reference: 'Reference', guides: 'Guides', tutorials: 'Tutorials', api: 'API' };
function sectionFor(id) {
  return SEARCH_SECTION[id.split('/')[0]] || 'Get started';
}

function flattenPages(tree) {
  const pages = [];
  (function rec(nodes) {
    nodes.forEach((n) => {
      if (n.id) pages.push({ id: n.id, label: n.label, section: sectionFor(n.id) });
      if (n.children) rec(n.children);
    });
  })(tree);
  // de-dupe by id
  const seen = {};
  return pages.filter((p) => (seen[p.id] ? false : (seen[p.id] = true)));
}

// module-level content cache
let CONTENT_INDEX = null;
let INDEXING = false;
function stripMd(md) {
  return md
    .replace(/^---\n[\s\S]*?\n---\n?/, '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#>*`_\[\]()|-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
async function buildIndex(pages, onDone) {
  if (CONTENT_INDEX || INDEXING) { if (CONTENT_INDEX) onDone(); return; }
  INDEXING = true;
  const idx = {};
  await Promise.all(pages.map((p) =>
    fetch(p.id + '.md').then((r) => (r.ok ? r.text() : '')).then((t) => { idx[p.id] = stripMd(t).toLowerCase(); }).catch(() => { idx[p.id] = ''; })
  ));
  CONTENT_INDEX = idx;
  INDEXING = false;
  onDone();
}

function SearchPalette({ tree, open, onClose, onNav }) {
  const pages = useRef(flattenPages(tree)).current;
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [indexed, setIndexed] = useState(!!CONTENT_INDEX);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQ(''); setActive(0);
      setTimeout(() => inputRef.current && inputRef.current.focus(), 30);
      buildIndex(pages, () => setIndexed(true));
    }
  }, [open]);

  const query = q.trim().toLowerCase();
  let results = [];
  if (!query) {
    results = pages.slice(0, 8).map((p) => ({ ...p, snippet: null }));
  } else {
    const scored = [];
    pages.forEach((p) => {
      const label = p.label.toLowerCase();
      const path = p.id.toLowerCase();
      let score = -1, snippet = null;
      if (label.includes(query)) score = 0;
      else if (path.includes(query)) score = 1;
      else if (CONTENT_INDEX && CONTENT_INDEX[p.id] && CONTENT_INDEX[p.id].includes(query)) {
        score = 2;
        const t = CONTENT_INDEX[p.id];
        const i = t.indexOf(query);
        snippet = (i > 40 ? '…' : '') + t.slice(Math.max(0, i - 40), i + query.length + 50) + '…';
      }
      if (score >= 0) scored.push({ ...p, score, snippet });
    });
    scored.sort((a, b) => a.score - b.score);
    results = scored.slice(0, 25);
  }

  useEffect(() => { setActive(0); }, [q]);

  const choose = (r) => { if (r) { onNav(r.id); onClose(); } };

  const onKey = (e) => {
    if (e.key === 'Escape') { onClose(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); choose(results[active]); }
  };

  if (!open) return null;
  return ReactDOM.createPortal((
    <div className="cmdk-overlay" onClick={onClose}>
      <div className="cmdk-panel" onClick={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="cmdk-input-row">
          <Icon name="search" size={17} style={{ color: 'var(--fg-3)' }} />
          <input ref={inputRef} className="cmdk-input" placeholder="Search the docs…"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="cmdk-esc">esc</span>
        </div>
        <div className="cmdk-results">
          {results.length === 0 ? (
            <div className="cmdk-empty">No matches for “{q}”.</div>
          ) : results.map((r, i) => (
            <div key={r.id + i} className={'cmdk-result' + (i === active ? ' active' : '')}
              onMouseEnter={() => setActive(i)} onClick={() => choose(r)}>
              <Icon name="book" size={15} style={{ color: i === active ? 'var(--signal)' : 'var(--fg-3)', flex: 'none' }} />
              <div className="cmdk-result-text">
                <div className="cmdk-result-top">
                  <span className="cmdk-result-label">{r.label}</span>
                  <span className="cmdk-result-section">{r.section}</span>
                </div>
                {r.snippet ? <div className="cmdk-result-snippet">{r.snippet}</div> : <div className="cmdk-result-path">{r.id}</div>}
              </div>
              <Icon name="arrowRight" size={13} style={{ color: 'var(--fg-3)', flex: 'none', opacity: i === active ? 1 : 0 }} />
            </div>
          ))}
        </div>
        <div className="cmdk-foot">
          <span><span className="kc">↑</span><span className="kc">↓</span> navigate</span>
          <span><span className="kc">↵</span> open</span>
          <span className="cmdk-foot-right">{indexed ? `${pages.length} pages` : 'indexing…'}</span>
        </div>
      </div>
    </div>
  ), document.body);
}

Object.assign(window, { SearchPalette });
