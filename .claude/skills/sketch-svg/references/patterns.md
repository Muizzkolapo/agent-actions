# Sketch SVG — Reusable Patterns

Copy-paste these SVG snippets when building sketch diagrams. All patterns work together — they share the same filter IDs and style conventions.

## 1. The Wobble Filter

This is the foundation of the hand-drawn look. Place it inside `<defs>`. Apply via `filter="url(#wobble)"` on shapes and arrows (never on text).

```svg
<filter id="wobble" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="1" result="noise"/>
  <feDisplacementMap in="SourceGraphic" in2="noise" scale="3" xChannelSelector="R" yChannelSelector="G"/>
</filter>
```

**Sloppiness presets:**

Architect (neat):
```svg
<filter id="wobble" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="1" result="noise"/>
  <feDisplacementMap in="SourceGraphic" in2="noise" scale="1" xChannelSelector="R" yChannelSelector="G"/>
</filter>
```

Artist (default):
```svg
<filter id="wobble" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="1" result="noise"/>
  <feDisplacementMap in="SourceGraphic" in2="noise" scale="3" xChannelSelector="R" yChannelSelector="G"/>
</filter>
```

Cartoonist (very sloppy):
```svg
<filter id="wobble" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="1" result="noise"/>
  <feDisplacementMap in="SourceGraphic" in2="noise" scale="6" xChannelSelector="R" yChannelSelector="G"/>
</filter>
```

**Other tuning:**
- `baseFrequency="0.02"` — larger, slower waves
- `seed` — change this number for different random patterns

## 2. Hatching Patterns

Each color needs its own pattern. The pattern creates diagonal lines over a solid pastel fill.

### Blue hatching
```svg
<pattern id="hatch-blue" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#a5d8ff"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#74b3e0" stroke-width="1.5" opacity="0.6"/>
</pattern>
```

### Green hatching
```svg
<pattern id="hatch-green" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#b2f2bb"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#7dd694" stroke-width="1.5" opacity="0.6"/>
</pattern>
```

### Orange/Yellow hatching
```svg
<pattern id="hatch-orange" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#ffd8a8"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#e8b080" stroke-width="1.5" opacity="0.6"/>
</pattern>
```

### Yellow hatching
```svg
<pattern id="hatch-yellow" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#ffec99"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#e0cc70" stroke-width="1.5" opacity="0.6"/>
</pattern>
```

### Purple hatching
```svg
<pattern id="hatch-purple" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#d0bfff"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#b098e0" stroke-width="1.5" opacity="0.6"/>
</pattern>
```

### Pink hatching
```svg
<pattern id="hatch-pink" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#fcc2d7"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#e09ab0" stroke-width="1.5" opacity="0.6"/>
</pattern>
```

### Light gray hatching (for secondary/neutral elements)
```svg
<pattern id="hatch-gray" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#f0f0f0"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#d0d0d0" stroke-width="1.5" opacity="0.5"/>
</pattern>
```

### Solid fills (no hatching — just use the pastel color directly)

When the user requests solid fills, skip patterns entirely and use `fill="<pastel-color>"` on the path:
```svg
<!-- Solid blue fill -->
<path d="..." fill="#a5d8ff" stroke="#1971c2" stroke-width="2" filter="url(#wobble)"/>

<!-- Solid green fill -->
<path d="..." fill="#b2f2bb" stroke="#2b8a3e" stroke-width="2" filter="url(#wobble)"/>

<!-- Solid yellow fill -->
<path d="..." fill="#ffec99" stroke="#e67700" stroke-width="2" filter="url(#wobble)"/>
```
The wobble filter still applies — solid fills look sketchy because of the wobbly borders, just without the line texture inside.

**Cross-hatching variant** — for denser fill, add a second line at 90 degrees:
```svg
<pattern id="hatch-blue-cross" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
  <rect width="8" height="8" fill="#a5d8ff"/>
  <line x1="0" y1="0" x2="0" y2="8" stroke="#74b3e0" stroke-width="1.2" opacity="0.5"/>
  <line x1="0" y1="0" x2="8" y2="0" stroke="#74b3e0" stroke-width="1.2" opacity="0.3"/>
</pattern>
```

## 3. Wobbly Rectangle Path

This replaces `<rect>`. Trace a rectangle as a path with bezier curves for natural waviness. The control points are offset ±3-5px from the straight line.

### Template (replace X, Y, W, H with your coordinates)

For a box at position (X, Y) with width W and height H:

```svg
<path d="
  M {X+12},Y
  Q {X+W*0.3},{Y-3} {X+W*0.5},{Y+2}
  Q {X+W*0.7},{Y-2} {X+W-12},Y
  Q {X+W+2},{Y+H*0.3} {X+W},{Y+H*0.5}
  Q {X+W+2},{Y+H*0.7} {X+W-12},{Y+H}
  Q {X+W*0.7},{Y+H+3} {X+W*0.5},{Y+H-2}
  Q {X+W*0.3},{Y+H+2} {X+12},{Y+H}
  Q {X-2},{Y+H*0.7} X,{Y+H*0.5}
  Q {X-2},{Y+H*0.3} {X+12},Y
  Z"
  fill="url(#hatch-blue)"
  stroke="#1971c2"
  stroke-width="2"
  filter="url(#wobble)"
/>
```

### Concrete example: 240x80 box at (50, 100)

```svg
<path d="
  M 62,100
  Q 122,97 170,102
  Q 218,98 278,100
  Q 292,124 290,140
  Q 292,156 278,180
  Q 218,183 170,178
  Q 122,182 62,180
  Q 48,156 50,140
  Q 48,124 62,100
  Z"
  fill="url(#hatch-blue)"
  stroke="#1971c2"
  stroke-width="2"
  filter="url(#wobble)"
/>
```

## 4. Hand-Drawn Arrow

Arrows use bezier curves with the wobble filter. Always use thick strokes and round caps.

### Straight-ish arrow (with slight curve)
```svg
<defs>
  <marker id="arrowhead" markerWidth="12" markerHeight="10" refX="10" refY="5" orient="auto">
    <polygon points="0,0 12,5 0,10 2,5" fill="#1e1e1e"/>
  </marker>
</defs>

<path d="M 150,200 Q 200,190 250,200 Q 300,210 350,200"
  fill="none"
  stroke="#1e1e1e"
  stroke-width="2"
  stroke-linecap="round"
  marker-end="url(#arrowhead)"
  filter="url(#wobble)"
/>
```

### Curved arrow (arc between boxes)
```svg
<path d="M 200,150 C 250,80 350,80 400,150"
  fill="none"
  stroke="#1e1e1e"
  stroke-width="2"
  stroke-linecap="round"
  marker-end="url(#arrowhead)"
  filter="url(#wobble)"
/>
```

### Long sweeping arrow (for cycle diagrams)
```svg
<path d="M 500,200 C 550,250 550,350 400,380 C 250,410 200,350 200,300"
  fill="none"
  stroke="#1e1e1e"
  stroke-width="2.5"
  stroke-linecap="round"
  marker-end="url(#arrowhead)"
  filter="url(#wobble)"
/>
```

## 5. Text Style

```svg
<text x="170" y="145"
  text-anchor="middle"
  font-family="Segoe Print, Comic Sans MS, Bradley Hand, cursive"
  font-size="24"
  font-weight="bold"
  fill="#1971c2">
  Define
</text>

<!-- Sub-label (smaller, lighter) -->
<text x="170" y="170"
  text-anchor="middle"
  font-family="Segoe Print, Comic Sans MS, Bradley Hand, cursive"
  font-size="14"
  fill="#1e1e1e"
  opacity="0.7">
  YAML · prompts · schemas
</text>
```

**Do NOT apply `filter="url(#wobble)"` to text elements.** The handwriting font provides the sketch feel for text.

## 6. Small Icons

### Bar chart icon (3-4 rectangles of varying height)
```svg
<g transform="translate(160, 50)" filter="url(#wobble)">
  <rect x="0" y="30" width="12" height="20" rx="1" fill="#74b3e0" stroke="#1971c2" stroke-width="1"/>
  <rect x="16" y="22" width="12" height="28" rx="1" fill="#74b3e0" stroke="#1971c2" stroke-width="1"/>
  <rect x="32" y="14" width="12" height="36" rx="1" fill="#74b3e0" stroke="#1971c2" stroke-width="1"/>
  <rect x="48" y="6" width="12" height="44" rx="1" fill="#a5d8ff" stroke="#1971c2" stroke-width="1"/>
</g>
```

### Checkmark in circle
```svg
<g transform="translate(100, 120)" filter="url(#wobble)">
  <circle cx="15" cy="15" r="14" fill="none" stroke="#e67700" stroke-width="2"/>
  <polyline points="7,15 13,21 24,9" fill="none" stroke="#e67700" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
</g>
```

### Document / page icon
```svg
<g transform="translate(200, 80)" filter="url(#wobble)">
  <rect x="0" y="0" width="24" height="30" rx="2" fill="#b2f2bb" stroke="#2b8a3e" stroke-width="1.5"/>
  <line x1="5" y1="8" x2="19" y2="8" stroke="#2b8a3e" stroke-width="1" opacity="0.6"/>
  <line x1="5" y1="13" x2="16" y2="13" stroke="#2b8a3e" stroke-width="1" opacity="0.6"/>
  <line x1="5" y1="18" x2="13" y2="18" stroke="#2b8a3e" stroke-width="1" opacity="0.6"/>
</g>
```

### Grid / multi-item icon
```svg
<g transform="translate(250, 100)" filter="url(#wobble)">
  <rect x="0" y="0" width="10" height="10" rx="1" fill="#d0d0d0" stroke="#888" stroke-width="1"/>
  <rect x="14" y="0" width="10" height="10" rx="1" fill="#d0d0d0" stroke="#888" stroke-width="1"/>
  <rect x="0" y="14" width="10" height="10" rx="1" fill="#d0d0d0" stroke="#888" stroke-width="1"/>
  <rect x="14" y="14" width="10" height="10" rx="1" fill="#d0d0d0" stroke="#888" stroke-width="1"/>
</g>
```

## 7. Complete Minimal Example

A two-node flow diagram:

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="500" height="250" viewBox="0 0 500 250">
  <defs>
    <filter id="wobble" x="-5%" y="-5%" width="110%" height="110%">
      <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="2" result="noise"/>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="3" xChannelSelector="R" yChannelSelector="G"/>
    </filter>
    <pattern id="hatch-green" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="8" height="8" fill="#b2f2bb"/>
      <line x1="0" y1="0" x2="0" y2="8" stroke="#7dd694" stroke-width="1.5" opacity="0.6"/>
    </pattern>
    <pattern id="hatch-blue" x="0" y="0" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="8" height="8" fill="#a5d8ff"/>
      <line x1="0" y1="0" x2="0" y2="8" stroke="#74b3e0" stroke-width="1.5" opacity="0.6"/>
    </pattern>
    <marker id="arrowhead" markerWidth="12" markerHeight="10" refX="10" refY="5" orient="auto">
      <polygon points="0,0 12,5 0,10 2,5" fill="#1e1e1e"/>
    </marker>
  </defs>

  <rect width="500" height="250" fill="#ffffff"/>

  <!-- Box 1: green -->
  <path d="M 32,60 Q 82,57 130,62 Q 178,58 218,60 Q 222,90 220,105 Q 222,120 218,150 Q 178,153 130,148 Q 82,152 32,150 Q 28,120 30,105 Q 28,90 32,60 Z"
    fill="url(#hatch-green)" stroke="#2b8a3e" stroke-width="2" filter="url(#wobble)"/>
  <text x="125" y="98" text-anchor="middle" font-family="Segoe Print, Comic Sans MS, cursive" font-size="20" font-weight="bold" fill="#2b8a3e">extract</text>
  <text x="125" y="120" text-anchor="middle" font-family="Segoe Print, Comic Sans MS, cursive" font-size="13" fill="#2b8a3e" opacity="0.7">parse · clean</text>

  <!-- Arrow -->
  <path d="M 225,105 Q 275,95 320,105" fill="none" stroke="#1e1e1e" stroke-width="2" stroke-linecap="round" marker-end="url(#arrowhead)" filter="url(#wobble)"/>

  <!-- Box 2: blue -->
  <path d="M 332,60 Q 382,57 430,62 Q 468,58 468,60 Q 472,90 470,105 Q 472,120 468,150 Q 428,153 380,148 Q 342,152 332,150 Q 328,120 330,105 Q 328,90 332,60 Z"
    fill="url(#hatch-blue)" stroke="#1971c2" stroke-width="2" filter="url(#wobble)"/>
  <text x="400" y="98" text-anchor="middle" font-family="Segoe Print, Comic Sans MS, cursive" font-size="20" font-weight="bold" fill="#1971c2">transform</text>
  <text x="400" y="120" text-anchor="middle" font-family="Segoe Print, Comic Sans MS, cursive" font-size="13" fill="#1971c2" opacity="0.7">enrich · validate</text>
</svg>
```

## 8. GitHub Compatibility Notes

- GitHub sanitizes SVGs: no `<script>`, no `<foreignObject>`, no external URLs
- Embedded `<style>` is allowed but only inline styles are fully reliable
- `<filter>`, `<pattern>`, and `<marker>` elements work correctly
- Fonts degrade gracefully — `Segoe Print` on Windows, `Comic Sans MS` broadly, `cursive` everywhere
- Use `<picture>` with `prefers-color-scheme` media queries if you need light/dark variants
- SMIL `<animate>` works in browsers but is stripped by GitHub — static SVGs only for READMEs
