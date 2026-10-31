# iroh-win7

Builds Windows 7 x64-compatible wheels of the official
[iroh](https://pypi.org/project/iroh/) package with zero upstream source
changes: the missing Win8+/Win10+ system APIs are emulated at link time plus
one import-table fix. Verified end to end on stock Windows 7 SP1 x64
(iroh 1.1.0, YY-Thunks 1.2.3, rustc stable-msvc).

- [docs/api-gap.md](docs/api-gap.md) — what exactly is missing on Windows 7, and how it was measured
- [docs/build.md](docs/build.md) — how the build works, prerequisites, verification, per-release maintenance
- [examples/README.md](examples/README.md) — deploying the wheel, the serve node and the boot task, troubleshooting
- [tools/win7gap.py](tools/win7gap.py) — verify any DLL's imports against real Windows 7 export tables
- [tools/patch_imports.py](tools/patch_imports.py) — length-preserving import-table module retargeting
- [LICENSE](LICENSE) — MIT
