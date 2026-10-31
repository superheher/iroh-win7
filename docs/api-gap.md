# The Windows 7 API gap, measured

This document answers one question: **why do the official `iroh` Python wheels
fail to load on Windows 7, and what exactly is missing?** Everything below was
verified against a stock Windows 7 SP1 x64 installation (PE import/export
analysis plus live `ctypes` probes), not inferred from version folklore.

## Summary

The native core of the [PyPI `iroh`](https://pypi.org/project/iroh/) package
(`iroh_ffi.dll`, built from [n0-computer/iroh-ffi](https://github.com/n0-computer/iroh-ffi))
statically imports a handful of Win8+/Win10+ APIs. Measured against the **real
export tables** of a stock Windows 7 SP1 x64 system, the entire gap is
**4 items / 6 functions**:

| # | Missing | Imported from | Windows 7 equivalent |
|---|---------|---------------|----------------------|
| 1 | `WaitOnAddress`, `WakeByAddressSingle`, `WakeByAddressAll` | `api-ms-win-core-synch-l1-2-0.dll` | keyed events (`NtWaitForKeyedEvent` / `NtReleaseKeyedEvent`) or a lock + condition-variable table |
| 2 | `GetSystemTimePreciseAsFileTime` | `kernel32.dll` | `GetSystemTimeAsFileTime` (+ optional QPC interpolation) |
| 3 | `ProcessPrng` | `bcryptprimitives.dll` | `SystemFunction036` (`RtlGenRandom`) |
| 4 | `CoIncrementMTAUsage` | `combase.dll` (the module does not exist on Win7 at all) | `CoInitializeEx(NULL, COINIT_MULTITHREADED)` on a helper thread |

Everything else among the ~120 static imports resolves on stock Windows 7,
including two pleasant surprises:

- `kernel32!FlushProcessWriteBuffers` **exists** on Win7 SP1 x64 (exported as a
  forwarder to `NTDLL.NtFlushProcessWriteBuffers`), despite being a Win8+ API
  by the documentation;
- `advapi32!SystemFunction036` (`RtlGenRandom`) is present — and the upstream
  DLL already imports it alongside `ProcessPrng`.

## Emulation precedents

None of the replacements above are exotic; each is the standard, battle-tested
mapping used by several independent projects:

- **[YY-Thunks](https://github.com/Chuyu-Team/YY-Thunks)** (MIT, active) — a
  link-time thunk library whose documented coverage includes exactly these
  functions: `ProcessPrng` → `RtlGenRandom`, the futex trio → keyed events,
  `CoIncrementMTAUsage` → `CoInitializeEx` on another thread. Its
  [issue #163](https://github.com/Chuyu-Team/YY-Thunks/issues/163) is the
  closest public precedent: a Rust-built binary failing on Win7 with
  `CoIncrementMTAUsage`, fixed by linking the thunks.
- **Rust itself** — the official tier-3 target
  [`x86_64-win7-windows-msvc`](https://github.com/rust-lang/rust/issues/128218)
  makes std use `RtlGenRandom`, keyed events and a
  `GetSystemTimeAsFileTime` fallback; the `getrandom` crate used `RtlGenRandom`
  on Windows before the Win10 baseline move.
- **[cristianadam/api-ms-win-core-synch-Win7](https://github.com/cristianadam/api-ms-win-core-synch-Win7)**
  — a ready `WaitOnAddress` implementation for Win7 (lock + condition-variable
  table), used to run Qt Creator MinGW builds on Win7.
- **Wine** — the 6.0-era `ntdll` source shows a complete `WaitOnAddress`
  implementation on Win32 primitives (keyed events as the no-futex fallback).

## Loader behaviour worth knowing

- **api-ms-\* names are ordinary files on Windows 7.** When a contract is not
  in the OS API set schema, the loader resolves the name through the standard
  DLL search. Microsoft ships physical `api-ms-win-*.dll` forwarder files for
  down-level systems with the
  [Universal CRT redistribution](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment),
  and the Qt/Python ecosystems use the same drop-in pattern. (This project does
  not even need api-ms drop-ins: YY-Thunks removes those imports at link time.)
- **Forwarders resolve lazily.** A DLL whose exports are forwarder strings can
  `LoadLibrary` successfully while individual `GetProcAddress` calls fail with
  "function not found". Verify exports, never trust a successful load alone —
  the api-ms-win-core-synch shim shipped with some community Python builds
  loads fine and then fails every call, because its forwarders point at
  `kernel32!WaitOnAddress`, which stock Win7 does not have.
- **Import-name patches must be length-preserving.** Rewriting a descriptor's
  module-name string in place is safe only if the new name is not longer than
  the old one (shorter is padded with NULs). A longer replacement resizes the
  file, shifts every subsequent RVA, and corrupts the image — the classic
  symptom is every import name reading one character off
  (`GetModuleFileNameW` → `etModuleFileNameW`). [`tools/patch_imports.py`](../tools/patch_imports.py)
  enforces the equal-length rule.

## Methodology

1. Dump the DLL's import table (pure-stdlib PE parser; `tools/win7gap.py`
   contains the same logic).
2. Copy the **real** DLLs from the target Windows 7 SP1 x64 machine
   (`kernel32.dll`, `kernelbase.dll`, `bcryptprimitives.dll`, ...) and parse
   their export tables; flag every import whose module is missing or whose
   function has no export (`tools/win7gap.py <dll> <dir-of-win7-dlls>`).
3. Probe every questionable API live on that machine with
   `ctypes.WinDLL(...).func` (load + attribute access; attribute access
   matters because of lazy forwarders).
4. Attempt the real load and walk the failure ladder until it passes.

On the unpatched wheel, step 4 fails with the generic loader error
("module ... or one of its dependencies"). After the
[build recipe](../build.py) (YY-Thunks relink + one import retarget), the
ladder passes end to end: import → endpoint bind through a relay → serve → a
real SSH session proxied through the node.
