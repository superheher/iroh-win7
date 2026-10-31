# Building a Windows 7 wheel

## How it works

1. **Link-time thunks.** The upstream `iroh-ffi` crate is rebuilt from the
   same version tag (source untouched) with
   `RUSTFLAGS="-C link-arg=YY_Thunks_for_Win7.obj"`. The
   [YY-Thunks](https://github.com/Chuyu-Team/YY-Thunks) object absorbs the
   missing imports at link time:
   - `ProcessPrng` (Win10+) → `RtlGenRandom` / `SystemFunction036`
   - `WaitOnAddress` / `WakeByAddressSingle` / `WakeByAddressAll` (Win8+) →
     keyed events
   - `CoIncrementMTAUsage` (Win8+) → `CoInitializeEx(COINIT_MULTITHREADED)`
     on a helper thread
2. **One import retarget.** Depending on the toolchain, the rebuilt DLL may
   still import from `combase.dll` (a Win8+ module), although the function it
   needs (`CoTaskMemAlloc`) exists in `ole32.dll` on every Windows version.
   The build script rewrites that module-name string inside the wheel — a
   length-preserving, NUL-padded in-place fix
   ([tools/patch_imports.py](../tools/patch_imports.py)).
3. Nothing else changes. The iroh source, its protocol behaviour and the pure
   Python layer are stock upstream; only the missing *OS* APIs are emulated.
   It is the Wine principle in reverse: run the unmodified application by
   emulating what the OS lacks.

## Prerequisites (build host)

Build on Windows 10/11, not on the Win7 target:

- rustup with the stable-msvc toolchain; rustc must be at or above the
  crate's declared `rust-version` (iroh-ffi v1.1.0 declares 1.91)
- Visual Studio Build Tools (`link.exe`) + Windows SDK
- the python running `build.py` needs maturin and uniffi-bindgen:
  `python -m pip install maturin uniffi-bindgen`

## Commands

```
git clone https://github.com/superheher/iroh-win7
cd iroh-win7
python build.py                                  # iroh-ffi v1.1.0, YY-Thunks v1.2.3
python build.py --tag v1.2.0 --yythunks-tag v1.2.3   # any other upstream tag
```

Output: `dist/iroh-<version>-win7-yythunks-py3-none-win_amd64.whl`. The wheel
is `py3-none` (ABI-independent): the Python layer is pure `ctypes`-based code,
so any x64 CPython that runs on Windows 7 works on the target side.

## Verification

On the target machine (or against DLLs copied from it):

```
python -I tools/win7gap.py <wheel-extract>\iroh\iroh_ffi.dll <dir-of-win7-dlls>
```

Expect `MISSING FUNCTION: 0`. The final gate is a live ladder on the machine
itself: `import iroh` → endpoint bind through a relay → serve → a real SSH
session proxied through the node, with the endpoint id stable across restarts.

## Per-release maintenance

- Rebuild for each upstream tag (`--tag`); the import surface can shift
  between releases.
- Re-run `tools/win7gap.py` against the fresh DLL. New gaps are handled in
  this order: extend the `RETARGETS` table in `build.py` only for functions
  that exist in older Windows modules; everything genuinely missing belongs
  in YY-Thunks coverage (or a purpose-built shim, if upstream refuses it).
- Verified combination: iroh-ffi **v1.1.0** (PyPI `iroh` 1.1.0), YY-Thunks
  **v1.2.3**, rustc 1.99.1 stable-msvc, stock Windows 7 SP1 x64.

## Notes

- Unofficial project; not affiliated with n0-computer. Upstream `iroh` /
  `iroh-ffi` are MIT OR Apache-2.0 — this repository ships build tooling and
  documentation, and links (never modifies) upstream sources.
- This repository's own code is MIT — see [LICENSE](../LICENSE).
- Target limits: x64 only, real Windows 7 SP1; the wheel does not add 32-bit
  support and does not make other upstream wheels Win7-compatible
  automatically.
