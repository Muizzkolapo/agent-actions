import React, { useState, useMemo } from 'react';

// ============================================
// DYNAMIC PROMPT RENDERER - LIGHT THEME
// ============================================

const DynamicPromptRenderer = ({ 
  promptContent, 
  promptMeta = {} 
}) => {
  const [viewMode, setViewMode] = useState('rendered');
  const [copied, setCopied] = useState(false);

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
  // PARSER
  // ============================================
  const parsePrompt = (content) => {
    if (!content) return [];
    
    const lines = content.split('\n');
    const tokens = [];
    let i = 0;
    
    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();
      
      if (!trimmed) {
        if (tokens.length > 0 && tokens[tokens.length - 1].type !== 'spacer') {
          tokens.push({ type: 'spacer' });
        }
        i++;
        continue;
      }
      
      if (/^# /.test(trimmed)) {
        tokens.push({ type: 'h1', content: trimmed.slice(2) });
        i++;
        continue;
      }
      
      if (/^## /.test(trimmed)) {
        tokens.push({ type: 'h2', content: trimmed.slice(3) });
        i++;
        continue;
      }
      
      if (/^### /.test(trimmed)) {
        tokens.push({ type: 'h3', content: trimmed.slice(4) });
        i++;
        continue;
      }
      
      if (/^```/.test(trimmed)) {
        const lang = trimmed.slice(3).trim();
        const codeLines = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i]);
          i++;
        }
        tokens.push({ type: 'codeblock', lang, content: codeLines.join('\n') });
        i++;
        continue;
      }
      
      if (/^[-*] /.test(trimmed)) {
        const listItems = [];
        while (i < lines.length && /^[-*] /.test(lines[i].trim())) {
          listItems.push(lines[i].trim().slice(2));
          i++;
        }
        tokens.push({ type: 'ul', items: listItems });
        continue;
      }
      
      if (/^\d+\. /.test(trimmed)) {
        const listItems = [];
        while (i < lines.length && /^\d+\. /.test(lines[i].trim())) {
          listItems.push(lines[i].trim().replace(/^\d+\. /, ''));
          i++;
        }
        tokens.push({ type: 'ol', items: listItems });
        continue;
      }
      
      if (/^> /.test(trimmed)) {
        const quoteLines = [];
        while (i < lines.length && /^> /.test(lines[i].trim())) {
          quoteLines.push(lines[i].trim().slice(2));
          i++;
        }
        tokens.push({ type: 'blockquote', content: quoteLines.join('\n') });
        continue;
      }
      
      if (/^(---|\*\*\*)$/.test(trimmed)) {
        tokens.push({ type: 'hr' });
        i++;
        continue;
      }
      
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

  const parseInline = (text) => {
    if (!text) return null;
    
    const elements = [];
    let remaining = text;
    let key = 0;
    
    while (remaining.length > 0) {
      let match = remaining.match(/^(.*?)\{\{\s*([^}]+)\s*\}\}/);
      if (match) {
        if (match[1]) elements.push(<span key={key++}>{parseInlineFormatting(match[1])}</span>);
        elements.push(
          <span key={key++} className="variable-tag">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
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
      
      elements.push(<span key={key++}>{parseInlineFormatting(remaining)}</span>);
      break;
    }
    
    return elements;
  };

  const parseInlineFormatting = (text) => {
    if (!text) return null;
    
    const parts = [];
    let remaining = text;
    let key = 0;
    
    while (remaining.length > 0) {
      let match = remaining.match(/^(.*?)(\*\*\*|___)(.+?)\2/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<strong key={key++}><em>{match[3]}</em></strong>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      match = remaining.match(/^(.*?)(\*\*|__)(.+?)\2/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<strong key={key++} className="text-bold">{match[3]}</strong>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      match = remaining.match(/^(.*?)(\*|_)(.+?)\2/);
      if (match && !match[1].endsWith('\\')) {
        if (match[1]) parts.push(match[1]);
        parts.push(<em key={key++}>{match[3]}</em>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
      match = remaining.match(/^(.*?)`([^`]+)`/);
      if (match) {
        if (match[1]) parts.push(match[1]);
        parts.push(<code key={key++} className="inline-code">{match[2]}</code>);
        remaining = remaining.slice(match[0].length);
        continue;
      }
      
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
      
      parts.push(remaining);
      break;
    }
    
    return parts;
  };

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

  const extractVariables = (content) => {
    const vars = new Set();
    const matches1 = content.matchAll(/\{\{\s*([^}]+)\s*\}\}/g);
    for (const m of matches1) vars.add(m[1].trim());
    const matches2 = content.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g);
    for (const m of matches2) vars.add(m[1]);
    return Array.from(vars).map(v => ({ name: v, type: inferType(v) }));
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

  const tokens = useMemo(() => parsePrompt(promptContent), [promptContent]);
  const variables = useMemo(() => extractVariables(promptContent || ''), [promptContent]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(promptContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
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
    
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10"/>
      </svg>
    );
  };

  const getListIcon = (item, listPattern) => {
    if (/^(✅|✓)/.test(item) || listPattern === 'can-do') {
      return (
        <svg className="list-icon can" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <polyline points="20,6 9,17 4,12"/>
        </svg>
      );
    }
    if (/^(❌|✗)/.test(item) || listPattern === 'cannot-do') {
      return (
        <svg className="list-icon cannot" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      );
    }
    return <span className="list-bullet">•</span>;
  };

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
        const listPattern = prevToken?.content ? detectPattern(prevToken.content) : null;
        
        return (
          <ul key={index} className={`token-ul ${listPattern || ''}`}>
            {token.items.map((item, i) => (
              <li key={i}>
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

  return (
    <div className="prompt-renderer">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap');
        
        .prompt-renderer {
          min-height: 100vh;
          background: #fafaf9;
          color: #1c1917;
          font-family: 'DM Sans', -apple-system, sans-serif;
          font-size: 14px;
          line-height: 1.6;
        }
        
        .prompt-renderer * { box-sizing: border-box; }
        
        .prompt-renderer ::-webkit-scrollbar { width: 6px; height: 6px; }
        .prompt-renderer ::-webkit-scrollbar-track { background: #f5f5f4; }
        .prompt-renderer ::-webkit-scrollbar-thumb { background: #d6d3d1; border-radius: 3px; }
        
        /* Layout */
        .pr-layout { display: flex; min-height: 100vh; }
        
        .pr-sidebar {
          width: 240px;
          background: #ffffff;
          border-right: 1px solid #e7e5e4;
          padding: 24px 16px;
          position: sticky;
          top: 0;
          height: 100vh;
          overflow-y: auto;
          flex-shrink: 0;
        }
        
        .pr-logo {
          padding: 4px 12px;
          margin-bottom: 28px;
        }
        
        .pr-logo-text {
          font-family: 'Newsreader', serif;
          font-size: 20px;
          font-weight: 600;
          color: #0c0a09;
          letter-spacing: -0.02em;
        }
        
        .pr-logo-sub {
          font-size: 12px;
          color: #a8a29e;
          margin-top: 2px;
        }
        
        .nav-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 12px;
          color: #78716c;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
          margin-bottom: 4px;
        }
        
        .nav-item:hover { background: #f5f5f4; color: #44403c; }
        .nav-item.active { 
          background: linear-gradient(135deg, #fef3c7, #fef9c3);
          color: #92400e;
        }
        
        .pr-main {
          flex: 1;
          padding: 32px 48px;
          max-width: 920px;
        }
        
        /* Breadcrumb */
        .pr-breadcrumb {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          color: #a8a29e;
          margin-bottom: 20px;
        }
        
        .pr-breadcrumb span { cursor: pointer; }
        .pr-breadcrumb span:hover { color: #78716c; }
        .pr-breadcrumb .current { color: #57534e; }
        
        /* Header */
        .pr-header { margin-bottom: 32px; }
        
        .pr-header-top {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          margin-bottom: 20px;
        }
        
        .pr-title {
          font-family: 'Newsreader', serif;
          font-size: 32px;
          font-weight: 600;
          color: #0c0a09;
          margin: 0;
          letter-spacing: -0.02em;
        }
        
        .pr-badges {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-top: 12px;
        }
        
        .pr-type-badge {
          padding: 4px 12px;
          background: linear-gradient(135deg, #f59e0b, #d97706);
          border-radius: 6px;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #fff;
          box-shadow: 0 1px 2px rgba(217, 119, 6, 0.2);
        }
        
        .pr-meta-pill {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: #fff;
          border: 1px solid #e7e5e4;
          border-radius: 20px;
          font-size: 12px;
          color: #78716c;
        }
        
        .pr-actions { display: flex; gap: 10px; }
        
        .pr-btn {
          padding: 10px 16px;
          border-radius: 8px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 8px;
          transition: all 0.15s;
          border: none;
        }
        
        .pr-btn-secondary {
          background: #fff;
          border: 1px solid #e7e5e4;
          color: #57534e;
          box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }
        
        .pr-btn-secondary:hover { 
          background: #f5f5f4; 
          border-color: #d6d3d1;
        }
        
        .pr-btn-primary {
          background: linear-gradient(135deg, #f59e0b, #d97706);
          color: #fff;
          box-shadow: 0 2px 4px rgba(217, 119, 6, 0.25);
        }
        
        .pr-btn-primary:hover { 
          box-shadow: 0 4px 8px rgba(217, 119, 6, 0.3);
          transform: translateY(-1px);
        }
        
        /* Meta bar */
        .pr-meta-bar {
          display: flex;
          align-items: center;
          gap: 24px;
          padding: 14px 20px;
          background: #fff;
          border: 1px solid #e7e5e4;
          border-radius: 12px;
          font-size: 13px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        
        .pr-meta-item {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #a8a29e;
        }
        
        .pr-meta-item .value { color: #57534e; }
        .pr-meta-item .highlight { 
          color: #b45309; 
          font-family: 'JetBrains Mono', monospace; 
          font-size: 12px;
          background: #fef3c7;
          padding: 2px 8px;
          border-radius: 4px;
        }
        
        .pr-meta-divider { width: 1px; height: 20px; background: #e7e5e4; }
        
        /* Tabs */
        .pr-tabs-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid #e7e5e4;
        }
        
        .pr-tabs-label {
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          color: #a8a29e;
        }
        
        .pr-tabs {
          display: flex;
          gap: 4px;
          background: #f5f5f4;
          padding: 4px;
          border-radius: 10px;
        }
        
        .pr-tab {
          padding: 8px 14px;
          font-size: 13px;
          font-weight: 500;
          border: none;
          background: transparent;
          color: #78716c;
          cursor: pointer;
          border-radius: 6px;
          transition: all 0.15s;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        
        .pr-tab:hover { color: #44403c; }
        .pr-tab.active { 
          background: #fff; 
          color: #0c0a09;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }
        
        /* Content styles */
        .pr-content { padding-left: 4px; }
        
        .token-h1 {
          font-family: 'Newsreader', serif;
          font-size: 26px;
          font-weight: 600;
          color: #0c0a09;
          margin: 0 0 20px 0;
          letter-spacing: -0.02em;
        }
        
        .section-block { margin: 28px 0 16px 0; }
        
        .section-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding-bottom: 10px;
          border-bottom: 2px solid #f5f5f4;
        }
        
        .section-icon {
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #f5f5f4;
          border-radius: 8px;
          color: #78716c;
        }
        
        .section-icon.critical, .section-icon.constraint { 
          color: #dc2626; 
          background: #fef2f2;
        }
        .section-icon.can-do { 
          color: #16a34a; 
          background: #f0fdf4;
        }
        .section-icon.cannot-do { 
          color: #dc2626; 
          background: #fef2f2;
        }
        .section-icon.example { 
          color: #d97706; 
          background: #fffbeb;
        }
        .section-icon.output { 
          color: #16a34a; 
          background: #f0fdf4;
        }
        .section-icon.input { 
          color: #0284c7; 
          background: #f0f9ff;
        }
        
        .section-header h2 {
          font-family: 'Newsreader', serif;
          font-size: 18px;
          font-weight: 600;
          color: #1c1917;
          margin: 0;
        }
        
        .token-h3 {
          font-size: 15px;
          font-weight: 600;
          color: #292524;
          margin: 24px 0 10px 0;
        }
        
        .token-h3.can-do { color: #16a34a; }
        .token-h3.cannot-do { color: #dc2626; }
        
        .token-paragraph {
          color: #57534e;
          margin: 0 0 14px 0;
          line-height: 1.75;
        }
        
        .text-bold { color: #1c1917; font-weight: 600; }
        
        /* Variables */
        .variable-tag {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 3px 10px;
          background: linear-gradient(135deg, #fef3c7, #fde68a);
          border: 1px solid #fbbf24;
          border-radius: 6px;
          font-family: 'JetBrains Mono', monospace;
          font-size: 12px;
          font-weight: 500;
          color: #92400e;
          vertical-align: middle;
        }
        
        .variable-tag-alt {
          display: inline;
          padding: 2px 8px;
          background: #fef3c7;
          border: 1px solid #fcd34d;
          border-radius: 4px;
          font-family: 'JetBrains Mono', monospace;
          font-size: 12px;
          color: #b45309;
        }
        
        .inline-code {
          padding: 3px 8px;
          background: #f5f5f4;
          border: 1px solid #e7e5e4;
          border-radius: 5px;
          font-family: 'JetBrains Mono', monospace;
          font-size: 12px;
          color: #c2410c;
        }
        
        /* Code blocks */
        .codeblock-wrapper {
          margin: 16px 0;
          border-radius: 12px;
          overflow: hidden;
          border: 1px solid #e7e5e4;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        
        .codeblock-lang {
          padding: 8px 16px;
          background: #fafaf9;
          font-family: 'JetBrains Mono', monospace;
          font-size: 11px;
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #a8a29e;
          border-bottom: 1px solid #e7e5e4;
        }
        
        .codeblock {
          margin: 0;
          padding: 16px 20px;
          background: #fff;
          font-family: 'JetBrains Mono', monospace;
          font-size: 13px;
          line-height: 1.7;
          color: #44403c;
          overflow-x: auto;
        }
        
        .codeblock code { background: none; padding: 0; border: none; color: inherit; }
        
        /* Lists */
        .token-ul, .token-ol {
          margin: 10px 0;
          padding: 0;
          list-style: none;
        }
        
        .token-ul li, .token-ol li {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 8px 0;
          color: #57534e;
        }
        
        .list-bullet {
          color: #d6d3d1;
          font-size: 20px;
          line-height: 1;
          margin-top: 0;
        }
        
        .list-icon { flex-shrink: 0; margin-top: 3px; }
        .list-icon.can { color: #16a34a; }
        .list-icon.cannot { color: #dc2626; }
        
        .check-icon { color: #16a34a; font-weight: bold; }
        .x-icon { color: #dc2626; font-weight: bold; }
        
        .ol-number {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          background: #f5f5f4;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 600;
          color: #78716c;
          flex-shrink: 0;
        }
        
        /* Blockquote */
        .token-blockquote {
          margin: 16px 0;
          padding: 16px 20px;
          background: #fff;
          border-left: 4px solid #d6d3d1;
          border-radius: 0 10px 10px 0;
          color: #57534e;
          font-style: italic;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        
        .token-hr {
          border: none;
          height: 1px;
          background: #e7e5e4;
          margin: 24px 0;
        }
        
        /* Special boxes */
        .critical-box {
          margin: 16px 0;
          padding: 16px 20px;
          background: linear-gradient(135deg, #fef2f2, #fff);
          border: 1px solid #fecaca;
          border-left: 4px solid #dc2626;
          border-radius: 0 12px 12px 0;
        }
        
        .critical-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 10px;
          color: #dc2626;
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        
        .critical-box p { margin: 0; color: #7f1d1d; }
        
        .info-box {
          margin: 16px 0;
          padding: 16px 20px;
          background: linear-gradient(135deg, #f0f9ff, #fff);
          border: 1px solid #bae6fd;
          border-left: 4px solid #0284c7;
          border-radius: 0 12px 12px 0;
        }
        
        .info-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 10px;
          color: #0284c7;
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        
        .info-box p { margin: 0; color: #0c4a6e; }
        
        /* Variables view */
        .pr-variables-intro {
          color: #78716c;
          margin-bottom: 20px;
        }
        
        .pr-variables-table {
          background: #fff;
          border: 1px solid #e7e5e4;
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        
        .pr-variables-header {
          display: grid;
          grid-template-columns: 1fr 100px;
          padding: 12px 20px;
          background: #fafaf9;
          border-bottom: 1px solid #e7e5e4;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          color: #a8a29e;
        }
        
        .pr-variable-row {
          display: grid;
          grid-template-columns: 1fr 100px;
          padding: 14px 20px;
          border-bottom: 1px solid #f5f5f4;
          align-items: center;
        }
        
        .pr-variable-row:last-child { border-bottom: none; }
        
        .pr-variable-name {
          font-family: 'JetBrains Mono', monospace;
          font-size: 13px;
          color: #b45309;
        }
        
        .pr-variable-type {
          padding: 4px 10px;
          background: #f5f5f4;
          border-radius: 6px;
          font-size: 11px;
          color: #78716c;
          text-align: center;
          font-weight: 500;
        }
        
        /* Raw view */
        .pr-raw {
          background: #fff;
          border: 1px solid #e7e5e4;
          border-radius: 12px;
          padding: 20px;
          font-family: 'JetBrains Mono', monospace;
          font-size: 13px;
          line-height: 1.7;
          color: #57534e;
          white-space: pre-wrap;
          word-break: break-word;
          max-height: 70vh;
          overflow: auto;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        
        /* Empty state */
        .pr-empty {
          text-align: center;
          padding: 60px 20px;
          color: #a8a29e;
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
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9,22 9,12 15,12 15,22"/>
            </svg>
            Overview
          </div>
          
          <div className="nav-item active">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
            Prompts
          </div>
          
          <div className="nav-item">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <line x1="3" y1="9" x2="21" y2="9"/>
              <line x1="9" y1="21" x2="9" y2="9"/>
            </svg>
            Datasets
          </div>
          
          <div className="nav-item">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
            </svg>
            Runs
          </div>
          
          <div className="nav-item">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                  Edit
                </button>
                <button className="pr-btn pr-btn-primary">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
// DEMO
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
