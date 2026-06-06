/**
 * Swizzled: @theme/DocSidebar/Mobile
 * Renders the agent-actions ASCII file-tree in the mobile drawer.
 * Matches the default Docusaurus pattern exactly, just swaps DocSidebarItems for AgacTree.
 */
import React from 'react';
import {
  NavbarSecondaryMenuFiller,
  type NavbarSecondaryMenuComponent,
} from '@docusaurus/theme-common';
import {useNavbarMobileSidebar} from '@docusaurus/theme-common/internal';
import AgacTree from '../_AgacTree';
import type {Props} from '@theme/DocSidebar/Mobile';

const DocSidebarMobileSecondaryMenu: NavbarSecondaryMenuComponent<Props> = ({
  sidebar,
  path,
}) => {
  const mobileSidebar = useNavbarMobileSidebar();
  return (
    <AgacTree
      sidebar={sidebar}
      path={path}
      className="agac-tree--mobile"
      onNavigate={() => mobileSidebar.toggle()}
    />
  );
};

function DocSidebarMobile(props: Props) {
  return (
    <NavbarSecondaryMenuFiller
      component={DocSidebarMobileSecondaryMenu}
      props={props}
    />
  );
}

export default React.memo(DocSidebarMobile);
