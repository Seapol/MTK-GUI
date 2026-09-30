# Git Workflow — mtk-gui

Simplified GitFlow for multi TRAE SOLO parallel development.

## Branch Structure

```
main                 protected release branch (tracks origin/main)
 └── develop         integration branch (created from main)
      └── feature/*  one feature branch per TRAE SOLO session
```

## Branch Rules & Protection Notes

### main — Release Branch (Protected)
- **No direct commit allowed.** Never commit to `main` directly.
- Only updated by merging `develop` **after integration test passes**.
- Every commit on `main` should be releasable / buildable.
- On GitHub, enable branch protection for `main`:
  *Settings → Branches → Add branch protection rule → Branch name pattern: `main`*
  - Require a pull request before merging (or at minimum: block force push, block direct push)
  - Do not allow force pushes / deletions

### develop — Integration Branch
- Created from `main`; the default working base for all development.
- `feature/*` branches merge here for **cross-module integration test**.
- Merge features into `develop` only after the feature's own smoke test passes.
- Run the full integration test (GUI startup + smoke test) before merging `develop` → `main`.

### feature/* — Feature Branches
- **One feature branch per TRAE SOLO session.** Never share a branch across sessions.
- Branch from the latest `develop`.
- Name by topic, e.g. `feature/console-quick-cmds`, `fix/waveform-redraw`.
- Keep the branch scoped to one feature or one bugfix; merge back into `develop` when done, then delete the branch.

## Commit Convention

Conventional Commits (English). Template configured via `git config commit.template .gitmessage`.

```
<type>(<scope>): <subject>
```

Types: `feat` / `fix` / `docs` / `style` / `refactor` / `perf` / `test` / `chore`

See `.gitmessage` at repository root for the full rules and examples.

## Command Reference

### Start a new feature (per TRAE SOLO session)
```bash
git checkout develop
git pull origin develop
git checkout -b feature/<topic>
```

### Merge a finished feature into develop
```bash
git checkout develop
git merge --no-ff feature/<topic>
git push origin develop
git branch -d feature/<topic>
```

### Release: merge develop into main (after integration test passes)
```bash
git checkout main
git merge --no-ff develop
git tag -a v<version> -m "Release v<version>"
git push origin main --tags
```

## Sync Between Machines (Mac dev ↔ Windows build)

- Modifying side commits and pushes; the other side pulls.
- After pulling on Windows, re-run the build script to regenerate the exe.
- Only one side modifies the same file to avoid conflicts.
