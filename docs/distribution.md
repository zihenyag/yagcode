# Distribution

YagCode is distributed through GitHub Release after platform build and smoke gates pass. Desktop and CLI products are separate.

## Desktop Assets

- macOS 13+ Apple Silicon: `yagcode-mac-arm64.dmg`
- Windows 10/11 x64: `yagcode-win-x64.exe`

Each platform has one required desktop download. The installed app may contain Electron, renderer assets, Python sidecar, SQLite support files, and runtime notices.

## CLI Assets

- macOS 13+ Apple Silicon: `yagcode-cli-mac-arm64.tar.gz`
- Windows 10/11 x64: `yagcode-cli-win-x64.zip`

The CLI is independent from the desktop app. Running `yagcode` starts the terminal workbench; `yagcode health` and `yagcode version` are smoke commands.

## Manifests

Each product/platform asset has a single-platform manifest under `dist/manifests/`. The release job merges exactly four manifests into `dist/release/release-manifest.json` after recalculating real asset bytes.

## Current Evidence

Current local evidence covers macOS ARM64 desktop and CLI packaging. Windows desktop and CLI package smoke still need a Windows runner for latest-source verification.

## Unsigned Artifacts

Build artifacts are unsigned unless a future release step adds reviewed signing. Users may see Gatekeeper or SmartScreen prompts. See `docs/distribution/unsigned-builds.md`.
