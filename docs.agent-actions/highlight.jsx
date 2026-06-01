// highlight.jsx — tiny, dependency-free syntax highlighter.
// Not a real parser; a pragmatic tokenizer good enough for docs samples.
// Returns an array of React nodes per line so we can wrap lines for highlighting.

(function () {
  const KEYWORDS = {
    js: ['import','from','export','default','const','let','var','function','return','await','async','new','class','extends','if','else','for','while','of','in','typeof','instanceof','try','catch','throw','this','null','undefined','true','false','yield','static','super','void'],
    ts: ['import','from','export','default','const','let','var','function','return','await','async','new','class','extends','implements','interface','type','enum','public','private','readonly','if','else','for','while','of','in','typeof','as','try','catch','throw','this','null','undefined','true','false','string','number','boolean','void','never','any','unknown','Promise'],
    bash: ['cd','ls','cat','echo','export','sudo','npm','npx','pnpm','yarn','git','curl','mkdir','rm','cp','mv','agac','run','build','dev','add','install','init'],
    json: ['true','false','null'],
    yaml: [],
    python: ['import','from','as','def','return','await','async','class','if','elif','else','for','while','in','not','and','or','is','None','True','False','try','except','finally','raise','with','yield','lambda','pass','break','continue','global','self'],
    py: ['import','from','as','def','return','await','async','class','if','elif','else','for','while','in','not','and','or','is','None','True','False','try','except','finally','raise','with','yield','lambda','pass','break','continue','global','self'],
  };

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ---- dedicated YAML highlighter ----
  function highlightYaml(line) {
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // locate a trailing comment ("#" preceded by whitespace/start, not inside quotes)
    let cIdx = -1, quote = null;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (quote) { if (c === quote) quote = null; }
      else if (c === '"' || c === "'") quote = c;
      else if (c === '#' && (i === 0 || /\s/.test(line[i - 1]))) { cIdx = i; break; }
    }
    let code = cIdx === -1 ? line : line.slice(0, cIdx);
    const comment = cIdx === -1 ? '' : line.slice(cIdx);

    const colorVal = (v) => {
      if (!v) return '';
      const t = v.trim();
      const lead = v.slice(0, v.length - v.trimStart().length);
      let inner;
      if (/^(['"]).*\1$/.test(t) || /^['"]/.test(t)) inner = `<span class="tok-string">${esc(t)}</span>`;
      else if (/^-?\d+(\.\d+)?$/.test(t)) inner = `<span class="tok-number">${esc(t)}</span>`;
      else if (/^(true|false|null|yes|no|on|off)$/i.test(t)) inner = `<span class="tok-keyword">${esc(t)}</span>`;
      else if (t[0] === '$') inner = `<span class="tok-func">${esc(t)}</span>`;
      else if (t[0] === '{' || t[0] === '[' || t[0] === '&' || t[0] === '*' || t[0] === '|' || t[0] === '>')
        inner = esc(t); // flow/block scalars — keep neutral
      else inner = esc(t); // plain scalar value — neutral/bright for readability
      return lead + inner;
    };

    let out = '';
    // leading indent + list markers ("- " possibly repeated)
    const lead = code.match(/^(\s*)((?:-\s+)*)/);
    let rest = code;
    if (lead) {
      out += lead[1] + lead[2].replace(/-/g, '<span class="tok-punc">-</span>');
      rest = code.slice(lead[0].length);
    }

    // key: value
    const kv = rest.match(/^([\w.$/-]+):(\s|$)([\s\S]*)$/);
    if (kv) {
      out += `<span class="tok-prop">${esc(kv[1])}</span><span class="tok-punc">:</span>`;
      out += kv[2] === ' ' ? ' ' : '';
      out += colorVal(kv[3]);
    } else {
      out += colorVal(rest);
    }

    if (comment) out += `<span class="tok-comment">${esc(comment)}</span>`;
    return out || '&nbsp;';
  }

  // Returns an HTML string with <span class="tok-*"> wrappers.
  function highlightLine(line, lang) {
    if (lang === 'yaml') return highlightYaml(line);
    const kw = KEYWORDS[lang] || KEYWORDS.js;
    let out = '';
    let i = 0;
    const n = line.length;

    const isWord = (c) => /[A-Za-z0-9_$]/.test(c);

    while (i < n) {
      const rest = line.slice(i);

      // line comments
      if (rest.startsWith('//') || ((lang === 'bash' || lang === 'yaml' || lang === 'python' || lang === 'py') && rest.startsWith('#'))) {
        out += `<span class="tok-comment">${esc(rest)}</span>`;
        break;
      }
      // block comment (single-line slice)
      if (rest.startsWith('/*')) {
        const end = rest.indexOf('*/');
        const seg = end === -1 ? rest : rest.slice(0, end + 2);
        out += `<span class="tok-comment">${esc(seg)}</span>`;
        i += seg.length;
        continue;
      }
      // strings
      const q = line[i];
      if (q === '"' || q === "'" || q === '`') {
        let j = i + 1;
        while (j < n && line[j] !== q) { if (line[j] === '\\') j++; j++; }
        const seg = line.slice(i, Math.min(j + 1, n));
        out += `<span class="tok-string">${esc(seg)}</span>`;
        i = j + 1;
        continue;
      }
      // numbers
      if (/[0-9]/.test(q) && (i === 0 || !isWord(line[i-1]))) {
        let j = i;
        while (j < n && /[0-9a-fx._]/i.test(line[j])) j++;
        out += `<span class="tok-number">${esc(line.slice(i, j))}</span>`;
        i = j;
        continue;
      }
      // words (keywords / functions / props)
      if (isWord(q)) {
        let j = i;
        while (j < n && isWord(line[j])) j++;
        const word = line.slice(i, j);
        const next = line[j];
        let cls = '';
        if (kw.includes(word)) cls = 'tok-keyword';
        else if (next === '(') cls = 'tok-func';
        else if (/^[A-Z]/.test(word)) cls = 'tok-type';
        else if (next === ':' && lang !== 'ts') cls = 'tok-prop';
        if (cls) out += `<span class="${cls}">${esc(word)}</span>`;
        else out += esc(word);
        i = j;
        continue;
      }
      // punctuation cluster
      if (/[{}()\[\].,;:=+\-*/<>!&|?%]/.test(q)) {
        out += `<span class="tok-punc">${esc(q)}</span>`;
        i++;
        continue;
      }
      out += esc(q);
      i++;
    }
    return out;
  }

  window.highlightLine = highlightLine;
})();
