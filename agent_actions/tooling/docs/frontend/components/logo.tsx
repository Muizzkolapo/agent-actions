/** Three bottom-aligned bars in a graphite tile. Matches public/favicon.svg. */
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <rect
        x="0.5"
        y="0.5"
        width="31"
        height="31"
        rx="5.5"
        fill="hsl(var(--accent-a12))"
        stroke="hsl(var(--accent-a30))"
      />
      <rect x="7.5" y="13" width="4" height="10" rx="2" fill="hsl(var(--accent))" />
      <rect x="14" y="7" width="4" height="16" rx="2" fill="hsl(var(--accent-soft-a50))" />
      <rect x="20.5" y="10" width="4" height="13" rx="2" fill="hsl(var(--accent-soft-a70))" />
    </svg>
  )
}
