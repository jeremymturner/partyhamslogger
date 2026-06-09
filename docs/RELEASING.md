# Releasing PartyHams Logger

This is the repeatable flow for cutting a tagged GitHub release with downloadable
artifacts and checksums. It builds on the PyInstaller packaging described in
[docs/PACKAGING.md](PACKAGING.md) — read that first for per-platform build
details.

The whole flow is driven by [`scripts/release.sh`](../scripts/release.sh), wrapped
by `make release`.

## Prerequisites

- **The dev venv + packaging deps:** `make setup` (the `make package*` targets
  pull in PyInstaller on first use automatically).
- **GitHub CLI:** [`gh`](https://cli.github.com/) installed and authenticated:

  ```bash
  gh auth login        # one-time; pick the repo's host + your account
  gh auth status       # confirm you're logged in
  ```

- **A clean git tree** on the commit you want to release (the script refuses to
  run otherwise).
- **Per-platform build hosts.** PyInstaller can't cross-compile, so each OS's
  artifact is built on that OS (see the matrix in
  [docs/PACKAGING.md](PACKAGING.md)). Run the release script once per platform
  into the *same* tag — the first run creates the release, later runs upload into
  it.

## Cut a release

1. **Bump the version** in both places so they agree (the script warns on a
   mismatch):
   - `project.version` in `pyproject.toml`
   - `__version__` in `src/partyhams/__init__.py`

   Commit that bump.

2. **Dry-run first** to see exactly what will happen (no tag, no network):

   ```bash
   make release VERSION=v0.1.0 RELEASE_ARGS=--dry-run
   # or directly:
   scripts/release.sh v0.1.0 --dry-run
   ```

3. **Cut it for real** on each target OS:

   ```bash
   make release VERSION=v0.1.0
   # or directly:
   scripts/release.sh v0.1.0
   ```

   On macOS you can build the universal2 `.app` instead of a single-arch one:

   ```bash
   make release VERSION=v0.1.0 RELEASE_ARGS="--target package-mac-universal"
   ```

   Other targets: `--target package-appimage`, `--target package-deb`,
   `--target package-rpm` (Linux).

4. **Push the tag** (the script creates the annotated tag locally but doesn't
   push it for you):

   ```bash
   git push origin v0.1.0
   ```

### What the script does

1. Validates the tag looks like `vMAJOR.MINOR.PATCH` and matches
   `pyproject.toml` / `__version__` (warns, doesn't block, on mismatch).
2. Refuses to run if the git tree is dirty.
3. Creates an annotated tag `vX.Y.Z` on `HEAD` if it doesn't already exist.
4. Runs `make <target>` (default `package`) to build into `dist/`.
5. Writes `dist/SHA256SUMS` and `dist/MD5SUMS`.
6. Runs `gh release create <tag> <artifacts> dist/SHA256SUMS dist/MD5SUMS
   --title --generate-notes`, or `gh release upload <tag> ... --clobber` if the
   release already exists.

It guards each external tool (`git`, `make`, `gh`) with a clear error if it's
missing, and `--dry-run` prints the tag/`gh` commands instead of executing them.

## Artifacts per platform

These are the top-level `dist/` entries each `make package*` target produces and
the release uploads (see [docs/PACKAGING.md](PACKAGING.md) for the full table):

| Platform              | Target                       | Artifact in `dist/` |
| --------------------- | ---------------------------- | ------------------- |
| Windows               | `package`                    | `PartyHamsLogger/` (contains `PartyHamsLogger.exe`) |
| macOS (single-arch)   | `package`                    | `PartyHamsLogger.app` |
| macOS (universal2)    | `package-mac-universal`      | `PartyHamsLogger.app` (Intel + Apple Silicon) |
| Linux                 | `package`                    | `PartyHamsLogger/` (contains the binary) |
| Linux AppImage        | `package-appimage`           | `PartyHamsLogger-x86_64.AppImage` |
| Linux `.deb`          | `package-deb`                | `partyhams-logger_*.deb` |
| Linux `.rpm`          | `package-rpm`                | `partyhams-logger-*.rpm` |

## Checksums

`dist/SHA256SUMS` and `dist/MD5SUMS` are produced over every uploaded artifact.
For directory artifacts (the `.app` bundle and the per-OS folder) the script
recurses and hashes every contained file, so the checksum file lists each file
individually. Both files are attached to the release. To verify a download:

```bash
# from the directory holding the downloaded artifacts + the SUMS files
sha256sum -c SHA256SUMS      # Linux
shasum -a 256 -c SHA256SUMS  # macOS
md5sum -c MD5SUMS            # Linux  (macOS: md5 -r)
```

## CI matrix note

Because there's no cross-compilation, the natural automation is a GitHub Actions
matrix — one runner per target OS/arch (`windows-latest`, `macos-13` Intel,
`macos-14` Apple Silicon, `ubuntu-latest`) — each running the matching
`make release VERSION=$TAG RELEASE_ARGS="--target <t>"` (or just the build +
`gh release upload`) into the tag that triggered the workflow. The first job to
run `gh release create` makes the release; the rest upload into it. See the "CI
suggestion" section of [docs/PACKAGING.md](PACKAGING.md).
