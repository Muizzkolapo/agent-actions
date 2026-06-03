/**
 * Swizzled: @theme/DocSidebar/Desktop/Content
 * Renders the agent-actions ASCII file-tree instead of Infima's <menu>.
 *
 * Drop in at:  src/theme/DocSidebar/Desktop/Content/index.tsx
 *
 * Thin wrapper around the shared <AgacTree>, which consumes Docusaurus's own
 * parsed `sidebar` prop so routing/active-state/nesting stay framework-wired.
 * The same tree renders in the mobile drawer (see DocSidebar/Mobile).
 */
import React from 'react';
import AgacTree from '../../_AgacTree';

export default function DocSidebarDesktopContent({sidebar, className}: any): JSX.Element {
  return <AgacTree sidebar={sidebar} className={className} />;
}
