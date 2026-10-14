# Changelog — v5.1.1

- Hardened the Cergea preflight: the bearer token is supplied to curl through a mode-600 temporary config file rather than a command-line header argument; the file is removed on success or failure.
- Added synthetic checks for private temporary credential handling and clean-new-user copy-only installs.
- Added an end-to-end local HTTP fixture that verifies curl parses the generated preflight config and transmits the expected authorization header and JSON body, without contacting Cergea.
- Kept Ponytail optional and separately documented; it complements simpler code generation but does not compact conversation history.
- Bumped the distribution version to 5.1.1. No user-specific Codex config, API key, or machine-specific path is included.
