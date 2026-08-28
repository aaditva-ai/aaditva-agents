---
sessionId: session-260824-183332-1y0s
---

# Diagnosis

### What's actually happening

All five specialist Dockerfiles (`agents/{brand_strategist,copywriter,designer,critic,project_manager}/Dockerfile`) share this exact pattern:

```dockerfile
COPY pyproject.toml .
RUN uv sync --no-install-project --no-dev
COPY . .
...
CMD ["uv", "run", "python", "agent.py"]
```

**Answering the questions directly:**

1. **"Are we missing `uv.lock` somewhere?"** — No, `uv.lock` *is* checked into every agent directory (e.g. `agents/designer/uv.lock` is committed, not gitignored — only `.venv/` is ignored). The bug is *ordering*: the Dockerfile only `COPY`s `pyproject.toml` before running `uv sync`, so the lock file isn't present yet at that point. `uv.lock` only enters the image later via the blanket `COPY . .`. So the venv built during `docker build` is synced **without** the pinned lock (uv resolves ad hoc / against whatever cache it has), and the *real* committed lock arrives in the image afterward but is never used to (re)sync at build time.
2. **"Is this a matter of rebuilding the venv?"** — Yes. Because the venv baked into the image doesn't provably match the repo's `uv.lock`, `uv run` (used in `CMD`) does its normal drift check at container startup and finds the environment doesn't satisfy the lock/project → it performs a real `uv sync` **inside the running container**, reinstalling dependencies. That's the ~4 minute stall Cloud Logging showed on `designer-00016-gpc`, which blew past the Cloud Run startup health-check timeout.
3. **"Does it make sense to check in the venv?"** — No. `.venv` is platform/arch-specific (glibc build vs Cloud Run's container base, Python ABI, etc.), huge, and fragile to commit — this is explicitly why it's gitignored. The correct fix is to make the *build* fully materialize the final venv against the committed lock, and make the *runtime* command never touch/re-sync it.
4. **"If this is in the Dockerfile, is it happening at deploy stage?"** — Partially. `gcloud run deploy --source=.` triggers Cloud Build to run this Dockerfile, so the (currently mis-ordered) `uv sync` does happen at build/deploy time. But that build-time sync doesn't produce the environment matching the real `uv.lock`. The second, *real* full sync — the expensive one — is deferred and happens implicitly at **container cold start / runtime**, exactly as suspected ("That does sound terrible!" — yes).

`gradio-ui/Dockerfile` already copies `uv.lock*` before syncing (better), but still lacks a build-time project-install pass and still uses plain `uv run` at `CMD`, so it's not fully immune either.

### Root cause summary
Dockerfile copies dependency lock file too late relative to the sync step, and never re-syncs after the app code (including the real lock) lands — pushing the authoritative sync to container startup instead of image build.

# Technical Design

### Current Implementation
- `agents/{brand_strategist,copywriter,designer,critic,project_manager}/Dockerfile` — identical pattern: `COPY pyproject.toml .` → `uv sync --no-install-project --no-dev` → `COPY . .` → `CMD ["uv", "run", "python", "agent.py"]`.
- `gradio-ui/Dockerfile` — copies `pyproject.toml uv.lock* ./` before syncing (better), but still only does one `--no-install-project` sync and plain `uv run` at `CMD`.
- Each agent directory is an independent `uv` project (own `pyproject.toml` + committed `uv.lock`, no `[tool.uv.workspace]` at the repo root), so the fix is purely per-Dockerfile — no cross-project lock coordination needed.

### Key Decisions
1. **Copy `uv.lock` alongside `pyproject.toml` before the first `uv sync`, and add `--frozen`.** `--frozen` makes `uv sync` fail loudly if the lock is out of date instead of silently re-resolving — this guarantees the build-time sync is byte-for-byte the committed lock, not an ad hoc resolution.
2. **Add a second `RUN uv sync --frozen --no-dev` after `COPY . .`.** The first sync installs only dependencies (`--no-install-project`, cacheable layer); this second pass installs the local project package itself (editable install) once the app code is present — completely at build time, never at runtime.
3. **Change `CMD` to `uv run --no-sync python agent.py`.** `--no-sync` tells `uv run` to skip its environment-drift check entirely and just execute — since the venv was already fully materialized in steps 1–2, there is nothing left to sync, and cold start becomes a plain process launch.
4. **Do not check in `.venv`.** Rejected — platform/ABI-specific, huge, brittle; the three changes above make it unnecessary since the image itself now carries a build-verified venv.

### Proposed Changes
Apply the same 3-part fix to all 5 specialist Dockerfiles and `gradio-ui/Dockerfile`:
```dockerfile
# Copy pyproject.toml AND uv.lock first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies only, pinned exactly to the committed lock
RUN uv sync --frozen --no-install-project --no-dev

# Copy application code
COPY . .

# Install the project itself against the same frozen lock (build time, not runtime)
RUN uv sync --frozen --no-dev

...

# Run without re-checking/syncing the venv - it's already fully materialized
CMD ["uv", "run", "--no-sync", "python", "agent.py"]
```

### File Structure
- `agents/brand_strategist/Dockerfile` — apply fix.
- `agents/copywriter/Dockerfile` — apply fix.
- `agents/designer/Dockerfile` — apply fix (the one observed stalling on `designer-00016-gpc`).
- `agents/critic/Dockerfile` — apply fix.
- `agents/project_manager/Dockerfile` — apply fix.
- `gradio-ui/Dockerfile` — apply the second-sync + `--no-sync` CMD parts (lock copy already present).

### Risks
- `--frozen` will hard-fail the build if any agent's `uv.lock` is currently stale relative to its `pyproject.toml` — this is desirable (surfaces drift at build time instead of masking it), but means a currently-passing build could start failing if a lock is out of sync; will verify each lock is current before/while applying the fix.
- Slightly larger build context isn't a concern (`uv.lock` is small); no behavior change to the actual dependency versions installed, only *when* the sync happens.

# Testing

### Validation Approach
- For each modified Dockerfile, confirm `uv sync --frozen ...` succeeds against the existing committed `uv.lock` (no drift) via a local `docker build`.
- Redeploy the Designer specifically (using the already-existing `deploy/deploy_all_specialists.py --agent designer` flag) since it's the one with reproduced evidence of the slow-cold-start failure, and confirm the fix via Cloud Logging.

### Key Scenarios
- Local `docker build` of `agents/designer` (and at least one other specialist, e.g. `brand_strategist`) completes without `--frozen` lock-mismatch errors.
- After redeploying `designer` to Cloud Run, Cloud Logging for the new revision shows no `uv sync` / venv-installation activity during container startup, and the revision reaches Ready without a health-check timeout on the first attempt.
- Agent card endpoint (`/.well-known/agent-card.json`) still returns 200 and the designer still successfully completes a real image-generation request (repeat of the prior smoke test) to confirm the runtime behavior is unaffected.

### Edge Cases
- If any agent's `uv.lock` turns out to be stale vs. its `pyproject.toml`, `--frozen` will fail the build — will re-run `uv lock` for that agent to refresh it before re-attempting.
- Verify `gradio-ui`'s build still succeeds with the added second sync + `--no-sync` CMD, since it wasn't part of the originally observed failure but shares the same runtime-resync risk.

# Delivery Steps

### ✓ Step 1: Fix build/runtime uv sync ordering in the 5 specialist Dockerfiles
All 5 specialist agent Dockerfiles fully materialize their venv at build time and never re-sync at container startup.
- Update `agents/brand_strategist/Dockerfile`, `agents/copywriter/Dockerfile`, `agents/designer/Dockerfile`, `agents/critic/Dockerfile`, `agents/project_manager/Dockerfile`.
- Change `COPY pyproject.toml .` to `COPY pyproject.toml uv.lock ./` before the first sync.
- Add `--frozen` to the existing `uv sync --no-install-project --no-dev` so it's pinned exactly to the committed lock instead of resolving ad hoc.
- Add a second `RUN uv sync --frozen --no-dev` after `COPY . .` to install the local project package at build time.
- Change `CMD ["uv", "run", "python", "agent.py"]` to `CMD ["uv", "run", "--no-sync", "python", "agent.py"]` so startup never touches the venv.

### ✓ Step 2: Apply the same fix to gradio-ui's Dockerfile
`gradio-ui/Dockerfile` follows the same build-time-complete-sync / no-sync-at-runtime pattern as the specialists.
- Add `--frozen` to the existing `uv sync --no-install-project --no-dev` (lock copy is already present via `uv.lock*`).
- Add a second `RUN uv sync --frozen --no-dev` after `COPY . .` to install the local project package.
- Change `CMD ["uv", "run", "python", "app.py"]` to `CMD ["uv", "run", "--no-sync", "python", "app.py"]`.

### ✓ Step 3: Validate locally and redeploy the Designer to confirm the cold-start fix
Docker builds succeed with `--frozen`, and the redeployed Designer starts without a runtime venv resync.
- Run a local `docker build` for `agents/designer` and `agents/brand_strategist` to confirm `--frozen` passes against the current committed `uv.lock` files (refresh any stale lock with `uv lock` if a build fails).
- Redeploy only the Designer via `uv run python deploy/deploy_all_specialists.py --agent designer`.
- Check Cloud Logging for the new revision's startup logs to confirm no `uv sync`/venv-rebuild activity occurs during cold start and the revision becomes Ready on the first health check.
- Re-run the agent-card check and a real image-generation smoke prompt against the redeployed Designer to confirm functional behavior is unchanged.