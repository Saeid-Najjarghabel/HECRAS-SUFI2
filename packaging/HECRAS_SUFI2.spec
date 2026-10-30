# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — build with:  pyinstaller --noconfirm packaging/HECRAS_SUFI2.spec
import os
from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = [(os.path.join(ROOT, "sufi2_gui", "resources"), "resources")]
datas += collect_data_files("pyproj")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["win32com", "win32com.client", "pythoncom", "pywintypes",
                   "shapely.strtree", "pyogrio._geometry", "pyogrio._io", "openpyxl"],
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "notebook", "pytest", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="HECRAS-SUFI2",
    console=False,
    icon=os.path.join(ROOT, "sufi2_gui", "resources", "app_icon.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="HECRAS-SUFI2")
