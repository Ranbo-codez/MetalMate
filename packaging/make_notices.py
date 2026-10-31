"""Write THIRD_PARTY_NOTICES.txt: the licences of everything the built app bundles.

Run with the Python environment the app is built from (build_app.sh does this), so the versions and
licence texts are exactly the ones shipped."""
from __future__ import annotations

import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CBURNETT = """Chess piece images by Colin M.L. Burnett ("Cburnett"), from Wikimedia Commons
(https://commons.wikimedia.org/wiki/Category:SVG_chess_pieces), used under the BSD licence:

Copyright (c) Colin M.L. Burnett. All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted
provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions
   and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of
   conditions and the following disclaimer in the documentation and/or other materials provided
   with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to
   endorse or promote products derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF
THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


def dist_licences(name: str) -> str:
    """The licence files a package ships in its metadata (falls back to a sibling package's)."""
    dist = metadata.distribution(name)
    texts = []
    for f in dist.files or []:
        parts = [p.lower() for p in f.parts]
        if any(p.endswith(".dist-info") for p in parts) and any(k in parts[-1] for k in ("license", "copying", "notice")):
            texts.append(Path(dist.locate_file(f)).read_text(errors="replace"))
    return "\n\n".join(texts)


def main() -> None:
    v = metadata.version
    qt = v("PySide6-Essentials")
    python_licence = Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"
    parts = [
        "MetalMate bundles the following third-party software. Each part keeps its own licence;\n"
        "MetalMate's own licence (LICENSE) does not apply to them.\n",
        ("Python " + sys.version.split()[0], "PSF License Agreement", "https://www.python.org",
         python_licence.read_text(errors="replace")),
        ("Libraries built into Python: OpenSSL, expat, libffi, libmpdec, HACL*, bzip2, xz (liblzma) and SQLite",
         "OpenSSL: Apache License 2.0; expat, libffi, HACL*: MIT; libmpdec: BSD-2-Clause; bzip2: bzip2 licence; "
         "xz and SQLite: public domain",
         "https://docs.python.org/3/license.html#licenses-and-acknowledgements-for-incorporated-software",
         "The full texts and copyright notices are in licenses/Python-incorporated-software.rst (CPython's\n"
         "\"Licenses and Acknowledgements for Incorporated Software\", including OpenSSL's Apache License 2.0)\n"
         "and licenses/bzip2.txt.\n\n" + (ROOT / "licenses" / "bzip2.txt").read_text(errors="replace")),
        (f"Qt {qt} and Qt for Python (PySide6, Shiboken6) {qt}",
         "GNU Lesser General Public License v3.0 (licenses/LGPL-3.0.txt, which builds on licenses/GPL-3.0.txt)",
         "https://www.qt.io, https://doc.qt.io/qtforpython-6/",
         "MetalMate uses Qt as unmodified shared libraries (inside MetalMate.app/Contents/Frameworks),\n"
         "which you may replace with your own builds of the same version. The source code of Qt and of\n"
         f"Qt for Python {qt} is available from https://download.qt.io/official_releases/qt/ and\n"
         "https://code.qt.io/cgit/pyside/pyside-setup.git (tag v" + qt + "). The full licence texts are\n"
         "in the licenses folder next to this file."),
        (f"NumPy {v('numpy')}", "BSD-3-Clause (and the bundled components listed below)", "https://numpy.org",
         dist_licences("numpy")),
        (f"Pillow {v('pillow')}", "MIT-CMU", "https://python-pillow.github.io", dist_licences("pillow")),
        (f"python-mss {v('mss')}", "MIT", "https://github.com/BoboTiG/python-mss", dist_licences("mss")),
        (f"truststore {v('truststore')}", "MIT", "https://github.com/sethmlarson/truststore",
         dist_licences("truststore")),
        (f"PyObjC {v('pyobjc-core')} (pyobjc-core, pyobjc-framework-Cocoa, pyobjc-framework-Quartz)", "MIT",
         "https://github.com/ronaldoussoren/pyobjc", dist_licences("pyobjc-framework-Cocoa")),
        (f"PyInstaller {v('pyinstaller')} bootloader", "GPL-2.0-or-later with the PyInstaller bootloader exception",
         "https://pyinstaller.org", dist_licences("pyinstaller")),
        ("Chess pieces (Cburnett)", "BSD-3-Clause", "https://commons.wikimedia.org/wiki/User:Cburnett", CBURNETT),
    ]
    out = [parts[0]]
    for name, licence, url, text in parts[1:]:
        out.append("=" * 100 + f"\n{name}\nLicence: {licence}\n{url}\n" + "-" * 100 + "\n" + text.strip() + "\n")
    (ROOT / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(out))
    print("wrote THIRD_PARTY_NOTICES.txt")


if __name__ == "__main__":
    main()
