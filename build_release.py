"""Build one distributable asset for a GitHub Release.

Local use:
    python build_release.py                  # bundle the current OS with PyInstaller
    python build_release.py --source-only    # portable source bundle, works everywhere

CI use (.github/workflows/release.yml):
    RELEASE_VERSION=v1.0.0 RELEASE_PLATFORM=windows-x64 python build_release.py

Only the standard library is needed for --source-only; the binary builds need
PyInstaller (pip install pyinstaller). PyInstaller cannot cross-compile, so each
OS must run this script on its own runner.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
PREFIX = "node-searcher"


def get_version():
    v = (os.environ.get("RELEASE_VERSION") or "").strip()
    if v:
        return v
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"',
                  (ROOT / "node_searcher.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "dev"


def get_platform():
    p = (os.environ.get("RELEASE_PLATFORM") or "").strip()
    if p:
        return p
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos"
    return "linux-x64"


def pack_source(ver):
    OUT.mkdir(exist_ok=True)
    dest = OUT / ("%s-%s-source.zip" % (PREFIX, ver))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("node_searcher.py", "run.bat", "run.sh", "README.md"):
            p = ROOT / name
            if p.is_file():
                z.write(p, "%s-%s/%s" % (PREFIX, ver, name))
    return dest


def pyinstaller_flags():
    if sys.platform == "win32":
        # No console window: node_searcher.py installs a _NullWriter for stdout/stderr.
        return ["--onefile", "--windowed", "--name", PREFIX]
    if sys.platform == "darwin":
        # PyInstaller 7 refuses --onefile + --windowed on macOS; a .app bundle is
        # the supported shape. Do not add --onefile here.
        return ["--windowed", "--name", "NodeSearcher"]
    return ["--onefile", "--name", PREFIX]


def build_binary(ver, platform):
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    cmd = ([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean"]
           + pyinstaller_flags() + ["node_searcher.py"])
    print("BUILD:", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(ROOT))

    OUT.mkdir(exist_ok=True)
    dest = OUT / ("%s-%s-%s.zip" % (PREFIX, ver, platform))
    if sys.platform == "darwin":
        # PyInstaller 6+ .app bundles contain symlinks: use `zip -y` to keep them.
        app = ROOT / "dist" / "NodeSearcher.app"
        if not app.is_dir():
            raise SystemExit("Missing %s" % app)
        if dest.exists():
            dest.unlink()
        subprocess.check_call(["zip", "-q", "-y", "-r", str(dest), app.name],
                              cwd=str(ROOT / "dist"))
        with zipfile.ZipFile(dest, "a", zipfile.ZIP_DEFLATED) as z:
            z.write(ROOT / "README.md", "README.md")
    else:
        exe = ROOT / "dist" / (PREFIX + (".exe" if sys.platform == "win32" else ""))
        if not exe.is_file():
            raise SystemExit("Missing %s" % exe)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(exe, exe.name)
            z.write(ROOT / "README.md", "README.md")
    return dest


def main():
    ver = get_version()
    if "--source-only" in sys.argv[1:]:
        dest = pack_source(ver)
    else:
        dest = build_binary(ver, get_platform())
    print("ASSET=%s (%d bytes)" % (dest, dest.stat().st_size), flush=True)


if __name__ == "__main__":
    main()
