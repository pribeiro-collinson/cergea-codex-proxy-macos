# v5.2.13

- Remove accidentally packaged Python bytecode (`__pycache__` / `.pyc`) that caused the distribution-manifest regression test to fail.
- Preserve executable permissions in the release ZIP so `install.sh` can be run directly after extraction on macOS.
- No runtime proxy-routing behavior changes in this release.
