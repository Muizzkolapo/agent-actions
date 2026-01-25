import React, { useState, useMemo } from 'react';

// ============================================
// DYNAMIC PROMPT RENDERER
// Parses any markdown prompt template and renders it
// ============================================

const DynamicPromptRenderer = ({ 
  promptContent, 
  promptMeta = {} 
}) => {
  const [viewMode, setViewMode] = useState('rendered');
  const [copied, setCopied] = useState(false);
  const [expandedSections, setExpandedSections] = useState({});

  // Default metadata
  const meta = {
    name: promptMeta.name || 'Untitled Prompt',
    source: promptMeta.source || 'unknown.md',
    lines: promptMeta.lines || '1 - 100',
    chars: promptContent?.length || 0,
    lastModified: promptMeta.lastModified || 'Unknown',
    version: promptMeta.version || 'v1.0',
    ...promptMeta
  };

  // ============================================
  // PARSER: Convert markdown to structured tokens
  // ============================================
  const parsePrompt = (content) => {
    if (!content) return [];
    
    const lines = content.split('\n');
    const tokens = [];
    let i = 0;
    
    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();
      
      // Skip empty lines (but track them for spacing)
      if (!trimmed) {
        if (tokens.length > 0 && tokens[tokens.length - 1].type !== 'spacer') {
          tokens.push({ type: 'spacer' });
        }
        i++;
        continue;
      }
      
      // H1 Header: # Title
      if (/^# /.test(trimmed)) {
        tokens.push({ type: 'h1', content: trimmed.slice(2) });
        i++;
        continue;
      }
      
      // H2 Header: ## Title
      if (/^## /.test(trimmed)) {
        tokens.push({ type: 'h2', content: trimmed.slice(3) });
        i++;
        continue;
      }
      
      // H3 Header: ### Title
      if (/^### /.test(trimmed)) {
        tokens.push({ type: 'h3', content: trimmed.slice(4) });
        i++;
        continue;
      }
      
      // Code block: ```
      if (/^```/.test(trimmed)) {
        const lang = trimmed.slice(3).trim();
        const codeLines = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i]);
          i++;
        }
        tokens.push({ type: 'codeblock', lang, content: codeLines.join('\n') });
        i++; // skip closing ```
        continue;
      }
      
      // Unordered list item: - item or * item
      if (/^[-*] /.test(trimmed)) {
        const listItems = [];
        while (i < lines.length && /^[-*] /.test(lines[i].trim())) {
          listItems.push(lines[i].trim().slice(2));
          i++;
        }
        tokens.push({ type: 'ul', items: listItems });
        continue;
      }
      
      // Ordered list item: 1. item
      if (/^\d+\. /.test(trimmed)) {
        const listItems = [];
        while (i < lines.length && /^\d+\. /.test(lines[i].trim())) {
          listItems.push(lines[i].trim().replace(/^\d+\. /, ''));
          i++;
        }
        tokens.push({ type: 'ol', items: listItems });
        continue;
      }
      
      // Blockquote: > text
      if (/^> /.test(trimmed)) {
        const quoteLines = [];
        while (i < lines.length && /^> /.test(lines[i].trim())) {
          quoteLines.push(lines[i].trim().slice(2));
          i++;
        }
        tokens.push({ type: 'blockquote', content: quoteLines.join('\n') });
        continue;
      }
      
      // Horizontal rule: --- or ***
      if (/^(---|\*\*\*)$/.test(trimmed)) {
        tokens.push({ type: 'hr' });
        i++;
        continue;
      }
      
      // Regular paragraph
      const paraLines = [];
      while (i < lines.length && lines[i].trim() && 
             !/^(#{1,3} |```|[-*] |\d+\. |> |---|\*\*\*)/.test(lines[i].trim())) {
        paraLines.push(lines[i].trim());
        i++;
      }
      if (paraLines.length > 0) {
        tokens.push({ type: 'paragraph', content: paraLines.join(' ') });
      }
    }
    
    return tokens;
  };

  // ============================================
  // INLINE PARSER: Handle inline formatting
  // ============================================
  const parseInline = (text) => {
    if (!text) return null;
    
    const elements = [];
    let remaining = text;
    let key = 0;
    
    while (remaining.length > 0) {
      // Template variable: {{ variable }}
      let match = remaining.match(/^(.*?)\{\{\s*([^}]+)\s*\}\}/);
      if (match) {
        if (match[1]) elements.push(<span key={key++}>{parseInlineFormatting(match[1])}</span>);
        elements.push(
          <span key={key++} className="variable-tag">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="4,7 4,4 20,4 20,7"/>
              <line x1="9" y1="20" x2="15" y2="20"/>
              <line x1="12" y1="4" x2="12" y2="20"/>
            </svg>
            {match[2].trim()}
          </span>
        );
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // {variable} style
      match = remaining.match(/^(.*?)\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/);
      if (match && !match[1].endsWith('\\')) {
        if (match[1]) elements.push(<span key={key++}>{parseInlineFormatting(match[1])}</span>);
        elements.push(
          <span key={key++} className="variable-tag-alt">
            {match[2]}
          </span>
        );
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // No more special patterns, parse remaining with formatting
      elements.push(<span key={key++}>{parseInlineFormatting(remaining)}</span>);
      break;
    }
    
    return elements;
  };

  // Parse bold, italic, code, etc.
  const parseInlineFormatting = (text) => {
    if (!text) return null;
    
    const parts = [];
    let remaining = text;
    let key = 0;
    
    while (remaining.length > 0) {
      // Bold + Italic: ***text*** or ___text___
      let match = remaining.match(/^(.*?)(\*\*\*|___)(.+?)\2/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<strong key={key++}><em>{match[3]}</em></strong>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // Bold: **text** or __text__
      match = remaining.match(/^(.*?)(\*\*|__)(.+?)\2/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<strong key={key++} className="text-bold">{match[3]}</strong>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // Italic: *text* or _text_
      match = remaining.match(/^(.*?)(\*|_)(.+?)\2/);
      if (match && !match[1].endsWith('\\')) {
        if (match[1]) parts.push(match[1]);
        parts.push(<em key={key++}>{match[3]}</em>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // Inline code: `code`
      match = remaining.match(/^(.*?)`([^`]+)`/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<code key={key++} className="inline-code">{match[2]}</code>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // Emoji indicators: ✅ ❌ ✓ ✗
      match = remaining.match(/^(.*?)(✅|✓)/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<span key={key++} className="check-icon">✓</span>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      match = remaining.match(/^(.*?)(❌|✗)/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<span key={key++} className="x-icon">✗</span>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      // No more patterns
      parts.push(remaining);
      break;
    }
    
    return parts;
  };

  // ============================================
  // DETECT SPECIAL CONTENT PATTERNS
  // ============================================
  const detectPattern = (text) => {
    const lower = text.toLowerCase();
    
    if (/^(critical|important|warning|caution|danger)/i.test(text.replace(/[*_:#]/g, '').trim())) {
      return 'critical';
    }
    if (/^(note|tip|info|hint)/i.test(text.replace(/[*_:#]/g, '').trim())) {
      return 'info';
    }
    if (/what you (can|should|must) do/i.test(lower) || /^(allowed|permitted|do this)/i.test(lower)) {
      return 'can-do';
    }
    if (/what you (cannot|can't|should not|must not) do/i.test(lower) || /^(not allowed|forbidden|don't|avoid)/i.test(lower)) {
      return 'cannot-do';
    }
    if (/example/i.test(lower)) {
      return 'example';
    }
    if (/output|result|response/i.test(lower)) {
      return 'output';
    }
    if (/input|task|context/i.test(lower)) {
      return 'input';
    }
    if (/constraint|restriction|rule|requirement/i.test(lower)) {
      return 'constraint';
    }
    return null;
  };

  // ============================================
  // EXTRACT VARIABLES FROM CONTENT
  // ============================================
  const extractVariables = (content) => {
    const vars = new Set();
    
    // {{ variable }} style
    const matches1 = content.matchAll(/\{\{\s*([^}]+)\s*\}\}/g);
    for (const m of matches1) vars.add(m[1].trim());
    
    // {variable} style (only valid identifiers)
    const matches2 = content.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g);
    for (const m of matches2) vars.add(m[1]);
    
    return Array.from(vars).map(v => ({
      name: v,
      type: inferType(v)
    }));
  };

  const inferType = (varName) => {
    const lower = varName.toLowerCase();
    if (lower.includes('content') || lower.includes('text') || lower.includes('doc')) return 'text';
    if (lower.includes('code')) return 'code';
    if (lower.includes('list') || lower.includes('array')) return 'array';
    if (lower.includes('count') || lower.includes('number') || lower.includes('num')) return 'number';
    if (lower.includes('flag') || lower.includes('is_') || lower.includes('has_')) return 'boolean';
    return 'string';
  };

  // ============================================
  // MEMOIZED PARSING
  // ============================================
  const tokens = useMemo(() => parsePrompt(promptContent), [promptContent]);
  const variables = useMemo(() => extractVariables(promptContent || ''), [promptContent]);

  // ============================================
  // COPY HANDLER
  // ============================================
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(promptContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // ============================================
  // RENDER TOKENS
  // ============================================
  const renderToken = (token, index, allTokens) => {
    const prevToken = index > 0 ? allTokens[index - 1] : null;
    const pattern = token.content ? detectPattern(token.content) : null;
    
    switch (token.type) {
      case 'spacer':
        return <div key={index} style={{ height: 8 }} />;
        
      case 'h1':
        return (
          <h1 key={index} className="token-h1">
            {parseInline(token.content)}
          </h1>
        );
        
      case 'h2':
        return (
          <div key={index} className={`section-block ${pattern || ''}`}>
            <div className="section-header">
              <div className={`section-icon ${pattern || ''}`}>
                {getSectionIcon(token.content, pattern)}
              </div>
              <h2>{parseInline(token.content)}</h2>
            </div>
          </div>
        );
        
      case 'h3':
        return (
          <h3 key={index} className={`token-h3 ${pattern || ''}`}>
            {parseInline(token.content)}
          </h3>
        );
        
      case 'paragraph':
        // Check if this looks like a critical/warning message
        if (pattern === 'critical') {
          return (
            <div key={index} className="critical-box">
              <div className="critical-header">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/>
                  <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                <span>Critical</span>
              </div>
              <p>{parseInline(token.content.replace(/^\**(critical|important|warning)[:\s]*/i, ''))}</p>
            </div>
          );
        }
        
        if (pattern === 'info') {
          return (
            <div key={index} className="info-box">
              <div className="info-header">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/>
                  <line x1="12" y1="16" x2="12" y2="12"/>
                  <line x1="12" y1="8" x2="12.01" y2="8"/>
                </svg>
                <span>Note</span>
              </div>
              <p>{parseInline(token.content.replace(/^\**(note|tip|info|hint)[:\s]*/i, ''))}</p>
            </div>
          );
        }
        
        return (
          <p key={index} className="token-paragraph">
            {parseInline(token.content)}
          </p>
        );
        
      case 'codeblock':
        return (
          <div key={index} className="codeblock-wrapper">
            {token.lang && <div className="codeblock-lang">{token.lang}</div>}
            <pre className="codeblock">
              <code>{token.content}</code>
            </pre>
          </div>
        );
        
      case 'ul':
        // Detect if this is a can-do or cannot-do list based on previous header
        const listPattern = prevToken?.content ? detectPattern(prevToken.content) : null;
        
        return (
          <ul key={index} className={`token-ul ${listPattern || ''}`}>
            {token.items.map((item, i) => (
              <li key={i} className={getListItemClass(item)}>
                {getListIcon(item, listPattern)}
                <span>{parseInline(item)}</span>
              </li>
            ))}
          </ul>
        );
        
      case 'ol':
        return (
          <ol key={index} className="token-ol">
            {token.items.map((item, i) => (
              <li key={i}>
                <span className="ol-number">{i + 1}</span>
                <span>{parseInline(item)}</span>
              </li>
            ))}
          </ol>
        );
        
      case 'blockquote':
        return (
          <blockquote key={index} className="token-blockquote">
            {parseInline(token.content)}
          </blockquote>
        );
        
      case 'hr':
        return <hr key={index} className="token-hr" />;
        
      default:
        return null;
    }
  };

  const getSectionIcon = (content, pattern) => {
    const lower = content.toLowerCase();
    
    if (pattern === 'critical' || pattern === 'constraint' || lower.includes('constraint') || lower.includes('critical')) {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      );
    }
    if (lower.includes('example')) {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="16,18 22,12 16,6"/>
          <polyline points="8,6 2,12 8,18"/>
        </svg>
      );
    }
    if (lower.includes('output') || lower.includes('result')) {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7,10 12,15 17,10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      );
    }
    if (lower.includes('input') || lower.includes('context') || lower.includes('task')) {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22,4 12,14.01 9,11.01"/>
        </svg>
      );
    }
    if (lower.includes('source') || lower.includes('document') || lower.includes('reference')) {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14,2 14,8 20,8"/>
        </svg>
      );
    }
    
    // Default icon
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10"/>
      </svg>
    );
  };

  const getListItemClass = (item) => {
    if (/^(✅|✓|CORRECT)/.test(item)) return 'list-item-correct';
    if (/^(❌|✗|WRONG|DO NOT|DON'T)/.test(item.toUpperCase())) return 'list-item-wrong';
    return '';
  };

  const getListIcon = (item, listPattern) => {
    if (/^(✅|✓)/.test(item) || listPattern === 'can-do') {
      return (
        <svg className="list-icon can" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="20,6 9,17 4,12"/>
        </svg>
      );
    }
    if (/^(❌|✗)/.test(item) || listPattern === 'cannot-do') {
      return (
        <svg className="list-icon cannot" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      );
    }
    return <span className="list-bullet">•</span>;
  };

  // ============================================
  // RENDER
  // ============================================
  return (
    <div className="prompt-renderer">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');
        
        .prompt-renderer {
          min-height: 100vh;
          background: #09090b;
          color: #e4e4e7;
          font-family: 'IBM Plex Sans', -apple-system, sans-serif;
          font-size: 14px;
          line-height: 1.6;
        }
        
        .prompt-renderer * { box-sizing: border-box; }
        
        .prompt-renderer ::-webkit-scrollbar { width: 6px; height: 6px; }
        .prompt-renderer ::-webkit-scrollbar-track { background: #18181b; }
        .prompt-renderer ::-webkit-scrollbar-thumb { background: #3f3f46; border-radius: 3px; }
        
        /* Layout */
        .pr-layout { display: flex; min-height: 100vh; }
        
        .pr-sidebar {
          width: 220px;
          border-right: 1px solid #27272a;
          padding: 20px 12px;
          position: sticky;
          top: 0;
          height: 100vh;
          overflow-y: auto;
          flex-shrink: 0;
        }
        
        .pr-logo {
          padding: 8px 12px;
          margin-bottom: 20px;
        }
        
        .pr-logo-text {
          font-family: 'Fraunces', serif;
          font-size: 18px;
          font-weight: 600;
          color: #fafafa;
          letter-spacing: -0.02em;
        }
        
        .pr-logo-sub {
          font-size: 11px;
          color: #52525b;
          margin-top: 2px;
        }
        
        .nav-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 9px 12px;
          color: #71717a;
          border-radius: 6px;
          font-size: 13px;
          cursor: pointer;
          transition: all 0.15s;
          margin-bottom: 2px;
        }
        
        .nav-item:hover { background: #18181b; color: #a1a1aa; }
        .nav-item.active { background: #1e1b4b; color: #a5b4fc; }
        
        .pr-main {
          flex: 1;
          padding: 28px 40px;
          max-width: 900px;
        }
        
        /* Breadcrumb */
        .pr-breadcrumb {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          color: #52525b;
          margin-bottom: 20px;
        }
        
        .pr-breadcrumb span { cursor: pointer; }
        .pr-breadcrumb span:hover { color: #71717a; }
        .pr-breadcrumb .current { color: #a1a1aa; }
        
        /* Header */
        .pr-header { margin-bottom: 28px; }
        
        .pr-header-top {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          margin-bottom: 16px;
        }
        
        .pr-title {
          font-family: 'Fraunces', serif;
          font-size: 28px;
          font-weight: 600;
          color: #fafafa;
          margin: 0;
          letter-spacing: -0.02em;
        }
        
        .pr-badges {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-top: 10px;
        }
        
        .pr-type-badge {
          padding: 3px 10px;
          background: linear-gradient(135deg, #4338ca, #6366f1);
          border-radius: 4px;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #fff;
        }
        
        .pr-meta-pill {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 3px 9px;
          background: #18181b;
          border: 1px solid #27272a;
          border-radius: 12px;
          font-size: 11px;
          color: #71717a;
        }
        
        .pr-actions { display: flex; gap: 8px; }
        
        .pr-btn {
          padding: 8px 14px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: all 0.15s;
          border: none;
        }
        
        .pr-btn-secondary {
          background: #18181b;
          border: 1px solid #27272a;
          color: #a1a1aa;
        }
        
        .pr-btn-secondary:hover { background: #27272a; color: #e4e4e7; }
        
        .pr-btn-primary {
          background: linear-gradient(135deg, #4338ca, #6366f1);
          color: #fff;
        }
        
        .pr-btn-primary:hover { opacity: 0.9; }
        
        /* Meta bar */
        .pr-meta-bar {
          display: flex;
          align-items: center;
          gap: 20px;
          padding: 12px 16px;
          background: #0f0f11;
          border: 1px solid #1f1f23;
          border-radius: 8px;
          font-size: 12px;
        }
        
        .pr-meta-item {
          display: flex;
          align-items: center;
          gap: 6px;
          color: #52525b;
        }
        
        .pr-meta-item .value { color: #a1a1aa; }
        .pr-meta-item .highlight { color: #a5b4fc; font-family: 'IBM Plex Mono', monospace; font-size: 11px; }
        
        .pr-meta-divider { width: 1px; height: 16px; background: #27272a; }
        
        /* Tabs */
        .pr-tabs-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 20px;
          padding-bottom: 12px;
          border-bottom: 1px solid #1f1f23;
        }
        
        .pr-tabs-label {
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          color: #3f3f46;
        }
        
        .pr-tabs {
          display: flex;
          gap: 2px;
          background: #0f0f11;
          padding: 3px;
          border-radius: 6px;
        }
        
        .pr-tab {
          padding: 6px 12px;
          font-size: 12px;
          font-weight: 500;
          border: none;
          background: transparent;
          color: #52525b;
          cursor: pointer;
          border-radius: 4px;
          transition: all 0.15s;
          display: flex;
          align-items: center;
          gap: 5px;
        }
        
        .pr-tab:hover { color: #a1a1aa; }
        .pr-tab.active { background: #27272a; color: #fafafa; }
        
        /* Content styles */
        .pr-content { padding-left: 4px; }
        
        .token-h1 {
          font-family: 'Fraunces', serif;
          font-size: 24px;
          font-weight: 600;
          color: #fafafa;
          margin: 0 0 16px 0;
          letter-spacing: -0.02em;
        }
        
        .section-block { margin: 24px 0 12px 0; }
        
        .section-header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding-bottom: 8px;
          border-bottom: 1px solid #1f1f23;
        }
        
        .section-icon {
          width: 26px;
          height: 26px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #18181b;
          border: 1px solid #27272a;
          border-radius: 5px;
          color: #71717a;
        }
        
        .section-icon.critical, .section-icon.constraint { color: #f87171; border-color: #7f1d1d; background: #1a0a0a; }
        .section-icon.can-do { color: #4ade80; border-color: #166534; background: #0a1a0a; }
        .section-icon.cannot-do { color: #f87171; border-color: #7f1d1d; background: #1a0a0a; }
        .section-icon.example { color: #fbbf24; border-color: #78350f; background: #1a1400; }
        .section-icon.output { color: #4ade80; border-color: #166534; background: #0a1a0a; }
        .section-icon.input { color: #38bdf8; border-color: #0c4a6e; background: #0a1a1f; }
        
        .section-header h2 {
          font-family: 'Fraunces', serif;
          font-size: 16px;
          font-weight: 500;
          color: #e4e4e7;
          margin: 0;
        }
        
        .token-h3 {
          font-size: 14px;
          font-weight: 600;
          color: #d4d4d8;
          margin: 20px 0 8px 0;
        }
        
        .token-h3.can-do { color: #4ade80; }
        .token-h3.cannot-do { color: #f87171; }
        
        .token-paragraph {
          color: #a1a1aa;
          margin: 0 0 12px 0;
          line-height: 1.7;
        }
        
        .text-bold { color: #e4e4e7; font-weight: 600; }
        
        /* Variables */
        .variable-tag {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 2px 8px;
          background: linear-gradient(135deg, #1e1b4b, #312e81);
          border: 1px solid #4338ca;
          border-radius: 4px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          color: #a5b4fc;
          vertical-align: middle;
        }
        
        .variable-tag-alt {
          display: inline;
          padding: 1px 6px;
          background: #1c1917;
          border: 1px solid #44403c;
          border-radius: 3px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          color: #fbbf24;
        }
        
        .inline-code {
          padding: 2px 6px;
          background: #18181b;
          border: 1px solid #27272a;
          border-radius: 3px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          color: #fbbf24;
        }
        
        /* Code blocks */
        .codeblock-wrapper {
          margin: 12px 0;
          border-radius: 8px;
          overflow: hidden;
          border: 1px solid #27272a;
        }
        
        .codeblock-lang {
          padding: 6px 12px;
          background: #18181b;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10px;
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #52525b;
          border-bottom: 1px solid #27272a;
        }
        
        .codeblock {
          margin: 0;
          padding: 14px 16px;
          background: #0a0a0b;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          line-height: 1.6;
          color: #a1a1aa;
          overflow-x: auto;
        }
        
        .codeblock code { background: none; padding: 0; border: none; color: inherit; }
        
        /* Lists */
        .token-ul, .token-ol {
          margin: 8px 0;
          padding: 0;
          list-style: none;
        }
        
        .token-ul li, .token-ol li {
          display: flex;
          align-items: flex-start;
          gap: 10px;
          padding: 6px 0;
          color: #a1a1aa;
        }
        
        .list-bullet {
          color: #52525b;
          font-size: 18px;
          line-height: 1;
          margin-top: 2px;
        }
        
        .list-icon { flex-shrink: 0; margin-top: 3px; }
        .list-icon.can { color: #4ade80; }
        .list-icon.cannot { color: #f87171; }
        
        .token-ul.can-do li { color: #a1a1aa; }
        .token-ul.cannot-do li { color: #a1a1aa; }
        
        .list-item-correct { color: #a1a1aa; }
        .list-item-wrong { color: #a1a1aa; }
        
        .check-icon { color: #4ade80; font-weight: bold; }
        .x-icon { color: #f87171; font-weight: bold; }
        
        .ol-number {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 20px;
          height: 20px;
          background: #27272a;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 600;
          color: #a1a1aa;
          flex-shrink: 0;
        }
        
        /* Blockquote */
        .token-blockquote {
          margin: 12px 0;
          padding: 12px 16px;
          background: #0f0f11;
          border-left: 3px solid #3f3f46;
          border-radius: 0 6px 6px 0;
          color: #a1a1aa;
          font-style: italic;
        }
        
        .token-hr {
          border: none;
          height: 1px;
          background: #27272a;
          margin: 20px 0;
        }
        
        /* Special boxes */
        .critical-box {
          margin: 12px 0;
          padding: 14px 16px;
          background: linear-gradient(135deg, #1a0a0a, #0c0a09);
          border: 1px solid #7f1d1d;
          border-radius: 8px;
        }
        
        .critical-header {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 8px;
          color: #f87171;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        
        .critical-box p { margin: 0; color: #d4d4d8; }
        
        .info-box {
          margin: 12px 0;
          padding: 14px 16px;
          background: linear-gradient(135deg, #0a1520, #0a0a0b);
          border: 1px solid #1e3a5f;
          border-radius: 8px;
        }
        
        .info-header {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 8px;
          color: #38bdf8;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        
        .info-box p { margin: 0; color: #d4d4d8; }
        
        /* Variables view */
        .pr-variables-intro {
          color: #71717a;
          margin-bottom: 20px;
        }
        
        .pr-variables-table {
          background: #0f0f11;
          border: 1px solid #1f1f23;
          border-radius: 8px;
          overflow: hidden;
        }
        
        .pr-variables-header {
          display: grid;
          grid-template-columns: 1fr 80px;
          padding: 10px 16px;
          background: #18181b;
          border-bottom: 1px solid #27272a;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          color: #52525b;
        }
        
        .pr-variable-row {
          display: grid;
          grid-template-columns: 1fr 80px;
          padding: 12px 16px;
          border-bottom: 1px solid #1f1f23;
          align-items: center;
        }
        
        .pr-variable-row:last-child { border-bottom: none; }
        
        .pr-variable-name {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          color: #a5b4fc;
        }
        
        .pr-variable-type {
          padding: 2px 8px;
          background: #27272a;
          border-radius: 3px;
          font-size: 10px;
          color: #71717a;
          text-align: center;
        }
        
        /* Raw view */
        .pr-raw {
          background: #0a0a0b;
          border: 1px solid #1f1f23;
          border-radius: 8px;
          padding: 16px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          line-height: 1.6;
          color: #71717a;
          white-space: pre-wrap;
          word-break: break-word;
          max-height: 70vh;
          overflow: auto;
        }
        
        /* Empty state */
        .pr-empty {
          text-align: center;
          padding: 60px 20px;
          color: #52525b;
        }
        
        .pr-empty-icon {
          width: 48px;
          height: 48px;
          margin: 0 auto 16px;
          color: #3f3f46;
        }
      `}</style>

      <div className="pr-layout">
        {/* Sidebar */}
        <aside className="pr-sidebar">
          <div className="pr-logo">
            <div className="pr-logo-text">PromptHub</div>
            <div className="pr-logo-sub">Template Manager</div>
          </div>

          <div className="nav-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9,22 9,12 15,12 15,22"/>
            </svg>
            Overview
          </div>
          
          <div className="nav-item active">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
            Prompts
          </div>
          
          <div className="nav-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <line x1="3" y1="9" x2="21" y2="9"/>
              <line x1="9" y1="21" x2="9" y2="9"/>
            </svg>
            Datasets
          </div>
          
          <div className="nav-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
            </svg>
            Runs
          </div>
          
          <div className="nav-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v6m0 6v6"/>
            </svg>
            Settings
          </div>
        </aside>

        {/* Main */}
        <main className="pr-main">
          {/* Breadcrumb */}
          <nav className="pr-breadcrumb">
            <span>Overview</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9,18 15,12 9,6"/>
            </svg>
            <span>Prompts</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9,18 15,12 9,6"/>
            </svg>
            <span className="current">{meta.name}</span>
          </nav>

          {/* Header */}
          <header className="pr-header">
            <div className="pr-header-top">
              <div>
                <h1 className="pr-title">{meta.name}</h1>
                <div className="pr-badges">
                  <span className="pr-type-badge">Prompt</span>
                  <span className="pr-meta-pill">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10"/>
                      <polyline points="12,6 12,12 16,14"/>
                    </svg>
                    {meta.lastModified}
                  </span>
                  <span className="pr-meta-pill">{meta.version}</span>
                </div>
              </div>
              
              <div className="pr-actions">
                <button className="pr-btn pr-btn-secondary">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                  Edit
                </button>
                <button className="pr-btn pr-btn-primary">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="5,3 19,12 5,21"/>
                  </svg>
                  Run
                </button>
              </div>
            </div>

            <div className="pr-meta-bar">
              <div className="pr-meta-item">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14,2 14,8 20,8"/>
                </svg>
                <span className="highlight">{meta.source}</span>
              </div>
              <div className="pr-meta-divider"/>
              <div className="pr-meta-item">
                Lines: <span className="value">{meta.lines}</span>
              </div>
              <div className="pr-meta-divider"/>
              <div className="pr-meta-item">
                <span className="value">{meta.chars.toLocaleString()}</span> chars
              </div>
              <div className="pr-meta-divider"/>
              <div className="pr-meta-item">
                <span className="value">{variables.length}</span> variables
              </div>
            </div>
          </header>

          {/* Tabs */}
          <div className="pr-tabs-row">
            <span className="pr-tabs-label">Prompt Content</span>
            <div className="pr-tabs">
              <button 
                className={`pr-tab ${viewMode === 'rendered' ? 'active' : ''}`}
                onClick={() => setViewMode('rendered')}
              >
                Rendered
              </button>
              <button 
                className={`pr-tab ${viewMode === 'raw' ? 'active' : ''}`}
                onClick={() => setViewMode('raw')}
              >
                Raw
              </button>
              <button 
                className={`pr-tab ${viewMode === 'variables' ? 'active' : ''}`}
                onClick={() => setViewMode('variables')}
              >
                Variables
              </button>
              <button className="pr-tab" onClick={handleCopy}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="9" y="9" width="13" height="13" rx="2"/>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
          </div>

          {/* Content */}
          {viewMode === 'rendered' && (
            <div className="pr-content">
              {tokens.length > 0 ? (
                tokens.map((token, i) => renderToken(token, i, tokens))
              ) : (
                <div className="pr-empty">
                  <svg className="pr-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14,2 14,8 20,8"/>
                  </svg>
                  <p>No prompt content to display</p>
                </div>
              )}
            </div>
          )}

          {viewMode === 'variables' && (
            <div>
              <p className="pr-variables-intro">
                This prompt uses <strong>{variables.length}</strong> template variable{variables.length !== 1 ? 's' : ''} that will be interpolated at runtime.
              </p>
              {variables.length > 0 ? (
                <div className="pr-variables-table">
                  <div className="pr-variables-header">
                    <span>Variable Name</span>
                    <span>Type</span>
                  </div>
                  {variables.map((v, i) => (
                    <div key={i} className="pr-variable-row">
                      <code className="pr-variable-name">{'{{ '}{v.name}{' }}'}</code>
                      <span className="pr-variable-type">{v.type}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="pr-empty">
                  <p>No variables detected in this prompt</p>
                </div>
              )}
            </div>
          )}

          {viewMode === 'raw' && (
            <pre className="pr-raw">{promptContent || 'No content'}</pre>
          )}
        </main>
      </div>
    </div>
  );
};

// ============================================
// DEMO WITH SAMPLE PROMPT
// ============================================
const samplePrompt = `You are creating the CORRECT, IDIOMATIC code implementation for a focused learning scenario.

**Works with ANY language/technology:** Python, Terraform, Azure CLI, Kubernetes, Bash, SQL, Docker, etc.

**CRITICAL: Ground your code in the source documentation. Follow best practices and patterns documented in the source material.**

## SOURCE DOCUMENTATION

Title: {{ source.title }}

Documentation:
\`\`\`
{{ source.page_content }}
\`\`\`

## TASK CONTEXT

- Scenario: {{ code_usage_scenario.sample_usage_scenario }}
- Base Code: {{ code_usage_scenario.code_for_scenario }}
- Complexity: {{ code_usage_scenario.scenario_complexity }}
- Considerations: {{ code_usage_scenario.key_considerations }}

## CRITICAL CONSTRAINTS

- The optimal code must be PURELY GROUNDED in the provided documentation and code_for_scenario
- Do NOT add ANY flags, parameters, configuration, or code elements not present in {code_for_scenario} OR mentioned in the source docs
- Do NOT add complexity beyond what's in {code_for_scenario}
- Keep the EXACT SAME flags/parameters/config as {code_for_scenario}
- Only fix syntax errors or make the existing code idiomatic based on patterns shown in the source documentation
- Use ONLY information from: source documentation, sample_usage_scenario, code_for_scenario, key_considerations

**Your task:**
Take {code_for_scenario} and make MINIMAL corrections to ensure it's syntactically correct and follows best practices FROM THE SOURCE DOCUMENTATION. Do NOT add anything new.

**What you CAN do:**
- Fix syntax errors in {code_for_scenario}
- Correct parameter/flag/argument formatting
- Fix quote styles, indentation, spacing
- Make idiomatic what's already there (e.g., proper Python conventions, Terraform best practices, etc.)
- Preserve the language/framework's syntax rules

**What you CANNOT do:**
- Add flags/parameters/config not in {code_for_scenario}
- Add imports, modules, or dependencies not in {code_for_scenario}
- Combine multiple concepts if {code_for_scenario} has one concept
- Add code from page_content that's not in {code_for_scenario}
- Expand beyond the length of {code_for_scenario}
- Wrap in functions/scripts if {code_for_scenario} is a simple command/statement
- Add error handling, logging, or production features
- Change the technology/framework (if it's Python, keep it Python; if it's Terraform, keep it Terraform)

**Examples across technologies:**

Python:
- Input: \`data = json.load(open('file.json'))\`
- ✅ CORRECT: \`data = json.load(open('file.json'))\` (already correct)
- ❌ WRONG: \`with open('file.json') as f: data = json.load(f)\` (added context manager not in input)

Terraform:
- Input: \`resource "aws_instance" "app" { ami = "ami-123" }\`
- ✅ CORRECT: \`resource "aws_instance" "app" { ami = "ami-123" }\`
- ❌ WRONG: \`resource "aws_instance" "app" { ami = "ami-123" instance_type = "t2.micro" }\` (added property)

Azure CLI:
- Input: \`az vm create --name myVM --resource-group myRG\`
- ✅ CORRECT: \`az vm create --name myVM --resource-group myRG\`
- ❌ WRONG: \`az vm create --name myVM --resource-group myRG --location eastus\` (added flag)

Provide only:
- optimal_code: The MINIMALLY corrected version of {code_for_scenario} (same flags/parameters, just syntactically correct and idiomatic)`;

export default function App() {
  return (
    <DynamicPromptRenderer 
      promptContent={samplePrompt}
      promptMeta={{
        name: "Code_Implementation_Generator",
        source: "qanalabs_code_gen.md",
        lines: "142 - 248",
        lastModified: "2 hours ago",
        version: "v1.3"
      }}
    />
  );
}
