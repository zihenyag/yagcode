# Known Limitations

- macOS Intel, Linux desktop packages, Homebrew, PyPI, npm package-manager distribution, and container images are outside the current release scope.
- Desktop artifacts are unsigned in local builds.
- Windows latest-source desktop and CLI native smoke evidence is still pending.
- GitHub Release, GitHub Pages, and platform package assets are produced by GitHub Actions after the relevant branch or tag is pushed.
- The local OS user account remains the system boundary; YagCode does not protect one local user from another process running as the same user.
- Real Provider behavior can fail because of quota, endpoint drift, transient network errors, or model output shape changes. Mock Provider tests remain the offline baseline for deterministic harness mechanisms.
