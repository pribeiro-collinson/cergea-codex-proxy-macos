# v5.1.4

- Make the installer independent of the current working directory by resolving paths from `install.sh` itself.
- Use `DISTRIBUTION-MANIFEST.txt` as the single source of truth for copying package-owned files.
- Copy the release's own `install.sh`, manifest, version, licenses, and documentation into `CODEX_HOME`, ensuring subsequent installs and tests use the same release.
- Canonicalize `CODEX_HOME` and bundle paths and skip identical files before invoking `cp`, including direct extraction into `~/.codex`.
- Reject missing or path-traversing manifest entries; preserve user configuration files not listed in the manifest.
- Add regression coverage for fresh installs, external extraction directories, direct-in-`~/.codex` execution, repeat runs, and installer self-update.
