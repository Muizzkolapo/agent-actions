/**
 * Swizzled: @theme/DocSidebar/Mobile
 * Renders the agent-actions ASCII file-tree inside Docusaurus's slide-in mobile
 * drawer, instead of Infima's default <menu> list.
 *
 * Drop in at:  src/theme/DocSidebar/Mobile/index.tsx
 *
 * Same shared <AgacTree> the desktop rail uses — so the look, routing, active
 * state, and collapse behaviour all match. `onNavigate` closes the drawer when
 * the user taps a doc link (categories that toggle keep the drawer open).
 *
 * Loosely typed on purpose so `docusaurus build` (Babel) never trips.
 */
import React from 'react';
import {
  NavbarSecondaryMenuFiller,
  useNavbarMobileSidebar,
} from '@docusaurus/theme-common/internal';
import AgacTree from '../_AgacTree';

function DocSidebarMobileSecondaryMenu({sidebar}: any): JSX.Element {
  const mobileSidebar = useNavbarMobileSidebar();
  return (
    <AgacTree
      sidebar={sidebar}
      className="agac-tree--mobile"
      onNavigate={() => mobileSidebar.toggle()}
    />
  );
}

function DocSidebarMobile(props: any): JSX.Element {
  return (
    <NavbarSecondaryMenuFiller
      component={DocSidebarMobileSecondaryMenu}
      props={props}
    />
  );
}

export default React.memo(DocSidebarMobile);
