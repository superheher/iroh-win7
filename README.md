# iroh-win7

Run the official [`iroh`](https://pypi.org/project/iroh/) Python wheels on
Windows 7 SP1 x64 — with **zero changes to upstream source code**.

The upstream wheels are built from
[n0-computer/iroh-ffi](https://github.com/n0-computer/iroh-ffi) and target
modern Windows: the native core `iroh_ffi.dll` fails to load on Windows 7
because it statically imports a handful of Win8+/Win10+ APIs. Measured against
a stock Windows 7 SP1 x64 system, the entire gap is **4 items / 6 functions**,
and every one of them has a well-understood Windows 7 equivalent — see
[docs/api-gap.md](docs/api-gap.md) for the full analysis.

This repository provides:

- **`build.py`** — a reproducible build script: clones upstream at a chosen
  tag, links [YY-Thunks](https://github.com/Chuyu-Team/YY-Thunks) (MIT), fixes
  one import-table module name in the produced wheel, and emits a
  Win7-compatible wheel;
- **`tools/win7gap.py`** — verifies any DLL's imports against the real export
  tables of a target Windows 7 system (pure stdlib PE parser);
- **`tools/patch_imports.py`** — length-preserving import-table module-name
  retargeting, with safety rails;
- **`examples/`** — a serve node (iroh → TCP forwarder), a windowless
  scheduled-task launcher, and a Windows 7 Task Scheduler XML;
- **`docs/api-gap.md`** — the gap analysis itself: what is missing, why, and
  the precedents for every replacement.

## How it works

1. **Link-time thunks.** The upstream `iroh-ffi` crate is rebuilt from the
   same version tag (source untouched) with
   `RUSTFLAGS="-C link-arg=YY_Thunks_for_Win7.obj"`. The thunk library absorbs
   the missing imports at link time:
   - `ProcessPrng` (Win10+) → `RtlGenRandom` / `SystemFunction036`
   - `WaitOnAddress` / `WakeByAddressSingle` / `WakeByAddressAll` (Win8+) →
     keyed events
   - `CoIncrementMTAUsage` (Win8+) → `CoInitializeEx(COINIT_MULTITHREADED)`
     on a helper thread
2. **One import retarget.** Depending on the toolchain, the rebuilt DLL may
   still import from `combase.dll` (a Win8+ module), although the function it
   needs (`CoTaskMemAlloc`) exists in `ole32.dll` on every Windows version.
   The build script rewrites that module-name string in the wheel — a
   length-preserving, NUL-padded in-place fix.
3. Nothing else changes. The iroh source, its protocol behaviour and the pure
   Python layer are stock upstream; only the missing *OS* APIs are emulated.
   It is the Wine principle in reverse: run the unmodified application by
   emulating what the OS lacks.

Verified end to end on a stock Windows 7 SP1 x64 machine with an x64 CPython:
import → endpoint bind through a self-hosted relay → serve → a real SSH
session proxied through the node, with a stable endpoint id across restarts.

## Building a wheel

On a Windows 10/11 build machine (not on the Win7 target):

```
python -m pip install maturin uniffi-bindgen     # plus rustup stable-msvc + VS Build Tools
git clone https://github.com/superheher/iroh-win7
cd iroh-win7
python build.py                                  # iroh-ffi v1.1.0, YY-Thunks v1.2.3
python build.py --tag v1.2.0                     # any other upstream tag
```

Result: `dist/iroh-<version>-win7-yythunks-py3-none-win_amd64.whl`.

The wheel is `py3-none` (ABI-independent): the Python layer is pure
`ctypes`-based code, so any x64 CPython that runs on Windows 7 works on the
target side.

## Deploying (short version)

See [examples/README.md](examples/README.md) for the full walk-through.

```
python -m zipfile -e dist\iroh-<v>-win7-yythunks-py3-none-win_amd64.whl C:\iroh7\site\
set PYTHONPATH=C:\iroh7\site
python examples\serve_node.py serve 127.0.0.1 22    # endpoint id on first run
```

For a background node on boot, use `examples/serve_launcher.py` with the
scheduled-task XML from `examples/win7-task.xml`.

## Versioning and maintenance

- The recipe is pinned per upstream tag (`--tag`); rebuild for each new
  iroh-ffi release. The import surface can shift between releases — re-run
  `tools/win7gap.py` against the fresh DLL and adjust the retarget table in
  `build.py` if the analysis shows new gaps.
- Current verified combination: iroh-ffi **v1.1.0** (PyPI `iroh` 1.1.0),
  YY-Thunks **v1.2.3**, rustc 1.99 stable-msvc, Windows 7 SP1 x64.

## Notes

- Unofficial project; not affiliated with n0-computer. `iroh` and
  `iroh-ffi` are MIT OR Apache-2.0 — this repository ships build tooling and
  documentation, and links (never modifies) upstream sources.
- YY-Thunks is MIT, Copyright Chuyu-Team; see
  https://github.com/Chuyu-Team/YY-Thunks.
- This repository's own code is MIT — see [LICENSE](LICENSE).
- The Windows 7 machine must be real hardware/VM with SP1 x64; the wheel does
  not add 32-bit support, nor does it make any other upstream wheel
  Win7-compatible automatically.
