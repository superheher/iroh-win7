"""Check a DLL's imports against real Windows 7 export tables.

Compares the static imports of a PE module against the export tables of a set
of DLLs copied from the target system. Answers two questions before you waste
time on a target machine:

  * which imported functions are absent from the versions of their modules
    that exist on Windows 7 (MISSING FUNCTION), and
  * which imported modules do not exist there at all in your sample set
    (MISSING DLL -- note this is only meaningful for modules you actually
    copied; stock system modules such as ws2_32.dll or ntdll.dll need not be
    sampled, they are always present).

Usage:
    python -I win7gap.py <file.dll> <dir-with-win7-dlls>

The directory should hold the target system's copies of the modules you want
checked (kernel32.dll, kernelbase.dll, bcryptprimitives.dll, ...). Pure
stdlib; no third-party PE parser.
"""
import struct, sys, os


def parse_pe(path):
    data = open(path, "rb").read()
    e = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[e:e + 4] == b"PE\0\0", path
    coff = e + 4
    machine, nsec, _, _, _, opt_size, chars = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    plus = magic == 0x20B
    ddoff = opt + (112 if plus else 96)      # data directories array start
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

    def cstr(off):
        end = data.index(b"\0", off)
        return data[off:end].decode("ascii", "replace")

    def dd(idx):
        rva, size = struct.unpack_from("<II", data, ddoff + 8 * idx)
        return rva, size

    def imports():
        rva, _ = dd(1)
        if not rva:
            return []
        out = []
        off = rva2off(rva)
        while True:
            thunk, _, _, name_rva, fthunk = struct.unpack_from("<IIIII", data, off)
            if thunk == 0 and name_rva == 0:
                break
            dll = cstr(rva2off(name_rva))
            names = []
            t = rva2off(thunk) or rva2off(fthunk)
            if t is not None:
                step = 8 if plus else 4
                while True:
                    v = struct.unpack_from("<Q" if plus else "<I", data, t)[0]
                    if v == 0:
                        break
                    if v & (1 << (63 if plus else 31)):
                        names.append("#ord%d" % (v & 0xFFFF))
                    else:
                        names.append(cstr(rva2off(v) + (2 if plus else 0)))
                    t += step
            out.append((dll, names))
            off += 20
        return out

    def exports():
        rva, size = dd(0)
        if not rva:
            return {}
        base = rva2off(rva)
        _, _, _, _, _, _, nfuncs, nnames, af_rva, an_rva, ao_rva = struct.unpack_from(
            "<IIHHIIIIIII", data, base)
        names_off = rva2off(an_rva)
        ords_off = rva2off(ao_rva)
        funcs_off = rva2off(af_rva)
        exp = {}
        for i in range(nnames):
            name = cstr(rva2off(struct.unpack_from("<I", data, names_off + 4 * i)[0]))
            o = struct.unpack_from("<H", data, ords_off + 2 * i)[0]
            frva = struct.unpack_from("<I", data, funcs_off + 4 * o)[0]
            fwd = ""
            fr = rva2off(frva)
            if fr is not None and rva <= frva < rva + size:  # forwarder string
                fwd = cstr(fr)
            exp[name] = fwd
        return exp

    return {"imports": imports, "exports": exports}


def main():
    ffi_path, dll_dir = sys.argv[1], sys.argv[2]
    local = {}
    for f in os.listdir(dll_dir):
        if f.lower().endswith(".dll"):
            local[f.lower()] = os.path.join(dll_dir, f)
    exports = {k: parse_pe(v)["exports"]() for k, v in local.items()}

    ok, miss_dll, miss_func, fwd = [], [], [], []
    for dll, names in parse_pe(ffi_path)["imports"]():
        key = dll.lower()
        for name in names:
            if key in exports:
                if name in exports[key]:
                    (fwd if exports[key][name] else ok).append((dll, name, exports[key][name]))
                else:
                    miss_func.append((dll, name))
            else:
                miss_dll.append((dll, name))

    print("== OK (export found): %d" % len(ok))
    print("== forwarders (resolve via a forwarder string): %d" % len(fwd))
    for d, n, t in fwd:
        print("   %s!%s -> %s" % (d, n, t))
    print("== MISSING FUNCTION (module exists, export absent): %d" % len(miss_func))
    for d, n in miss_func:
        print("   %s!%s" % (d, n))
    print("== MISSING DLL (not in the sample dir): %d" % len(miss_dll))
    for d, n in miss_dll:
        print("   %s!%s" % (d, n))


if __name__ == "__main__":
    main()
