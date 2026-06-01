// markdown.jsx — renders agent-actions markdown docs into the agac design system.
// Uses `marked` (parse) + our highlighter (code) + `mermaid` (diagrams).
const { useState, useEffect, useLayoutEffect, useRef } = React;

if (window.mermaid) {
  window.mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'loose',
    theme: 'base',
    themeVariables: {
      background: 'transparent',
      primaryColor: '#161c21',
      primaryBorderColor: '#2b343b',
      primaryTextColor: '#e9edee',
      secondaryColor: '#11161a',
      tertiaryColor: '#0d1115',
      lineColor: '#6b777e',
      fontFamily: 'JetBrains Mono, ui-monospace, monospace',
      fontSize: '13px',
    },
  });
}

/* ---------- helpers ---------- */
function slugify(s) {
  return s.toLowerCase().trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function iconSvg(name) {
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${window.ICONS[name] || ''}</svg>`;
}
const ADMONITION_KIND = { tip: 'tip', note: 'note', info: 'note', warning: 'warn', caution: 'warn', danger: 'warn', important: 'note' };
const ADMONITION_ICON = { tip: 'bulb', note: 'info', warn: 'warn' };

function stripFrontmatter(md) {
  const m = md.match(/^---\n([\s\S]*?)\n---\n?/);
  let title = null;
  if (m) {
    const t = m[1].match(/^title:\s*(.+)$/m);
    if (t) title = t[1].replace(/^["']|["']$/g, '').trim();
    md = md.slice(m[0].length);
  }
  return { md, title };
}

/* ---------- markdown -> html (admonition-aware) ---------- */
function renderMarkdown(raw, docId) {
  let { md, title } = stripFrontmatter(raw);

  // pull the first H1 as the page title
  md = md.replace(/^#\s+(.+)$/m, (full, h1) => {
    if (!title) title = h1.trim();
    return '';
  });

  marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });

  // walk admonition blocks, parsing the rest with marked
  const re = /^:::(\w+)([^\n]*)\n([\s\S]*?)\n:::\s*$/gm;
  let out = '';
  let last = 0;
  let m;
  while ((m = re.exec(md)) !== null) {
    out += marked.parse(md.slice(last, m.index));
    const kind = ADMONITION_KIND[m[1].toLowerCase()] || 'note';
    const ttl = (m[2] || '').trim();
    const inner = marked.parse(m[3]);
    out += `<div class="callout ${kind}"><div class="callout-ic">${iconSvg(ADMONITION_ICON[kind])}</div>`
      + `<div class="callout-body">${ttl ? `<span class="cap">${escapeHtml(ttl)}</span>` : ''}${inner}</div></div>`;
    last = re.lastIndex;
  }
  out += marked.parse(md.slice(last));

  return { title: title || docId, html: out };
}

/* ---------- DOM enhancement after insertion ---------- */
function buildCodeBlock(codeText, lang) {
  const code = codeText.replace(/\n$/, '');
  const lines = code.split('\n');
  const color = (window.LANG_COLOR && window.LANG_COLOR[lang]) || '#8b969d';

  const cb = document.createElement('div');
  cb.className = 'cb';
  cb.innerHTML =
    `<div class="cb-head">
       <div class="cb-head-meta"><span class="lang-dot" style="width:7px;height:7px;border-radius:99px;background:${color}"></span>${lang || 'text'}</div>
       <div class="cb-head-right">
         <button class="cb-btn copy-btn"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${window.ICONS.copy}</svg>copy</button>
       </div>
     </div>
     <div class="cb-body">
       <div class="cb-gutter">${lines.map((_, i) => `<span class="ln">${i + 1}</span>`).join('')}</div>
       <div class="cb-code">${lines.map((ln) => `<span class="cb-line">${window.highlightLine(ln, lang) || '&nbsp;'}</span>`).join('')}</div>
     </div>`;

  const btn = cb.querySelector('.copy-btn');
  btn.addEventListener('click', () => {
    navigator.clipboard && navigator.clipboard.writeText(code).catch(() => {});
    btn.classList.add('copied');
    btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${window.ICONS.check}</svg>copied`;
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${window.ICONS.copy}</svg>copy`;
    }, 1400);
  });
  return cb;
}

// resolve an internal markdown link to a doc id
function resolveDocId(href, docId) {
  let h = href.split('#')[0];
  if (!h) return null;
  h = h.replace(/\.md$/, '');
  const baseParts = docId.split('/').slice(0, -1);
  if (h.startsWith('/')) {
    baseParts.length = 0;
    h = h.replace(/^\//, '').replace(/^docs\//, '');
  }
  const segs = h.split('/');
  const stack = baseParts.slice();
  for (const s of segs) {
    if (s === '' || s === '.') continue;
    if (s === '..') stack.pop();
    else stack.push(s);
  }
  let id = stack.join('/');
  if (href.replace(/#.*$/, '').endsWith('/') || segs[segs.length - 1] === '') id += '/index';
  return id;
}

function enhance(container, onNav, docId) {
  // code fences + mermaid
  container.querySelectorAll('pre > code').forEach((codeEl) => {
    const pre = codeEl.parentElement;
    const cls = codeEl.className || '';
    const langMatch = cls.match(/language-([\w-]+)/);
    const lang = langMatch ? langMatch[1] : '';
    const text = codeEl.textContent;
    if (lang === 'mermaid') {
      const wrap = document.createElement('div');
      wrap.className = 'cb-mermaid';
      const inner = document.createElement('div');
      inner.className = 'mermaid';
      inner.textContent = text;
      wrap.appendChild(inner);
      pre.replaceWith(wrap);
    } else {
      pre.replaceWith(buildCodeBlock(text, lang));
    }
  });

  // images — make absolute "/img/..." paths relative so they resolve at any mount point; lazy-load
  container.querySelectorAll('img[src]').forEach((img) => {
    const src = img.getAttribute('src');
    if (src && src.startsWith('/')) img.setAttribute('src', src.replace(/^\/+/, ''));
    img.loading = 'lazy';
  });

  // links
  container.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href');
    if (/^https?:/.test(href)) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    } else if (href.startsWith('#')) {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        const el = document.getElementById(href.slice(1));
        if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 78, behavior: 'smooth' });
      });
    } else {
      const target = resolveDocId(href, docId);
      a.addEventListener('click', (e) => { e.preventDefault(); if (target) onNav(target); });
    }
  });

  // headings -> ids + TOC (h2 only for the rail)
  const heads = [];
  container.querySelectorAll('h2, h3').forEach((h) => {
    const id = slugify(h.textContent);
    h.id = id;
    h.style.scrollMarginTop = '80px';
    if (h.tagName === 'H2') heads.push({ id, label: h.textContent });
  });

  // run mermaid if present
  if (window.mermaid && container.querySelector('.mermaid')) {
    try {
      window.mermaid.run({ nodes: container.querySelectorAll('.mermaid') });
    } catch (e) { /* ignore */ }
  }
  return heads;
}

/* ---------- section eyebrow from path ---------- */
const SECTION_LABEL = { reference: 'Reference', guides: 'Guides', tutorials: 'Tutorials', api: 'API', installation: 'Get started', index: 'Get started' };
function sectionOf(docId) {
  const first = docId.split('/')[0];
  return SECTION_LABEL[first] || 'Docs';
}

/* ---------- DocPage ---------- */
function DocPage({ docId, onNav }) {
  const [doc, setDoc] = useState(null);
  const [toc, setToc] = useState([]);
  const [tocActive, setTocActive] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    let alive = true;
    setDoc(null); setToc([]);
    fetch(docId + '.md')
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((md) => { if (alive) setDoc(renderMarkdown(md, docId)); })
      .catch(() => {
        if (alive) setDoc({ title: 'Page not available', html: `<p>This page (<code>${docId}.md</code>) isn’t in the demo yet.</p>` });
      });
    return () => { alive = false; };
  }, [docId]);

  useLayoutEffect(() => {
    if (!doc || !ref.current) return;
    const heads = enhance(ref.current, onNav, docId);
    setToc(heads);
    window.scrollTo({ top: 0 });
  }, [doc]);

  // scrollspy
  useEffect(() => {
    if (!toc.length) return;
    const ids = toc.map((i) => i.id);
    const onScroll = () => {
      let cur = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 120) cur = id;
      }
      setTocActive(cur);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, [toc]);

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 78, behavior: 'smooth' });
  };

  const crumbs = docId.split('/').filter((s) => s !== 'index');

  return (
    <div className="content-wrap">
      <article className="article">
        <div className="breadcrumb">
          <span>docs</span>
          {crumbs.map((c, i) => (
            <React.Fragment key={i}>
              <span className="sep">/</span>
              <span className={i === crumbs.length - 1 ? 'cur' : ''}>{c}</span>
            </React.Fragment>
          ))}
        </div>
        <div className="art-eyebrow">{sectionOf(docId)}</div>
        <h1 className="art-title">{doc ? doc.title : '\u00a0'}</h1>
        {doc ? (
          <div className="prose" ref={ref} dangerouslySetInnerHTML={{ __html: doc.html }} />
        ) : (
          <div className="doc-loading">loading {docId}.md …</div>
        )}
      </article>
      <Toc items={toc} activeId={tocActive} onNav={scrollTo} />
    </div>
  );
}

Object.assign(window, { DocPage, renderMarkdown });
