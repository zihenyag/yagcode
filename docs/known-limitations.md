# Known Limitations

- macOS Intel, Linux desktop packages, Homebrew, PyPI, npm package-manager distribution, and container images are outside this release scope.
- Desktop artifacts are unsigned in the local build.
- Windows latest-source desktop and CLI native smoke evidence is still pending.
- GitHub Release, GitHub Pages public URL, and final remote CI pass evidence require user authorization for push/dispatch.
- The local OS user account remains the system boundary; YagCode does not protect one local user from another process running as the same user.
- Real Provider behavior can fail because of quota, endpoint drift, transient network errors, or model output shape changes. Mock Provider tests remain the offline baseline for deterministic harness mechanisms.
- `product-notes.md` must be written by the maintainer. AI assistance should be limited to outline checks or polishing text the maintainer already wrote.
