# PyInstaller spec for MetalMate.app. Build with packaging/build_app.sh.
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "(.+?)"', (ROOT / "metalmate" / "__init__.py").read_text()).group(1)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    hiddenimports=["PySide6.QtSvg", "Quartz", "AppKit", "objc"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtOpenGL",
              "PySide6.QtDBus", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtXml", "PySide6.QtHelp",
              "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtConcurrent"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MetalMate", console=False,
          argv_emulation=False, target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="MetalMate")
app = BUNDLE(
    coll,
    name="MetalMate.app",
    icon=str(ROOT / "packaging" / "MetalMate.icns"),
    bundle_identifier="com.ranbirdhall.metalmate",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "MetalMate",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSApplicationCategoryType": "public.app-category.board-games",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright": "© 2026 Ranbir Dhall · PolyForm Noncommercial 1.0.0",
        "NSScreenCaptureUsageDescription": "MetalMate takes screenshots of the chessboard window you choose "
                                           "to follow the game.",
    },
)
