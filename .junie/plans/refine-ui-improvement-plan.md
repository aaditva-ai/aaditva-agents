---
sessionId: session-260831-222100-r9we
---

# Requirements

### Overview & Goals

The goal is to update `web/UI_IMPROVEMENTS_PLAN.md` to accurately reflect the required architectural changes necessary to achieve a polished, production-ready user interface in the web application. The current plan details component styling but overlooks the critical need for persistent global layout components (like a Navbar and overall page container) which are causing the "lack of polish" complaint.

### Scope

**In Scope:**
*   Diagnosing the root cause of the UI's lack of high-level polish (e.g., missing consistent navigation, inconsistent page boundaries).
*   Updating `web/UI_IMPROVEMENTS_PLAN.md` with concrete steps to introduce a structural layout component.

**Out of Scope:**
*   Implementing all functional changes mentioned in the existing plan (Tailwind setup, etc.); this focuses only on the *structural documentation update*.

### Diagnosis: The Missing Global Layout

The current implementation relies on routing directly from `App.tsx` into route-specific components (`HomeRoute`, `CampaignRoute`). While these internal components can be styled well using Tailwind CSS and design tokens (as per sections 1-7 of the existing plan), they lack a common, persistent wrapper that provides global context to the user—such as a site-wide navigation bar or consistent page container with margins.

The current `web/src/App.tsx` is simply:
\`\`\`typescript
<Routes>
  <Route path="/" element={<HomeRoute />} />
  <Route path="/c/:sessionId" element={<CampaignRoute />} />
</Routes>
\`\`\`

This structure treats every page as an independent, unconstrained view, leading to the observed "terrible layout" feeling.

### Proposed Architectural Fix (The Layout Component)

A new structural component, `<Layout />`, must be introduced in `web/src/components/` that wraps all routed components within `App.tsx`. This component will enforce global elements and visual consistency across the entire application.

**Architecture:**
\`\`\`mermaid
graph LR
    User --> App.tsx[React Router];
    App.tsx --> Layout(Global <Layout /> Component);
    Layout --> Navbar[Persistent NavBar/Header];
    Layout --> Sidebar{Optional Sidebar};
    Layout --> Content[Page Content (HomeRoute / CampaignRoute)];
\`\`\`

**Technical Change Summary:**
1.  Create `web/src/components/Layout.tsx`.
2.  Modify `web/src/App.tsx` to use `<Routes>` inside the `<Layout />` wrapper.
3.  Update `web/UI_IMPROVEMENTS_PLAN.md` to prioritize this structural fix above component-level polish, as it is foundational to fixing the overall layout issue.

# Technical Design

### Current Implementation Analysis

The existing code demonstrates a clear separation of concerns for routing (defined in `App.tsx`) and localized styling (detailed in `web/UI_IMPROVEMENTS_PLAN.md`). The current structure is highly modular, using functional components that assume a well-defined wrapper container.

**Key Files Affected:**
*   `/src/App.tsx`: Defines the routing boundary. Needs modification to wrap routes with a structural component.
*   `web/UI_IMPROVEMENTS_PLAN.md`: The target document. Its implementation path must be updated to include the global layout dependency.

**Technical Gap (The Root Cause):**
The primary architectural gap is the lack of an encompassing, persistent root component in `App.tsx`. While all individual components are styled using Tailwind utilities (as planned), they do not exist within a shared `<main>` or container element that governs global margins, page headers/footers, and the presence of essential navigational elements like a primary menu bar.

### Key Decisions

1.  **Decision: Introduce a dedicated Layout Component (`<Layout />`)**: This component will encapsulate all common structural elements (Navbar, main content area, etc.).
    *   *Rationale:* Following established React/SPA patterns, wrapping the `<Routes>` in a dedicated layout is the most idiomatic way to provide persistent UI shell functionality without coupling it to specific routes.
2.  **Decision: Update `App.tsx`**: The component must be modified to render the `<Layout />` wrapper and pass the router's output (the rendered route element) as its primary child.

### Proposed Changes

1.  **File Creation:** Create `web/src/components/Layout.tsx`. This file will define the shell structure, incorporating a basic Navbar placeholder and reserving space for sidebars or footers.
2.  **Modification (`App.tsx`):** Update `App.tsx` to import and render `<Layout />`, passing the router's element to it.
3.  **Document Update:** Modify `web/UI_IMPROVEMENTS_PLAN.md` to explicitly add "Implementing Global Layout Structure" as a foundational, mandatory step that must precede all fine-tuning work described in sections 2 and 4 of the current plan.

### File Structure Changes

*   **New File:** `web/src/components/Layout.tsx`
*   **Modified File:** `web/src/App.tsx`
*   **Target Documentation Update:** `web/UI_IMPROVEMENTS_PLAN.md` (Content modification)

# Delivery Steps

###   Step 1: Implement Global Layout Wrapper in App.tsx
The core application logic will wrap all routes with a persistent layout component (e.g., <Layout />). This addresses the missing global navigation and overall page container structure required for polish across all pages.

- Update `web/src/App.tsx` to use `<Layout>` as a wrapper around `<Routes>`.
- Create a new `web/src/components/Layout.tsx` that contains the persistent structural elements (Navbar, Sidebar area).
- Implement basic structure in `Layout.tsx`: 1. Fixed Navbar at top. 2. Main content area (`flex-grow`) below the navbar. 3. Optional sidebar integration point on larger screens.

###   Step 2: Refactor and Update UI_IMPROVEMENTS_PLAN.md
The existing design plan will be updated to reflect the necessary structural changes. This step makes the documentation accurate by adding the Layout Component implementation as the critical next step after basic styling is done.

- Open `web/UI_IMPROVEMENTS_PLAN.md`.
- Add a new section (e.g., "Structural Polish: Global Layout") detailing the need for and plan to create `<Layout />` component.
- Update the "Recommended Implementation Path" section of the markdown file to prioritize creating this foundational layout component before further feature-specific styling or refinement is done.