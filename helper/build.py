"""Build the PC Helper into one program members download: a .exe on Windows, a .app (zipped) on a Mac.

    cd helper
    python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   (Mac: .venv/bin/pip)
    .venv/Scripts/python build.py                                             (Mac: .venv/bin/python build.py)

The result is in helper/dist/. A Mac build must be made on a Mac (GitHub Actions does both: .github/workflows/helper.yml).
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "ClipRelay Helper"


def main() -> None:
    # The very editing code the server runs, so a PC edits exactly like the server.
    shutil.copyfile(os.path.join(HERE, "..", "backend", "app", "services", "media.py"), os.path.join(HERE, "app", "services", "media.py"))
    sys.path.insert(0, HERE)
    from cliprelay_helper.logo import save_icons

    ico, png = save_icons(os.path.join(HERE, "app"))  # the ClipRelay mark as the program's icon
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NAME, "--paths", HERE,
        "--collect-all", "yt_dlp_ejs", "--collect-all", "imageio_ffmpeg", "--collect-submodules", "yt_dlp",
        "--hidden-import", "app.services.media", "--hidden-import", "app.config",
    ]
    if sys.platform == "win32":
        args += ["--onefile", "--noconsole", "--hidden-import", "pystray._win32", "--icon", ico]
    elif sys.platform == "darwin":
        args += ["--windowed", "--hidden-import", "pystray._darwin", "--osx-bundle-identifier", "com.cliprelay.helper", "--icon", png]
    args.append(os.path.join(HERE, "run.py"))
    subprocess.run(args, check=True, cwd=HERE)
    dist = os.path.join(HERE, "dist")
    if sys.platform == "darwin":
        app = os.path.join(dist, f"{NAME}.app")
        plist = os.path.join(app, "Contents", "Info.plist")
        # An icon next to the clock only, with no Dock icon.
        subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Add :LSUIElement bool true", plist], check=False)
        import platform

        name = "ClipRelay-Helper-mac" if platform.machine() == "arm64" else "ClipRelay-Helper-mac-intel"  # Apple chip, or an older Intel Mac
        shutil.make_archive(os.path.join(dist, name), "zip", dist, f"{NAME}.app")
    elif sys.platform == "win32":
        shutil.copyfile(os.path.join(dist, f"{NAME}.exe"), os.path.join(dist, "ClipRelay-Helper-windows.exe"))
    print("Built:", ", ".join(sorted(os.listdir(dist))))


if __name__ == "__main__":
    main()
