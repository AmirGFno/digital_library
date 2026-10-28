"""Inputs shared by the portable and the installed PyInstaller builds.

Both specs import this module so the bundled assets, hidden imports and the
excluded Qt modules can never drift apart.
"""
from pathlib import Path

DATAS = [
    ("assets/icon.png", "assets"),
    ("assets/icon.ico", "assets"),
    ("assets/default_cover.png", "assets"),
    ("assets/chevron.png", "assets"),
    ("assets/check.png", "assets"),
    ("assets/radio_dot.png", "assets"),
]

# The brand font follows the program: a machine without it installed must
# still draw the title the same way. Font files in assets/ and in
# assets/fonts/ are packaged as they are, so a second weight needs no change
# here and the file can sit wherever it was dropped.
FONT_SUFFIXES = {".ttf", ".otf"}
for _folder in (Path("assets"), Path("assets") / "fonts"):
    if not _folder.is_dir():
        continue
    DATAS += [
        (str(path), str(_folder))
        for path in sorted(_folder.iterdir())
        if path.is_file() and path.suffix.lower() in FONT_SUFFIXES
    ]

HIDDEN_IMPORTS = [
    "rarfile",
    "py7zr",
    "PIL",
    "PIL.Image",
    "pypdfium2",
    "pypdfium2_raw",
]

EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc",
    "pytest",
    "_pytest",
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebChannel",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtSerialPort",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtOpenGL",
    "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtXml",
    "PyQt6.QtDBus",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtSvg",
    "PyQt6.QtSvgWidgets",
    "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization",
    "PyQt6.Qt3DCore",
    "PyQt6.Qt3DRender",
    "pymupdf",
    "pymupdf4llm",
    "pymupdf_layout",
    "fitz",
    "numpy",
    "scipy",
    "matplotlib",
    "pandas",
    "onnxruntime",
]
