#!/usr/bin/env python3
"""Build a Windows 7 x64-compatible iroh wheel from unmodified upstream sources.

Steps
  1. clone https://github.com/n0-computer/iroh-ffi at --tag (default v1.1.0)
  2. download the YY-Thunks objects release and pick objs/x64/YY_Thunks_for_Win7.obj
  3. run `python -m maturin build --release` with
     RUSTFLAGS="-C link-arg=<YY_Thunks obj>"  (absorbs the Win8+/Win10+ imports:
     ProcessPrng, the WaitOnAddress futex trio, CoIncrementMTAUsage)
  4. rewrite the wheel in place, retargeting combase.dll imports to ole32.dll
     (the only post-build fix currently needed; see docs/api-gap.md)
  5. copy the result to dist/iroh-<version>-win7-yythunks.whl

Host prerequisites (build on Windows 10/11, not on the Win7 target):
  - rustup with the stable-msvc toolchain (rustc >= the crate's rust-version)
  - Visual Studio Build Tools (link.exe) + Windows SDK
  - the python running this script must have maturin and uniffi-bindgen:
        python -m pip install maturin uniffi-bindgen

Usage:
  python build.py                                  # iroh-ffi v1.1.0, YY-Thunks v1.2.3
  python build.py --tag v1.2.0 --yythunks-tag v1.2.3 --out dist

After building, verify on the target machine with:
  python -I tools/win7gap.py <extracted>/iroh/iroh_ffi.dll <dir-of-win7-dlls>
Expect: "MISSING FUNCTION: 0".
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

REPO = "https://github.com/n0-computer/iroh-ffi"
YYTHUNKS_ASSET = "https://github.com/Chuyu-Team/YY-Thunks/releases/download/{tag}/YY-Thunks-Objs.zip"
YYTHUNKS_OBJ = "objs/x64/YY_Thunks_for_Win7.obj"

# Module-name retargets applied to the built wheel. combase.dll does not exist
# before Windows 8; the functions the rebuilt DLL needs from it (currently only
# CoTaskMemAlloc) live in ole32.dll on every Windows version.
# See docs/api-gap.md. Keep this table minimal and verified per release.
RETARGETS = [("combase.dll", "ole32.dll")]


def run(cmd, env=None, cwd=None):
    print("+ " + " ".join(str(c) for c in cmd))
    subprocess.check_call([str(c) for c in cmd], env=env, cwd=cwd)


def step_clone(tag, src_dir):
    if (src_dir / ".git").exists():
        print("[skip] source already cloned at %s" % src_dir)
        return
    run(["git", "clone", "--depth", "1", "--branch", tag, REPO, src_dir])


def step_yythunks(tag, work):
    obj = work / "yythunks" / YYTHUNKS_OBJ
    if obj.exists():
        print("[skip] %s already present" % obj)
        return obj
    url = YYTHUNKS_ASSET.format(tag=tag)
    zpath = work / "dl" / ("YY-Thunks-Objs-%s.zip" % tag)
    zpath.parent.mkdir(parents=True, exist_ok=True)
    if not zpath.exists():
        print("+ download %s" % url)
        urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extract(YYTHUNKS_OBJ, work / "yythunks")
    return obj


def step_maturin(src_dir, out_dir, obj):
    env = dict(os.environ)
    env["RUSTFLAGS"] = "-C link-arg=%s" % obj.as_posix()
    run([sys.executable, "-m", "maturin", "build", "--release", "-o", out_dir],
        env=env, cwd=src_dir)


def find_wheel(out_dir):
    wheels = sorted(pathlib.Path(out_dir).glob("iroh-*.whl"))
    if not wheels:
        sys.exit("no iroh wheel produced in %s" % out_dir)
    return wheels[-1]


def step_patch_wheel(wheel, tools_dir):
    sys.path.insert(0, str(tools_dir))
    from patch_imports import retarget_bytes  # noqa: E402

    src = zipfile.ZipFile(wheel)
    patched = wheel.with_name(wheel.name + ".tmp")
    with zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.replace("\\", "/") == "iroh/iroh_ffi.dll":
                blob = bytearray(data)
                for old, new in RETARGETS:
                    try:
                        result = retarget_bytes(blob, old, new)
                        print("+ %s: retarget %s -> %s (%s)" %
                              (info.filename, old, new, result))
                    except ValueError as exc:
                        print("+ %s: %s" % (info.filename, exc))
                data = bytes(blob)
            dst.writestr(info, data)
    src.close()
    patched.replace(wheel)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default="v1.1.0", help="iroh-ffi tag to build (default v1.1.0)")
    ap.add_argument("--yythunks-tag", default="v1.2.3", help="YY-Thunks release tag (default v1.2.3)")
    ap.add_argument("--out", default="dist", help="output directory for the wheel (default dist)")
    ap.add_argument("--work", default="work", help="scratch directory (default work)")
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parent
    work = root / args.work
    out_dir = root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    step_clone(args.tag, work / "iroh-ffi-src")
    obj = step_yythunks(args.yythunks_tag, work)
    step_maturin(work / "iroh-ffi-src", out_dir, obj)
    wheel = find_wheel(out_dir)
    step_patch_wheel(wheel, root / "tools")

    final = out_dir / (wheel.name.replace("-py3-none-", "-win7-yythunks-py3-none-"))
    shutil.move(str(wheel), final)
    print("\nBuilt %s" % final)
    print("Verify against the target system's exports before deploying:")
    print("  python -I tools/win7gap.py <wheel-extract>/iroh/iroh_ffi.dll <dir-of-win7-dlls>")
    print("Expect: MISSING FUNCTION: 0")


if __name__ == "__main__":
    main()
