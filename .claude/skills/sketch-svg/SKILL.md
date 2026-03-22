---
name: sketch-svg
description: Generate hand-drawn / whiteboard-style SVG diagrams with a pencil-sketch aesthetic. Use this skill PROACTIVELY whenever the user asks for a diagram, flowchart, architecture visual, cycle diagram, workflow illustration, or any SVG image that should look hand-drawn, sketchy, or Excalidraw-like. Also trigger when the user mentions "whiteboard style", "pencil feel", "sketchy diagram", "hand-drawn", or wants visuals that look informal and organic rather than clean/corporate. Even if they just say "draw me a diagram of X" — use this skill to produce the sketch aesthetic by default.
---

# Sketch SVG — Hand-Drawn Diagram Generator

You generate SVG diagrams that look like someone drew them on a whiteboard with colored markers and pencils. The aesthetic is warm, informal, and human — not corporate or sterile.

## The Aesthetic You're Aiming For

Think Excalidraw. Think whiteboard sketch. The key qualities:
- **Imperfect borders** — lines wobble slightly, corners aren't perfectly square
- **Hatched fills** — diagonal line patterns over pastel backgrounds (not flat solid fills)
- **Handwriting font** — text looks written, not typed
- **Organic arrows** — curved bezier paths, not ruler-straight lines
- **Distinct colors** — each element gets its own bright, friendly color

This matters because hand-drawn visuals feel approachable and are more engaging in READMEs, docs, and presentations than sterile corporate diagrams. People trust them more and spend more time looking at them.

## How to Build a Sketch SVG

Every sketch SVG you create follows this structure. Read `references/patterns.md` for the actual SVG code snippets — this section explains the why and when.

### Step 1: Set Up the Canvas

Start with a white background SVG. Define your shared resources in `<defs>`:
- The **wobble filter** (`feTurbulence` + `feDisplacementMap`) that makes edges organic
- **Hatching patterns** — one per color you'll use (diagonal lines over pastel fill)
- **Arrow markers** for connection lines

The wobble filter is the single most important element. It takes any perfectly straight SVG shape and displaces its pixels using fractal noise, creating that hand-drawn edge quality. Use `baseFrequency="0.04"` and `scale="3"` as defaults — increase scale for more wobble, decrease for subtler effect.

### Step 2: Draw the Boxes (Nodes)

Each box is a `<path>` element, not a `<rect>`. Why? Because `<rect>` gives you perfectly straight edges even with the wobble filter. Instead, trace the rectangle as a path using quadratic bezier curves (`Q` command) that introduce slight natural waviness.

A wobbly rectangle path works like this:
- Move to the top-left corner
- Draw the top edge as 2-3 bezier segments, each with control points offset ±3-5px vertically
- Continue around all four sides the same way
- Close with `Z`

Fill each box with a hatching pattern (diagonal lines over a pastel color) and add a colored stroke border.

### Step 3: Add Text

Use a handwriting font stack: `"Segoe Print", "Comic Sans MS", "Bradley Hand", cursive`

This degrades gracefully across operating systems. The text should feel written, not typed. Use slightly larger font sizes than you normally would (20-28px for titles, 14-16px for sub-labels) because handwriting fonts render thinner than system fonts.

Color the text to match or complement its container's border color — not black. Black text on colored boxes looks corporate. Dark versions of the box color (the border color itself) look hand-written.

### Step 4: Draw the Arrows

Arrows connect boxes using cubic or quadratic bezier curves. The key to making them look hand-drawn:
- Use `stroke-width="2"` or thicker — thin lines look mechanical
- Apply `stroke-linecap="round"` and `stroke-linejoin="round"`
- Apply the wobble filter
- Make arrowheads as simple filled triangles, slightly oversized

For curved arrows between boxes, use `C` (cubic bezier) with control points that create a natural arc. Don't use straight lines — even for short connections, add a slight curve.

### Step 5: Add Small Icons (Optional)

The reference images include small illustrative icons inside boxes (bar charts, checkmarks, document icons). These are simple SVG shapes — 3-4 rectangles for a bar chart, a circle with a checkmark for completion. Keep them minimal. Apply the wobble filter to them too.

### Step 6: Apply the Wobble Filter

Apply `filter="url(#wobble)"` to ALL visual elements — boxes, arrows, icons. Text is the one exception: don't filter text, because displaced text becomes unreadable. The font itself provides the hand-drawn feel for text.

## Drawing Options

Just like Excalidraw's sidebar, this skill supports several configurable drawing options. The user can request any combination — if they don't specify, use the defaults marked below.

### Fill Style

Controls how box interiors are filled. The user might say "use solid fills" or "cross-hatch everything".

| Style | Description | When to use | Default? |
|-------|-------------|-------------|----------|
| **Hatched** | Diagonal lines over pastel background | Most diagrams — the classic whiteboard look | **Yes** |
| **Cross-hatched** | Two perpendicular diagonal line sets | Denser, more "sketched in" feel — good for emphasis | No |
| **Solid** | Flat pastel fill, no lines | Cleaner look, still sketchy via wobble filter | No |

See `references/patterns.md` for SVG pattern code for each style. For cross-hatching, add a second `<line>` in the pattern rotated 90 degrees from the first.

### Sloppiness (Wobble Intensity)

Controls how hand-drawn the shapes look. Maps to the wobble filter's `scale` parameter.

| Level | Filter scale | Feel | When to use |
|-------|-------------|------|-------------|
| **Architect** | `scale="1"` | Barely wobbly — neat but not mechanical | Technical docs, formal presentations |
| **Artist** | `scale="3"` | Moderate wobble — clearly hand-drawn | General purpose, READMEs, blog posts |
| **Cartoonist** | `scale="6"` | Heavy wobble — very sketchy and playful | Fun visuals, social media, casual contexts |

Default is **Artist** (`scale="3"`). If the user says "make it sloppier" increase the scale. "Make it neater" decrease it.

### Stroke Width

| Level | Width | Feel |
|-------|-------|------|
| **Thin** | `stroke-width="1"` | Pencil-fine lines |
| **Regular** | `stroke-width="2"` | Marker-weight lines |
| **Bold** | `stroke-width="3"` | Thick marker / whiteboard marker |

Default is **Regular** (`stroke-width="2"`).

### Stroke Style

| Style | SVG attribute | Feel |
|-------|--------------|------|
| **Solid** | (none) | Continuous line — default |
| **Dashed** | `stroke-dasharray="8,4"` | Dashed lines |
| **Dotted** | `stroke-dasharray="2,4"` | Dotted lines |

Default is **Solid**. Dashed/dotted are useful for secondary relationships, optional flows, or "planned" vs "existing" distinctions.

### Edge Style

Controls whether box corners are rounded or sharp.

| Style | SVG approach | Feel |
|-------|-------------|------|
| **Round** | Larger bezier control point offsets at corners (±10-15px) | Soft, organic — default |
| **Sharp** | Smaller control point offsets (±2-3px), near-straight corners | More angular, technical |

Default is **Round**.

### How to Apply These Options

When the user requests a specific style, adjust the SVG accordingly:

```
"make it cross-hatched and sloppier"
→ Use cross-hatch patterns + scale="6" on the wobble filter

"clean it up, use solid fills"
→ Use solid pastel fills (no pattern) + scale="1" wobble

"dashed borders, bold strokes"
→ Add stroke-dasharray="8,4" + stroke-width="3" to all box paths
```

If the user doesn't specify any options, use the defaults: hatched fill, artist sloppiness, regular stroke, solid stroke style, round edges.

## Color Palette

Use bright, distinct, friendly colors. Each box gets its own color. Here's a proven palette based on Excalidraw conventions:

| Element | Fill (pastel) | Hatching lines | Border/Text |
|---------|--------------|----------------|-------------|
| Blue | `#a5d8ff` | `#74b3e0` | `#1971c2` |
| Green | `#b2f2bb` | `#7dd694` | `#2b8a3e` |
| Orange/Red | `#ffd8a8` | `#e8b080` | `#e67700` |
| Yellow | `#ffec99` | `#e0cc70` | `#e67700` |
| Purple | `#d0bfff` | `#b098e0` | `#7048b8` |
| Pink | `#fcc2d7` | `#e09ab0` | `#c2255c` |

You can use other colors, but keep them in this warm-pastel register. Avoid dark fills, neon colors, or low-contrast combinations.

## Layout Patterns

Depending on what the user asks for, choose the right layout:

**Cycle / Loop** (3-4 nodes in a triangle/square with curved arrows between them)
- Great for: lifecycles, feedback loops, continuous processes
- Place a logo or label at the center of the cycle
- Arrows curve around the outside, creating circular flow

**Flow / Pipeline** (left-to-right or top-to-bottom sequence)
- Great for: data pipelines, step-by-step processes, build chains
- Connect with horizontal/vertical arrows
- Optional: loopback arrow below/beside for iteration

**DAG / Dependency graph** (one node at top, branches, merges back)
- Great for: build systems, workflow dependencies, data flow
- Fan out from top, fan back in at bottom
- Parallel branches sit side-by-side at the same vertical level

**Comparison / Side-by-side** (cards arranged in a row or grid)
- Great for: feature comparison, before/after, options
- Same-sized boxes in a row with labels

**Stacked / Timeline** (vertical stack with connecting spine)
- Great for: changelogs, phase progression, ordered steps

## Output Requirements

1. **Always produce a complete, valid SVG** — the output should render in any browser without external dependencies
2. **No JavaScript** — pure SVG with embedded `<style>`, `<defs>`, filters, and patterns
3. **No external fonts** — use the system font fallback stack
4. **Include the wobble filter** on all shapes and arrows (not text)
5. **Use hatching patterns** for fills, not flat solid colors
6. **Set a reasonable viewBox** — typically 800x520 for landscape, 600x700 for portrait
7. **Save the SVG to a file** and tell the user where it is, or write it inline if they ask

## Common Mistakes to Avoid

- **Flat solid fills** — Always use hatching patterns. Solid fills look like PowerPoint, not a whiteboard.
- **Perfectly straight lines** — Use bezier curves for everything. Even "straight" connections should have a slight curve.
- **Black text everywhere** — Color text to match its box's border color.
- **Tiny text** — Handwriting fonts render small. Use 20px+ for labels.
- **Filtering text** — Don't apply the wobble filter to `<text>` elements. It makes them unreadable.
- **Too many nodes** — Sketch diagrams work best with 3-6 nodes. More than that and it gets cluttered. If needed, group related items into a single box.
- **Forgetting the filter** — If shapes look too clean, you probably forgot to apply `filter="url(#wobble)"`.

## Reference

See `references/patterns.md` for copy-paste SVG code snippets for:
- The wobble filter definition
- Hatching pattern definitions for each color
- Wobbly rectangle path template
- Hand-drawn arrow paths
- Small icons (bar chart, checkmark, document, grid)
- A complete minimal example diagram
