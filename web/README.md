# Aaditva Campaign Builder — SPA

Static Vite + React + TypeScript frontend for the Aaditva Instagram
campaign builder, replacing `gradio-ui/` (see
`docs/replace-gradio-with-spa-job-architecture.md` for the full
architecture and rationale).

## Setup

**Prerequisites:** [Bun](https://bun.sh) package manager installed globally.

```bash
bun install
cp .env.example .env   # then fill in VITE_FIREBASE_* and VITE_BROKER_URL
bun run dev
```

Firebase config values are public client identifiers, not secrets, but are
still project-specific — see `.env.example` for where to find them in
Firebase Console.

## Scripts

All commands use `bun`:

- `bun run dev` — local development server (Vite)
- `bun run build` — typecheck (`tsc -b`) + production build to `dist/`
- `bun run test` — unit tests (Vitest)
- `bun run lint` — Oxlint
- `bun run deploy` — deploy static bundle to Firebase Hosting (`firebase deploy --only hosting`)

> **Note:** This project uses Bun as the package manager for `web/`. All dependency installation, dev, and build commands should use `bun`.

## Deploying

For production deployment to Firebase Hosting:

```bash
bun install
bun run build
bun run deploy
```

This builds the static bundle to `dist/` and deploys it to Firebase Hosting as configured in `firebase.json` and `.firebaserc`.

## Structure

- `src/api/` — the only code that talks to the broker (`authedFetch`,
  `queries.ts`'s TanStack Query hooks, `selectTranscript`'s pure page → view
  model transform)
- `src/auth/` — Firebase Auth sign-in gate
- `src/routes/` — `/` (start a campaign, recent campaigns) and
  `/c/:sessionId` (transcript view) — the URL is the only durable handle,
  no `localStorage`
- `src/components/` — presentational transcript rendering
