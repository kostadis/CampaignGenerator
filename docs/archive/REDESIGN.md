> **STATUS: ARCHIVED.** This is a UI redesign spec for the RPG Library
> frontend, which lives in a different repo. Preserved here as a design
> precedent — none of the components it names (`LibraryBrowse.vue`,
> `CommandBar.vue`, `SubjectsDrawer.vue`, etc.) exist in this codebase.
> For CampaignGenerator's actual UI, see [`docs/web/web_ui.md`](../web/web_ui.md)
> and the Vue views under `frontend/src/views/`.

---

# RPG Library — Redesign Spec (Direction A: "Catalog")

This file is the handoff for Claude Code. It describes a ground-up visual + structural redesign of the Vue frontend. Follow it top-to-bottom; every change is keyed to a file in `frontend/src/`.

**Thesis.** The current UI grew feature-by-feature: an NLQ bar sits on top of a keyword sidebar sits on top of a chip banner sits on top of a group-by toggle. Information is there but hierarchy isn't. The redesign is one calm surface: a single command bar absorbs search + NLQ + filters, a quiet facet rail handles browsing, and type does the work of separating roles.

Reference mock: `RPG Library Redesign.html` (see "01 · Search", "02 · Book detail", "03 · Browse index" under Direction A).

---

## 1. Design tokens — `src/style.css`

Replace the entire `:root` block and global resets. Light mode only for this pass.

```css
:root {
  /* Surfaces */
  --bg:          #fbfaf7;   /* warm paper, not stark white */
  --surface:     #ffffff;
  --surface-alt: #f6f4ef;   /* hover rows, chip backgrounds in the sidebar */

  /* Borders */
  --line:        #ecebe6;   /* default hairline */
  --line-hard:   #ddd9d0;   /* inputs, cards, stronger separators */

  /* Ink */
  --text:        #1d1d1b;
  --text-dim:    #6d6a62;
  --text-mute:   #9b978c;

  /* Accent — cool blue, low saturation. Replaces #e94560 everywhere. */
  --accent:      #3a5bdc;
  --accent-bg:   #edf1ff;
  --accent-ink:  #ffffff;

  /* Chips */
  --chip-bg:     #f3f1ec;
  --chip-text:   #3a3833;

  /* Semantic */
  --fav:         #d05555;
  --danger:      #b43a2e;
  --success:     #2f8a5f;

  /* Type */
  --font-sans:  'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
  --font-mono:  'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
  --font-serif: 'Source Serif 4', Georgia, serif;

  /* Scale */
  --fs-xs:   11px;
  --fs-sm:   12px;
  --fs-base: 13px;
  --fs-md:   14px;
  --fs-lg:   16px;
  --fs-xl:   20px;
  --fs-2xl:  26px;
  --fs-3xl:  34px;

  /* Radius / shadow */
  --radius-sm: 4px;
  --radius:    6px;
  --radius-lg: 8px;
  --shadow-1:  0 1px 0 rgba(0,0,0,0.02);
  --shadow-2:  0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.05);

  font-family: var(--font-sans);
  font-size: var(--fs-base);
  line-height: 1.5;
  letter-spacing: -0.005em;
  color: var(--text);
  background: var(--bg);
  color-scheme: light;
}
```

Add Google Fonts (preconnect + stylesheet link) to `frontend/index.html`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Source+Serif+4:wght@400;500;600&display=swap" rel="stylesheet">
```

Global resets stay, but:
- Default `a` color → `var(--accent)`, hover no underline, focus `underline`.
- Default `button` → `border-radius: var(--radius); padding: 6px 12px; font-size: var(--fs-sm);`.
- `.btn-primary` → `background: var(--text); color: var(--surface);` (flat black button, not accent-colored). Hover: `background: #000;`.
- `.btn-secondary` → `background: var(--surface); color: var(--text); border: 1px solid var(--line-hard);`. Hover: `background: var(--surface-alt);`.
- `.tag` → `background: var(--chip-bg); color: var(--chip-text); border-radius: var(--radius-sm); padding: 2px 7px; font-family: var(--font-mono); font-size: var(--fs-xs);`.
- `input, select` → `background: var(--surface); border: 1px solid var(--line-hard); border-radius: var(--radius); padding: 6px 10px;`. Focus: `border-color: var(--accent); outline: none; box-shadow: 0 0 0 3px var(--accent-bg);`.

Delete the old dark-mode variables (`--bg-card`, `--bg-sidebar`, etc.) and update every `var(...)` reference accordingly — a search for `var(--bg-` should produce zero hits after this pass.

---

## 2. App shell — `src/App.vue`

The current header is a dark bar with a red accent border. Replace with a flat light top bar that feels like Linear's.

**Structure**

```
<header class="topbar">
  <router-link to="/" class="brand">
    <span class="brand-mark"></span>
    <span class="brand-name">RPG Library</span>
  </router-link>

  <nav class="topnav">
    <router-link to="/">Search</router-link>
    <router-link to="/browse/series">Series</router-link>
    <router-link to="/browse/publisher">Publishers</router-link>
    <router-link to="/browse/game_system">Systems</router-link>
    <router-link to="/browse/tag">Tags</router-link>
    <router-link to="/graph">Graph</router-link>
  </nav>

  <div class="topbar-right">
    <span class="kbd">⌘K</span>
    <span class="stat">{{ totalBooks.toLocaleString() }} books</span>
  </div>
</header>
```

- Remove the "Browse:" text label — nav items sit directly next to Search.
- `totalBooks` comes from `store.totalBooks` (add a getter that returns the library total; `loadFilters()` already has the data).

**Styles**

```css
.topbar {
  height: 52px;
  display: flex; align-items: center; gap: 24px;
  padding: 0 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 8px;
  font-family: var(--font-serif); font-size: var(--fs-lg); font-weight: 600;
  color: var(--text); text-decoration: none; letter-spacing: -0.01em; }
.brand-mark { width: 14px; height: 14px; border-radius: 3px; background: var(--text); }
.topnav { display: flex; gap: 2px; }
.topnav a {
  padding: 6px 10px; border-radius: var(--radius);
  font-size: 12.5px; color: var(--text-dim); text-decoration: none;
}
.topnav a:hover { background: var(--surface-alt); color: var(--text); }
.topnav a.router-link-active {
  background: var(--chip-bg); color: var(--text); font-weight: 500;
}
.topbar-right { margin-left: auto; display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-mute); }
.kbd { border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px;
  background: var(--surface); }
```

No dark backgrounds. No red border.

---

## 3. Command bar — new component, replaces NLQ bar + search inputs + chip banner

Create `src/components/CommandBar.vue`. This is the single biggest change.

**Why.** Today there are three horizontal strips stacked: `nlq-bar` + two "Search All" / "Search by Title" inputs in the sidebar + `active-filters` chip banner. They do the same job (narrow results) with three UIs. Collapse into one.

**Behavior**

One text input. Everything typed becomes either:
- Free text (plain keyword search) — shown as italic placeholder-colored text at the end of the input.
- A token, rendered inline as a chip: `system:D&D 5e`, `tag:horror`, `level:5`, `pub:Chaosium`, `!tag:undead` (excluded).

Tokens are created by:
1. Typing a token directly (`system:5e`) — on space/enter, it becomes a chip.
2. Clicking a facet in the sidebar — chip appears in the bar.
3. Hitting the NLQ "Ask" path (below) — parsed system/type/tags appear as chips; remaining keywords stay as free text.

A single "Enter" behavior:
- If the input contains any natural-language words not in token form **and** no chips have been explicitly added this keystroke, POST to `/api/library/nlq` (existing endpoint). Populate chips from `query_parsed`. Put residual `keywords` as free text in the bar.
- Otherwise, run a normal search with the current chips + free text.

This replaces `doNlqSearch` + `doSearch` + `activeFilterChips` + `clearAllChips`.

**Layout**

```vue
<div class="cmd">
  <span class="cmd-glyph">⌕</span>

  <Chip v-for="c in chips" :key="c.key"
        :label="c.label" :value="c.value" :excluded="c.excluded"
        @remove="c.remove" @invert="c.invert" />

  <input
    v-model="draft"
    class="cmd-input"
    placeholder='Search or ask — e.g. "horror 5e adventures with undead"'
    @keydown.enter="submit"
    @keydown.backspace="maybePopChip"
  />

  <button class="cmd-addfilter" @click="openAddFilter">+ filter</button>
  <span class="kbd">⏎</span>
</div>

<div class="cmd-meta">
  <span v-if="nlqActive">parsed as natural language</span>
  <span v-if="nlqActive">·</span>
  <span>{{ store.total.toLocaleString() }} results</span>
  <span>·</span>
  <button class="cmd-reset" @click="reset">reset</button>
</div>
```

**Chip.vue** (shared — use for the command bar and any other in-page filter display):

```css
.chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 4px 2px 8px; border-radius: var(--radius-sm);
  background: var(--chip-bg); color: var(--chip-text);
  font-size: var(--fs-sm); line-height: 1.5; white-space: nowrap;
}
.chip-key {  /* mono prefix like "system:" */
  font-family: var(--font-mono); font-size: 10.5px;
  color: var(--text-mute); text-transform: lowercase;
}
.chip-value { font-weight: 500; }
.chip-x {
  width: 14px; height: 14px; display: inline-flex; align-items: center;
  justify-content: center; color: var(--text-mute); font-size: 11px;
  cursor: pointer;
}
.chip--excluded { background: #fbeae7; color: var(--danger); }
.chip--excluded .chip-value { text-decoration: line-through; }
```

**Command bar styles**

```css
.cmd {
  display: flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1px solid var(--line-hard);
  border-radius: var(--radius-lg); padding: 8px 10px 8px 12px;
  box-shadow: var(--shadow-1);
}
.cmd:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-bg); }
.cmd-glyph { color: var(--text-mute); font-size: 13px; }
.cmd-input {
  flex: 1; border: none; background: transparent; outline: none; padding: 0;
  font-family: var(--font-sans); font-size: var(--fs-base); color: var(--text);
}
.cmd-input::placeholder { color: var(--text-mute); font-style: italic; }
.cmd-addfilter {
  background: transparent; border: none; padding: 4px 8px; border-radius: 4px;
  font-size: var(--fs-sm); color: var(--text-dim); cursor: pointer;
}
.cmd-addfilter:hover { background: var(--surface-alt); color: var(--text); }
.cmd-meta {
  margin-top: 8px; display: flex; gap: 14px;
  font-family: var(--font-mono); font-size: 11.5px; color: var(--text-mute);
}
.cmd-reset { background: none; border: none; padding: 0; cursor: pointer;
  color: var(--accent); font-family: inherit; font-size: inherit; }
```

**Mount point.** The command bar lives in `LibraryBrowse.vue` at the top of the results column (not in the sidebar, not in App.vue). Its sibling is the sidebar; they share a horizontal band above the results header.

**Delete.** The entire `.nlq-bar`, `.nlq-applied-banner`, and `.active-filters` sections in `LibraryBrowse.vue`. The two sidebar "Search All" / "Search by Title" inputs. Their handlers (`doNlqSearch`, `clearNlqBanner`, the big `activeFilterChips` computed). Wire the store to fetch from chips + draft directly.

---

## 4. Sidebar facet rail — `LibraryBrowse.vue` (rewrite)

Rename mentally from "filter sidebar" to "facet rail." Narrower, quieter, scannable.

**Width.** 220px (was 260).

**Structure.** Replace the `<select>` dropdowns and "Advanced" accordion with groups of clickable text rows, each row showing `value` left, `count` right-aligned in mono.

```vue
<aside class="rail">
  <FacetGroup title="System" :items="store.filters.game_system.slice(0, 6)"
              :active="store.activeFilters.game_system"
              @pick="store.setFilter('game_system', $event)" />
  <FacetGroup title="Type"   :items="store.filters.product_type.slice(0, 6)"
              :active="store.activeFilters.product_type"
              @pick="store.setFilter('product_type', $event)" />

  <FacetGroup title="Tags" :items="topTags" :active="store.activeFilters.tags"
              @pick="store.setFilter('tags', $event)">
    <template #footer>
      <button class="rail-more" @click="openSubjects">Browse all tags ›</button>
    </template>
  </FacetGroup>

  <FacetGroup title="Level" :items="levelBuckets"
              :active="activeLevelBucket" @pick="setLevelBucket" />

  <div class="rail-flags">
    <Checkbox v-model="store.favoritesOnly" label="Favorites only" />
    <Checkbox v-model="store.includeDrafts" label="Include drafts" muted />
    <Checkbox v-model="store.includeDuplicates" label="Include duplicates" muted />
    <Checkbox v-model="store.includeOld" label="Include old versions" muted />
  </div>
</aside>
```

**FacetGroup** (`components/FacetGroup.vue`):

```vue
<template>
  <section class="facet">
    <div class="facet-head">
      <span>{{ title }}</span>
      <span class="facet-add">+</span>
    </div>
    <ul class="facet-list">
      <li v-for="it in items" :key="it.value"
          :class="{ 'is-active': it.value === active }"
          @click="$emit('pick', it.value === active ? '' : it.value)">
        <span class="facet-val">{{ it.value }}</span>
        <span class="facet-count">{{ it.count.toLocaleString() }}</span>
      </li>
    </ul>
    <slot name="footer" />
  </section>
</template>
```

**Styles**

```css
.rail { width: 220px; min-width: 220px; flex-shrink: 0;
  border-right: 1px solid var(--line); background: var(--bg);
  padding: 16px 14px 40px; overflow-y: auto; }

.facet { margin-bottom: 18px; }
.facet-head {
  display: flex; justify-content: space-between;
  font-family: var(--font-mono); font-size: 10.5px;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--text-mute); margin-bottom: 6px;
}
.facet-list { list-style: none; padding: 0; margin: 0; }
.facet-list li {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 3px 6px; border-radius: 4px; font-size: 12.5px;
  cursor: pointer;
}
.facet-list li:hover { background: var(--surface-alt); }
.facet-list li.is-active {
  background: var(--accent-bg); font-weight: 500;
}
.facet-val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.facet-count { font-family: var(--font-mono); font-size: 10.5px;
  color: var(--text-mute); flex-shrink: 0; margin-left: 8px; }
.rail-more { background: none; border: none; padding: 3px 6px;
  font-size: 11.5px; color: var(--accent); cursor: pointer; }
.rail-flags { margin-top: 18px; padding-top: 14px;
  border-top: 1px solid var(--line);
  display: flex; flex-direction: column; gap: 6px; }
```

**Delete.** The existing `select` dropdowns in the sidebar. The "Advanced" toggle + accordion — Publisher/Series/Source move *inside* the command bar's "+ filter" picker, not the rail. The tag-groups dropdown (`TAG_GROUPS`) moves into the Subjects drawer (§6).

---

## 5. Results — `LibraryBrowse.vue` (table + cards)

**Header bar above results.**

```vue
<div class="results-head">
  <div class="results-count">
    <span class="num">{{ store.total.toLocaleString() }}</span> books
    <span class="mute">· sorted by {{ sortLabel }}</span>
  </div>
  <div class="groupby">
    <button v-for="opt in GROUP_OPTIONS" :key="opt.value"
            :class="['pill', { active: store.groupBy === opt.value }]"
            @click="store.setGroupBy(opt.value)">
      {{ opt.label }}
    </button>
  </div>
</div>
```

```css
.results-head { display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px 10px; }
.results-count { font-size: var(--fs-base); color: var(--text-dim); }
.results-count .num { color: var(--text); font-weight: 500; font-family: var(--font-mono); }
.results-count .mute { color: var(--text-mute); }
.groupby { display: flex; gap: 2px; }
.pill {
  padding: 4px 9px; font-size: var(--fs-sm); border-radius: 5px;
  background: transparent; border: none; color: var(--text-dim); cursor: pointer;
}
.pill:hover { background: var(--surface-alt); color: var(--text); }
.pill.active { background: var(--chip-bg); color: var(--text); font-weight: 500; }
```

**Table.** Keep the columns; restyle.

```css
.book-table { width: 100%; border-collapse: collapse; font-size: var(--fs-base); }
.book-table thead th {
  padding: 6px 12px; text-align: left;
  font-family: var(--font-mono); font-size: 10.5px;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--text-mute); border-bottom: 1px solid var(--line);
  font-weight: 400; white-space: nowrap;
}
.book-table tbody tr {
  border-bottom: 1px solid var(--line);
}
.book-table tbody td { padding: 10px 12px; max-width: 300px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.book-table tbody tr:hover { background: var(--surface-alt); }
.col-title { color: var(--text); font-weight: 500; }
.book-table tbody tr:hover .col-title { text-decoration: none; }
.col-num { text-align: right; font-family: var(--font-mono); font-size: 11.5px;
  color: var(--text-dim); }
.type-badge {
  display: inline-block; padding: 1px 5px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 10.5px;
  color: var(--text-dim); border: 1px solid var(--line);
  text-transform: uppercase; letter-spacing: 0.04em;
  background: transparent;
}
```

Key changes:
- Header text is mono uppercase micro-type, not bold.
- `type-badge` becomes an outlined mono pill, not a solid red badge.
- Row hover is a warm off-white, no red underline on the title.
- Sort icons use `↑ ↓` (not triangles) and only show on the active column; inactive columns show nothing, not `⇅`.

**Cards.**

```css
.book-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px; padding: 0 20px 20px; }
.book-card {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius-lg); padding: 16px;
  text-decoration: none; color: inherit; display: block;
  transition: border-color 120ms, box-shadow 120ms;
}
.book-card:hover { border-color: var(--line-hard); box-shadow: var(--shadow-2); }
.card-meta-row {
  font-family: var(--font-mono); font-size: 10.5px; color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;
}
.card-title { font-family: var(--font-sans); font-size: var(--fs-md);
  font-weight: 600; color: var(--text); margin-bottom: 6px; letter-spacing: -0.005em; }
.card-desc { font-size: var(--fs-sm); color: var(--text-dim);
  line-height: 1.5; margin-bottom: 10px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; }
```

**Favorite button.** Heart stays; color → `var(--fav)`. Inactive → outline heart in `var(--text-mute)`.

**Empty state + skeletons.** Keep them but adopt the new palette (`var(--surface-alt)` for skeleton cells, `var(--text-mute)` for icon + message).

---

## 6. Subjects drawer — new component

New file `src/components/SubjectsDrawer.vue`. Trigger: the "Browse all tags ›" link in the rail, plus a `?` keybinding. Works exactly like a command palette.

**Layout.** Centered overlay, ~720px wide, with:
1. Header: "Subjects" title + count of selected / esc hint.
2. A text filter input.
3. Tabs: All / Content / Setting / Format / Genre / System (these map to the existing `TAG_GROUPS` in `LibraryBrowse.vue` — move the constant into the drawer).
4. Grouped tag chips with counts, selected state as solid dark chip with count in white-muted.
5. Footer: "N subjects will narrow to X books · Clear · Apply".

Port the existing `TAG_GROUPS` array into the drawer; augment each group with `{count}` per tag from `store.filters.tags`.

Styles are listed in the mock; crib from direction B's Subjects drawer — but use `var(--accent)` for the active underline instead of oxblood, and keep the Inter/mono/serif triplet from direction A.

---

## 7. Book detail — `src/views/BookDetail.vue`

Keep sections; rewrite the header and visual weight.

**Header.**

```vue
<div class="breadcrumb">← <router-link :to="{ name: 'browse' }">Search</router-link> / Horror / {{ book.display_title }}</div>

<div class="detail-eyebrow">{{ book.publisher }} · {{ book.game_system }}</div>

<h1 class="detail-title">{{ book.display_title || book.filename }}</h1>

<div class="detail-meta">
  <span>{{ book.product_type?.toLowerCase() }}</span>
  <span>·</span>
  <span>{{ book.page_count }} pages</span>
  <span v-if="book.min_level">·</span>
  <span v-if="book.min_level">levels {{ book.min_level }}–{{ book.max_level }}</span>
  <span v-if="book.is_favorite">·</span>
  <span v-if="book.is_favorite" class="is-fav">♥ favorited</span>
</div>
```

```css
.detail-page { max-width: 780px; margin: 0 auto; padding: 24px 48px; }
.breadcrumb { font-family: var(--font-mono); font-size: 11px;
  color: var(--text-mute); margin-bottom: 18px; }
.detail-eyebrow {
  font-family: var(--font-mono); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-mute); margin-bottom: 6px;
}
.detail-title {
  font-family: var(--font-serif); font-size: var(--fs-3xl);
  font-weight: 600; letter-spacing: -0.02em; line-height: 1.15;
  color: var(--text); margin: 0 0 12px;
}
.detail-meta {
  display: flex; flex-wrap: wrap; gap: 10px;
  font-family: var(--font-mono); font-size: 12px; color: var(--text-dim);
  margin-bottom: 20px;
}
.detail-meta .is-fav { color: var(--fav); }
```

**Actions row.** Two flat buttons; the heart moves into `.detail-meta` as above, so only PDF actions live here.

```vue
<div class="detail-actions">
  <button class="btn-primary" @click="openInApp">Open PDF</button>
  <button class="btn-secondary" @click="previewPdf">Preview in browser</button>
  <span v-if="openStatus" class="open-status">{{ openStatus }}</span>
</div>
```

**Description.** Typeset in serif for reading.

```css
.detail-description {
  font-family: var(--font-serif); font-size: 15.5px; line-height: 1.65;
  color: var(--text); max-width: 620px; margin-bottom: 28px;
}
```

**Section heads.** Mono micro-type, not big H2s.

```css
.detail-section { margin-bottom: 28px; }
.detail-section-head {
  font-family: var(--font-mono); font-size: 10.5px;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-mute); margin-bottom: 10px;
}
```

**Table of contents.** Replace the shaded card with a plain list + dotted leaders.

```css
.toc-item {
  display: flex; justify-content: space-between;
  padding: 4px 0; border-bottom: 1px dotted var(--line);
  font-family: var(--font-mono); font-size: 12px; color: var(--text);
  cursor: pointer;
}
.toc-item:hover { color: var(--accent); }
.toc-page { color: var(--text-mute); }
```

**Related books.** Cards become smaller flat tiles (no red hover border, no dark card background).

**Metadata table.** Keep as-is; restyle to match the new line color.

---

## 8. Browse index — `src/views/BrowseIndex.vue` + `components/DimensionGrid.vue`

Today this renders a big tile grid. Redesign as a two-column directory list — faster to scan when there are hundreds of series.

**Page head.**

```vue
<div class="browse-head">
  <h1 class="browse-title">Browse {{ typeLabel }}</h1>
  <div class="browse-sub">{{ items.length }} {{ typeLabel }} · {{ totalBooks.toLocaleString() }} books</div>
</div>
<div class="browse-tools">
  <input class="browse-filter" v-model="filter" placeholder="Filter…" />
  <div class="browse-sort">
    <button :class="{ active: sort==='count' }" @click="sort='count'">By count</button>
    <button :class="{ active: sort==='name' }" @click="sort='name'">By name</button>
  </div>
</div>
<div class="browse-index">
  <router-link v-for="it in filtered" :key="it.value"
               class="browse-row"
               :to="{ name: 'topic', params: { type, name: it.value } }">
    <span class="browse-name">{{ it.value }}</span>
    <span class="browse-count">{{ it.count }}</span>
  </router-link>
</div>
```

```css
.browse-head h1 { font-family: var(--font-serif); font-size: var(--fs-2xl);
  font-weight: 600; letter-spacing: -0.01em; color: var(--text); margin: 0; }
.browse-sub { font-family: var(--font-mono); font-size: 11px; color: var(--text-mute); }
.browse-tools { display: flex; gap: 12px; margin: 16px 0; max-width: 900px; }
.browse-filter { flex: 1; max-width: 420px; }
.browse-sort { display: flex; gap: 2px; margin-left: auto; }
.browse-sort button { background: transparent; border: none;
  padding: 4px 9px; border-radius: 5px;
  font-size: var(--fs-sm); color: var(--text-dim); cursor: pointer; }
.browse-sort button.active { background: var(--chip-bg); color: var(--text); font-weight: 500; }

.browse-index {
  display: grid; grid-template-columns: repeat(2, 1fr);
  column-gap: 24px; max-width: 900px;
}
.browse-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 10px 0; border-bottom: 1px solid var(--line);
  text-decoration: none; color: var(--text); font-size: 13.5px;
}
.browse-row:hover .browse-name { color: var(--accent); }
.browse-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  padding-right: 12px; }
.browse-count { font-family: var(--font-mono); font-size: 11px;
  color: var(--text-mute); flex-shrink: 0; }
```

Retire `DimensionGrid.vue`'s tile styling — it was used in `BrowseIndex.vue` **and** in the group-by facet view inside `LibraryBrowse.vue`. Update the latter to render the same two-column row list (share the component — rename it to `DirectoryIndex.vue`).

---

## 9. Topic hub — `src/views/TopicHub.vue`

Out of scope for this pass, but apply the new tokens (line colors, font stack, chip styles) so nothing feels orphaned. Do not rework the layout.

---

## 10. Graph view — `src/views/GraphView.vue`

Same — retheme only. Node stroke → `var(--line-hard)`, labels → `var(--text)`, link color → `var(--text-mute)`, selected node → `var(--accent)`.

---

## 11. Things to delete outright

- Every `#e94560` / `#ff6b81` / red-accent use in component styles. Search the repo; there should be no hits after this pass.
- `.nlq-bar`, `.nlq-inner`, `.nlq-input`, `.nlq-btn`, `.nlq-clear`, `.nlq-applied-banner`, `.banner-label`, `.nlq-chip`, `.tag-chip`, `.keywords-chip`, `.nlq-clear-applied` in `LibraryBrowse.vue`.
- `.active-filters`, `.active-filters-label`, `.filter-chip*`, `.filters-clear-all` — replaced by the chip rendering inside `CommandBar.vue`.
- `.advanced-section`, `.advanced-toggle`, `.advanced-body` — replaced by the `+ filter` menu in `CommandBar`.
- The `search-mode` div/class if present.
- `.search-btn` and `.clear-btn` in the sidebar — the command bar's reset link covers both.

---

## 12. Suggested implementation order

1. §1 tokens + §2 shell. Verify site doesn't look broken.
2. §5 results styling (table/cards against new tokens) — most of the UI.
3. §4 facet rail — removes the old `<select>` dropdowns.
4. §3 command bar — biggest behavioral change; merges three inputs into one.
5. §7 book detail.
6. §8 browse index + §9/§10 retheming.
7. §6 subjects drawer (ship last; the command bar's `tag:` chip + facet rail tags-group both work without it).

Each step should land green — don't mix §3 into §1.

---

## 13. Out of scope

- Dark mode (can return later; tokens already centralized).
- Mobile layout (the facet rail should just stack above results on narrow widths — `@media (max-width: 900px)` — but full mobile polish is separate).
- Any backend changes. The NLQ endpoint, facets endpoint, favorites, variant groups — all stay.