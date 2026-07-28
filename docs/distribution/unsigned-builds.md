# Unsigned Local Builds

YagCode release scripts are configured for unsigned local artifacts:

- macOS desktop: `forceCodeSigning: false`, `mac.identity: null`.
- Windows desktop: `win.signAndEditExecutable: false`, `signtoolOptions: null`, `azureSignOptions: null`.
- Electron auto-update metadata is rejected by `scripts/build-desktop.mjs`.

These settings are intentional for local validation. A public production release should add reviewed signing and notarization without changing the deterministic manifest and smoke gates.
