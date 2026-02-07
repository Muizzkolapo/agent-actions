import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: string;
  icon: string;
  href: string;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Quick Start',
    description: 'Go from zero to a running workflow in under 5 minutes.',
    icon: 'QS',
    href: '/docs/',
  },
  {
    title: 'Design Patterns',
    description:
      'Fan-out, fan-in, quality gates, retries, and conditional branching.',
    icon: 'WF',
    href: '/docs/guides/design-patterns',
  },
  {
    title: 'CLI Reference',
    description:
      'Run, inspect, batch, validate — every agac command documented.',
    icon: 'CLI',
    href: '/docs/reference/cli',
  },
  {
    title: 'Custom Tools',
    description:
      'Extend workflows with Python UDFs for deterministic logic.',
    icon: 'UDF',
    href: '/docs/guides/custom-tools',
  },
];

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className={styles.grid}>
        {FeatureList.map((feature) => (
          <Link key={feature.title} className={styles.card} to={feature.href}>
            <div className={styles.icon}>{feature.icon}</div>
            <div className={styles.title}>{feature.title}</div>
            <div className={styles.desc}>{feature.description}</div>
          </Link>
        ))}
      </div>
    </section>
  );
}
