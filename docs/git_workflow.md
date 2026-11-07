# Git Workflow — mtk-gui

Simplified GitFlow for multi TRAE SOLO parallel development.

## Branch Structure

```
develop              integration + release branch (the only long-lived branch)
 └── feature/*       one feature branch per TRAE SOLO session
```

`main` is **retired**. It still exists on GitHub, more than 500 commits behind, and nothing is merged into it.
Do not push to it, do not merge into it, do not tag on it. The Bitbucket mirror declares `develop` as its main
branch for exactly this reason: showing the stale `main` would hand readers months-old code.

## Branch Rules & Protection Notes

### develop — Integration and Release Branch
- The default working base for all development, and the branch every release tag is cut on.
- `feature/*` branches merge here for **cross-module integration test**.
- Merge features into `develop` only after the feature's own smoke test passes.
- On GitHub, protect it: block force pushes and deletions. Direct commits from the owner are expected; a
  release is a commit on `develop` plus an annotated tag, not a merge into another branch.

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

### Release: tag `develop`, publish, then mirror
```bash
# 1. version bump + history entry, in one commit
git commit -m "Release v1.0.0.1"
git tag -a v1.0.0.1 -m "Release v1.0.0.1"

# 2. publish to GitHub - the branch that carries the tag, nothing else
git push origin develop --follow-tags
```

The mirror push to Bitbucket, the permission model and the verification steps are documented in the owner's
runbook, which is **deliberately not in this repository** — a file here is every colleague's file once the mirror
exists. Two refs reach the mirror: `develop` and the release tag. `git push --mirror` is never used.

`__version__` in `mtkgui/__init__.py` is the single source of truth, and the tag must be byte-identical to it.

Daily work is unaffected by any of this: branch, commit and push to `develop` exactly as in the sections above.
A release adds two things only — a version bump with its history entry, and one annotated tag. No release, no tag:
work keeps flowing to `develop` as before.

The owner's runbook prescribes nothing about development or about ordinary pushes, and it is not needed to
work on this repository: build, commit and push without ever reading it.

## Sync Between Machines (Mac dev ↔ Windows build)

- Modifying side commits and pushes; the other side pulls.
- After pulling on Windows, re-run the build script to regenerate the exe.
- Only one side modifies the same file to avoid conflicts.
