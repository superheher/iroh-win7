"""Retarget a PE import-table module name in place, without shifting bytes.

A PE import descriptor names its source module with a NUL-terminated string.
If a binary imports a function from a module that does not exist on Windows 7
(e.g. `combase.dll`) while the very same function is exported by an older
module that does (`ole32.dll`), pointing the descriptor at the older module is
a one-string fix -- provided the new name is **not longer** than the old one:
shorter names are padded with NUL bytes, but a longer replacement would grow
the file, shift every RVA after the string, and corrupt the image.

Usage:
    python -I patch_imports.py <file.dll> --list
    python -I patch_imports.py <file.dll> <from.dll> <to.dll>

`--list` dumps every import descriptor and its functions (read-only). The
retarget form enforces equal length, requires the old name to be unique, is a
no-op if the file was already retargeted, and re-parses the import table
afterwards to prove the file still parses.
"""
import struct, sys


def _parse(data):
    e = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[e:e + 4] == b"PE\0\0"
    coff = e + 4
    _, nsec, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    plus = struct.unpack_from("<H", data, opt)[0] == 0x20B
    ddoff = opt + (112 if plus else 96)
    sec = opt + opt_size
    sections = []
    for i in range(nsec):
        off = sec + 40 * i
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((vaddr, max(vsize, rsize), raddr))

    def rva2off(rva):
        for vaddr, size, raddr in sections:
            if vaddr <= rva < vaddr + size:
                return raddr + (rva - vaddr)
        return None

    def cstr(off, blob=None):
        blob = data if blob is None else blob
        end = blob.index(b"\0", off)
        return blob[off:end].decode("ascii", "replace")

    dd = ddoff
    imp_rva = struct.unpack_from("<II", data, dd + 8)[0]
    descriptors = []
    off = rva2off(imp_rva)
    while True:
        thunk, _, _, name_rva, fthunk = struct.unpack_from("<IIIII", data, off)
        if thunk == 0 and name_rva == 0:
            break
        name_off = rva2off(name_rva)
        name = cstr(name_off)
        t = rva2off(thunk) or rva2off(fthunk)
        funcs = []
        if t is not None:
            step = 8 if plus else 4
            while True:
                v = struct.unpack_from("<Q" if plus else "<I", data, t)[0]
                if v == 0:
                    break
                if v & (1 << (63 if plus else 31)):
                    funcs.append("#ord%d" % (v & 0xFFFF))
                else:
                    funcs.append(cstr(rva2off(v) + (2 if plus else 0)))
                t += step
        descriptors.append((name, name_off, funcs))
        off += 20
    return descriptors


def list_descriptors(path):
    data = open(path, "rb").read()
    for name, _, funcs in _parse(data):
        print("== %s (%d imports)" % (name, len(funcs)))
        print("  " + ", ".join(funcs))


def retarget_bytes(data, old, new):
    """Retarget module name `old` to `new` inside PE bytes (in place).

    Returns "patched", "already", or raises. `old`/`new` are module names with
    or without the .dll suffix, matched case-insensitively against descriptor
    name strings; the new name must not be longer than the old one.
    """
    if not old.lower().endswith(".dll"):
        old += ".dll"
    if not new.lower().endswith(".dll"):
        new += ".dll"
    old_b, new_b = old.encode(), new.encode()
    if len(new_b) > len(old_b):
        raise ValueError(
            "new module name %r is longer than %r; an in-place string patch "
            "would shift RVAs and corrupt the file" % (new, old))
    new_padded = new_b + b"\0" * (len(old_b) - len(new_b))

    descriptors = _parse(bytes(data))
    names = [d[0].lower() for d in descriptors]
    if old.lower() not in names:
        if new.lower() in names:
            return "already"          # retargeted before; nothing to do
        raise ValueError("no import descriptor named %r" % old)

    count = bytes(data).count(old_b)
    if count != 1:
        raise ValueError("expected exactly one %r string, found %d" % (old_b, count))
    idx = data.index(old_b)
    data[idx:idx + len(old_b)] = new_padded

    # prove the file still parses and the descriptor now carries the new name
    names2 = [d[0].lower() for d in _parse(bytes(data))]
    assert new.lower() in names2, "post-patch parse lost the descriptor"
    return "patched"


def retarget_file(path, old, new):
    data = bytearray(open(path, "rb").read())
    result = retarget_bytes(data, old, new)
    if result == "patched":
        open(path, "wb").write(data)
    print("%s: %s" % (path, result))


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--list":
        sys.exit("usage: patch_imports.py <file.dll> --list")
    path = args[0]
    if len(args) == 2 and args[1] == "--list":
        list_descriptors(path)
        return
    if len(args) != 3:
        sys.exit(__doc__)
    retarget_file(path, args[1], args[2])


if __name__ == "__main__":
    main()
