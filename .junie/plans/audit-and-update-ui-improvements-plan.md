---
sessionId: session-260901-134452-5iaq
---

# Requirements

### Overview & Goals
The objective is to analyze the existing `web/UI_IMPROVEMENTS_PLAN.md`, compare it against the actual implementation in the `web/` directory (React + Vite + Tailwind CSS SPA), and update the markdown file to accurately document what has been completed, what is partially completed, and what remains pending.

### Scope

#### In Scope
- Comprehensive status audit of all UI components, stylesheets, and configs in `web/`.
- Reconciling claims in `web/UI_IMPROVEMENTS_PLAN.md` with actual source code in `web/src/` and `web/package.json`.
- Updating `web/UI_IMPROVEMENTS_PLAN.md` with:
  - Accurate status indicators (Done ✅, In Progress / Partial 🟡, Pending ⏳).
  - Clear itemization of unstyled components (e.g. `SignInGate.tsx`, `TranscriptView.tsx`).
  - Remaining architectural improvements (Global Layout shell, Navbar, unified container widths).
  - Accessibility and polish backlog (ARIA tags, font loading, heading deduplication).
  - Removal / deprecation roadmap for legacy `App.css`.

#### Out of Scope
- Modifying React code or CSS files (handled in subsequent implementation phases).
- Backend or broker API adjustments.

### User Stories
- **As a Developer/Maintainer**, I want `web/UI_IMPROVEMENTS_PLAN.md` to be an accurate source of truth so that I know exactly which components are fully styled with Tailwind and which tasks remain in the backlog.
- **As a Product Contributor**, I want a prioritized list of pending UI/UX improvements (layout consistency, accessibility, theming) so that future sprints can deliver maximum visual and functional polish efficiently.

# Technical Design

### Current Codebase Audit vs. Plan

Based on a file-by-file audit of the `web/` folder, here is the verified status of the UI improvements:

#### 1. Build, Theming & Configuration
| Item | Status | Details |
| :--- | :---: | :--- |
| **Bun Package Manager** | ✅ Done | `package.json` scripts and `bun.lock` configured for Bun. |
| **Tailwind CSS Setup** | ✅ Done | `@tailwindcss/vite` (v4) and `tailwind.config.mjs` configured. |
| **Design Token System** | ✅ Done | `src/index.css` defines `:root` and `.dark` CSS variables (`--primary`, `--background`, `--card`, `--muted`, etc.). |
| **Google Fonts (Inter)** | 🟡 Partial | `index.css` defines font-family `'Inter'`, but Google Fonts stylesheet `<link>` is not yet added in `index.html`. |
| **Production Build Script** | ✅ Done | `bun run build` emits to `dist/`, configured in `firebase.json`. |

#### 2. Components & Routes
| Component / File | Status | Audit Findings |
| :--- | :---: | :--- |
| **`HomeRoute.tsx`** | ✅ Done | Styled with Tailwind utility classes, clean card header, accessible textarea, animated loading spinner, and error banner. Minor cleanup: duplicate `<h2>Recent campaigns</h2>`. |
| **`RecentCampaigns.tsx`** | ✅ Done | Responsive 2-column grid, card hover states, colored status dots (`complete`, `running`, `failed`), loading skeleton, empty state SVG. |
| **`CampaignRoute.tsx`** | ✅ Done | Sticky header with back navigation, loading spinner ring, reconnecting notice, empty state illustration, and error banners. |
| **`StatusBanner.tsx`** | ✅ Done | Semantic color treatments (`emerald`, `destructive`, `yellow`), proper spacing, focus-visible ring on resume action button. |
| **`StepCard.tsx`** | ✅ Done | Card wrapper with shadow, tool call badges (blue), tool result `<details>` accordion (green), image tiles with hover shadow, and transfer badges (purple). |
| **`TranscriptView.tsx`** | 🟡 Partial | Still uses legacy `<div className="transcript">` class from `App.css` instead of Tailwind flex layout utilities. |
| **`SignInGate.tsx`** | ❌ Pending | Uses legacy unstyled `className="centered-page"` and raw buttons/headings from `App.css`. Needs complete Tailwind conversion. |
| **`App.css` Legacy Styles** | ❌ Pending | Still contains 154 lines of legacy CSS rules; pending complete cleanup once all components are migrated. |
| **Global `<Layout />` Shell** | ❌ Pending | No shared persistent layout/navbar component exists in `App.tsx`; `HomeRoute` (`max-w-md`) and `CampaignRoute` have divergent container widths. |

#### 3. Accessibility & Polish
| Item | Status | Details |
| :--- | :---: | :--- |
| **Focus-Visible Rings** | ✅ Done | Interactive buttons and summaries have `focus-visible:ring`. |
| **ARIA Screen Reader Labels** | ❌ Pending | Tool call/result badges and image figcaptions lack explicit `aria-label` / `aria-describedby` attributes. |
| **Heading Duplication** | ❌ Pending | `HomeRoute.tsx` has a redundant `<h2>Recent campaigns</h2>` wrapper preceding `<RecentCampaigns />`. |

---

### Structure of Updated `UI_IMPROVEMENTS_PLAN.md`

The updated `web/UI_IMPROVEMENTS_PLAN.md` will be organized into:
1. **Executive Summary & Tech Stack Status** (Bun, Vite, Tailwind v4, Design Tokens).
2. **Completed Milestones (✅ Done)**:
   - Tooling & Token Architecture.
   - Core Route Styling (`HomeRoute`, `CampaignRoute`).
   - Feed & Status Components (`RecentCampaigns`, `StatusBanner`, `StepCard`).
3. **In-Progress / Partially Done (🟡 Partial)**:
   - `TranscriptView.tsx` container styling.
   - Font loading optimization in `index.html`.
4. **Pending Backlog & Next Steps (⏳ Pending)**:
   - **Step A: Auth Gate Redesign (`SignInGate.tsx`)** — Card-based login UI with Tailwind utilities.
   - **Step B: Global Layout Component (`Layout.tsx`)** — Persistent navigation header, user status, and responsive page shell.
   - **Step C: Accessibility & Heading Refinement** — ARIA labels and duplicate heading cleanup.
   - **Step D: Legacy CSS Purge** — Remove unused rules in `App.css` and streamline styling imports.

# Delivery Steps

### ✓ Step 1: Audit web folder UI components and styling status
A detailed inventory of every UI component and style asset in the `web` folder is documented.
- Inspect every source file in `web/src/` (`SignInGate.tsx`, `TranscriptView.tsx`, `StepCard.tsx`, `RecentCampaigns.tsx`, `HomeRoute.tsx`, `CampaignRoute.tsx`, `App.tsx`, `App.css`, `index.css`, `index.html`).
- Validate Tailwind CSS configuration, theme variables, and Vite build configuration.
- Catalog exact implementation gaps, styling mismatches, duplicate headings, and legacy CSS dependencies.

### ✓ Step 2: Draft updated status and pending items for UI_IMPROVEMENTS_PLAN.md
A structured, accurate markdown revision for `web/UI_IMPROVEMENTS_PLAN.md` is drafted.
- Structure updated status tables categorizing items into Completed (✅), Partially Completed (🟡), and Pending (⏳).
- Add specific remediation notes for unstyled components (`SignInGate.tsx`, `TranscriptView.tsx`), global `<Layout />` structure, accessibility improvements (ARIA labels), and legacy `App.css` removal.
- Update the "Next Steps" and "Implementation Path" sections to guide subsequent development iterations.

### ✓ Step 3: Update and finalize web/UI_IMPROVEMENTS_PLAN.md
`web/UI_IMPROVEMENTS_PLAN.md` is updated and verified against the actual repository state.
- Write the finalized analysis and updated status directly into `web/UI_IMPROVEMENTS_PLAN.md`.
- Ensure all sections (Current State, Completed Features, Partially Completed Features, Pending Backlog, and Next Steps) are coherent, clear, and actionable.