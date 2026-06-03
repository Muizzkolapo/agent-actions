/**
 * Swizzled: @theme/CodeBlock/Layout
 *
 * Replaces the default code block layout with a structured header bar
 * matching the agac "code instrument" reference design:
 *
 *   [ traffic-lights | filename / label  ...  LANG chip  copy btn ]
 *   [ ─────────────────────────────────────────────────────────── ]
 *   [ code content                                                ]
 *
 * All existing Docusaurus functionality (copy, word-wrap, line highlighting,
 * title, Prism highlighting) is preserved — we only restructure the chrome.
 */
import React, {
  useCallback,
  useState,
  useRef,
  useEffect,
  type ReactNode,
} from 'react';
import clsx from 'clsx';
import {translate} from '@docusaurus/Translate';
import {useCodeBlockContext} from '@docusaurus/theme-common/internal';
import Container from '@theme/CodeBlock/Container';
import Content from '@theme/CodeBlock/Content';
import type {Props} from '@theme/CodeBlock/Layout';

/* ── language display names ── */
const LANG_LABELS: Record<string, string> = {
  bash: 'bash',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yaml: 'yaml',
  yml: 'yaml',
  json: 'json',
  python: 'python',
  py: 'python',
  toml: 'toml',
  ts: 'typescript',
  tsx: 'typescript',
  typescript: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  javascript: 'javascript',
  diff: 'diff',
  css: 'css',
  scss: 'css',
  html: 'html',
  xml: 'xml',
  sql: 'sql',
  rust: 'rust',
  go: 'go',
  java: 'java',
  c: 'c',
  cpp: 'c++',
  ruby: 'ruby',
  rb: 'ruby',
  php: 'php',
  swift: 'swift',
  kotlin: 'kotlin',
  markdown: 'markdown',
  md: 'markdown',
  mdx: 'mdx',
  graphql: 'graphql',
  docker: 'docker',
  dockerfile: 'docker',
  makefile: 'makefile',
  lua: 'lua',
  r: 'r',
  text: 'text',
  txt: 'text',
  plaintext: 'text',
};

/* ── chip abbreviations (short uppercase badge) ── */
const LANG_CHIPS: Record<string, string> = {
  bash: 'BASH',
  yaml: 'YAML',
  json: 'JSON',
  python: 'PY',
  toml: 'TOML',
  typescript: 'TS',
  javascript: 'JS',
  diff: 'DIFF',
  css: 'CSS',
  html: 'HTML',
  xml: 'XML',
  sql: 'SQL',
  rust: 'RS',
  go: 'GO',
  java: 'JAVA',
  'c++': 'C++',
  c: 'C',
  ruby: 'RB',
  php: 'PHP',
  swift: 'SWIFT',
  kotlin: 'KT',
  markdown: 'MD',
  mdx: 'MDX',
  graphql: 'GQL',
  docker: 'DOCKER',
  makefile: 'MAKE',
  lua: 'LUA',
  r: 'R',
  text: 'TXT',
};

/* ── inline copy button (moved into the header) ── */
async function copyToClipboard(text: string) {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text);
  }
  const {default: copy} = await import('copy-text-to-clipboard');
  return copy(text);
}

function HeaderCopyButton(): ReactNode {
  const {
    metadata: {code},
  } = useCodeBlockContext();
  const [isCopied, setIsCopied] = useState(false);
  const copyTimeout = useRef<number | undefined>(undefined);

  const handleCopy = useCallback(() => {
    copyToClipboard(code).then(() => {
      setIsCopied(true);
      copyTimeout.current = window.setTimeout(() => {
        setIsCopied(false);
      }, 1000);
    });
  }, [code]);

  useEffect(() => () => window.clearTimeout(copyTimeout.current), []);

  const label = isCopied
    ? translate({id: 'theme.CodeBlock.copied', message: 'Copied'})
    : translate({id: 'theme.CodeBlock.copy', message: 'Copy'});

  return (
    <button
      type="button"
      className={clsx('cb-head-btn', isCopied && 'cb-head-btn--copied')}
      onClick={handleCopy}
      aria-label={label}>
      {isCopied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
      <span className="cb-head-btn-label">{label}</span>
    </button>
  );
}

/* ── main layout ── */
export default function CodeBlockLayout({className}: Props): ReactNode {
  const {metadata} = useCodeBlockContext();
  const {language, title} = metadata;

  const langLabel = LANG_LABELS[language] || language || 'code';
  const chip = LANG_CHIPS[langLabel] || langLabel.toUpperCase().slice(0, 6);
  const displayName = title || langLabel;

  return (
    <Container
      as="div"
      className={clsx(className, metadata.className, 'cb-instrument')}>
      {/* ── structured header bar ── */}
      <div className="cb-head">
        <div className="cb-lights" aria-hidden="true">
          <span className="cb-light cb-light--red" />
          <span className="cb-light cb-light--amber" />
          <span className="cb-light cb-light--green" />
        </div>
        <span className="cb-head-name">{displayName}</span>
        <div className="cb-head-right">
          <span className="cb-head-chip">{chip}</span>
          <HeaderCopyButton />
        </div>
      </div>
      {/* ── code content (Prism highlighting + line numbers) ── */}
      <div className="cb-body-wrap">
        <Content />
      </div>
    </Container>
  );
}
