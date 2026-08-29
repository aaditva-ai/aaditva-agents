# Aaditva Campaign Builder — SPA

Static Vite + React + TypeScript frontend for the Aaditva Instagram
campaign builder, replacing `gradio-ui/` (see
`docs/replace-gradio-with-spa-job-architecture.md` for the full
architecture and rationale).

## Setup

```bash
npm install
cp .env.example .env   # then fill in VITE_FIREBASE_* and VITE_BROKER_URL
npm run dev
```

Firebase config values are public client identifiers, not secrets, but are
still project-specific — see `.env.example` for where to find them in
Firebase Console.

## Scripts

- `npm run dev` — local dev server
- `npm run build` — typecheck (`tsc -b`) + production build to `dist/`
- `npm run test` — unit tests (Vitest)
- `npm run lint` — Oxlint

## Structure

- `src/api/` — the only code that talks to the broker (`authedFetch`,
  `queries.ts`'s TanStack Query hooks, `selectTranscript`'s pure page → view
  model transform)
- `src/auth/` — Firebase Auth sign-in gate
- `src/routes/` — `/` (start a campaign, recent campaigns) and
  `/c/:sessionId` (transcript view) — the URL is the only durable handle,
  no `localStorage`
- `src/components/` — presentational transcript rendering
