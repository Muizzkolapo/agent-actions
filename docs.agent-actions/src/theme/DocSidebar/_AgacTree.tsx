/**
 * Shared ASCII file-tree renderer for the agac theme.
 *
 * Consumed by BOTH swizzles:
 *   - DocSidebar/Desktop/Content   (sticky left rail)
 *   - DocSidebar/Mobile            (slide-in drawer secondary menu)
 *
 * It takes Docusaurus's own parsed `sidebar` tree, so routing, active-state,
 * and nesting stay wired to the framework — we only replace the *rendering*.
 *
 * Loosely typed on purpose so `docusaurus build` (Babel) never trips; a couple
 * of `any`s are expected if you run `npm run typecheck`.
 */
import React, {useState} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {useLocation} from '@docusaurus/router';

const norm = (p?: string) => (p || '').replace(/\/+$/, '') || '/';

function samePath(a?: string, b?: string) {
  return norm(a) === norm(b);
}

// does this category contain the active route anywhere in its subtree?
function containsActive(item: any, path: string): boolean {
  if (item.type === 'category') {
    if (item.href && samePath(item.href, path)) return true;
    return (item.items || []).some((c: any) => containsActive(c, path));
  }
  if (item.type === 'link') return samePath(item.href, path);
  return false;
}

type Row =
  | {kind: 'category'; item: any; glyph: string; key: string; collapsible: boolean; isOpen: boolean; active: boolean}
  | {kind: 'link'; item: any; glyph: string; active: boolean}
  | {kind: 'html'; item: any; glyph: string};

function buildRows(
  items: any[],
  prefix: string,
  open: Record<string, boolean>,
  path: string,
  ancestorKey: string,
): Row[] {
  const rows: Row[] = [];
  items.forEach((item, i) => {
    const last = i === items.length - 1;
    const glyph = prefix + (last ? '└─ ' : '├─ ');
    const childPrefix = prefix + (last ? '   ' : '│  ');

    if (item.type === 'category') {
      const key = ancestorKey + '/' + item.label;
      const collapsible = item.collapsible !== false;
      const active = !!(item.href && samePath(item.href, path));
      const defaultOpen = item.collapsed === false || containsActive(item, path);
      const isOpen = !collapsible ? true : key in open ? open[key] : defaultOpen;
      rows.push({kind: 'category', item, glyph, key, collapsible, isOpen, active});
      if (isOpen) {
        rows.push(...buildRows(item.items || [], childPrefix, open, path, key));
      }
    } else if (item.type === 'link') {
      rows.push({kind: 'link', item, glyph, active: samePath(item.href, path)});
    } else if (item.type === 'html') {
      rows.push({kind: 'html', item, glyph});
    }
  });
  return rows;
}

/**
 * @param sidebar    Docusaurus parsed sidebar tree
 * @param className  extra classes for the <nav>
 * @param onNavigate optional callback fired when a doc link is clicked
 *                   (the mobile drawer uses it to close itself)
 */
export default function AgacTree({sidebar, className, onNavigate}: any): JSX.Element {
  const location = useLocation();
  const path = norm(location.pathname);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const toggle = (key: string, fallback: boolean) =>
    setOpen((o) => ({...o, [key]: !(key in o ? o[key] : fallback)}));

  const rows = buildRows(sidebar || [], '', open, path, '');
  const {siteConfig} = useDocusaurusContext();
  const version = (siteConfig.customFields?.agentActionsVersion as string) || '0.0.0';

  return (
    <nav className={'agac-tree ' + (className || '')} aria-label="Docs sidebar">
      <div className="agac-tree-root">
        <span>agent-actions</span>
        <span style={{color: 'var(--ifm-color-emphasis-300)'}}>·</span>
        <span className="dot">v{version}</span>
      </div>

      {rows.map((row, idx) => {
        if (row.kind === 'category') {
          const {item, glyph, key, collapsible, isOpen, active} = row;
          const caret = collapsible ? (
            <span className="agac-tree-caret" aria-hidden="true">›</span>
          ) : null;
          const inner = (
            <>
              <span className="agac-tree-glyph">{glyph}</span>
              <span className="agac-tree-label">{item.label}</span>
              {caret}
            </>
          );
          const cls =
            'agac-tree-node is-dir' + (isOpen ? ' open' : '') + (active ? ' active' : '');

          // category with a doc link → navigate AND open
          if (item.href) {
            return (
              <Link
                key={idx}
                to={item.href}
                className={cls}
                onClick={() => {
                  if (collapsible && !isOpen) toggle(key, true);
                  if (onNavigate) onNavigate();
                }}>
                {inner}
              </Link>
            );
          }
          // pure category → toggle only
          return (
            <div
              key={idx}
              className={cls}
              role="button"
              tabIndex={0}
              onClick={() => collapsible && toggle(key, isOpen)}
              onKeyDown={(e) => {
                if (collapsible && (e.key === 'Enter' || e.key === ' ')) {
                  e.preventDefault();
                  toggle(key, isOpen);
                }
              }}>
              {inner}
            </div>
          );
        }

        if (row.kind === 'link') {
          const {item, glyph, active} = row;
          return (
            <Link
              key={idx}
              to={item.href}
              className={'agac-tree-node' + (active ? ' active' : '')}
              onClick={() => onNavigate && onNavigate()}>
              <span className="agac-tree-glyph">{glyph}</span>
              <span className="agac-tree-label">{item.label}</span>
              <span className="agac-tree-arrow" aria-hidden="true">›</span>
            </Link>
          );
        }

        // html item
        return (
          <div
            key={idx}
            className="agac-tree-node"
            dangerouslySetInnerHTML={{__html: row.glyph + (row.item.value || '')}}
          />
        );
      })}
    </nav>
  );
}
