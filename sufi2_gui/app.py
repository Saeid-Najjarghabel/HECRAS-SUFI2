# -*- coding: utf-8 -*-
"""HEC-RAS SUFI-2 Calibrator — desktop interface (PySide6)."""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import traceback
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout,
    QWidget,
)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from . import __version__, hecras_project, ras_controller  # noqa: E402
from .engine import (DEFAULT_CONFIG, CalibrationStopped, Callbacks, SufiEngine,  # noqa: E402
                     read_landcover_table, read_obs_series, sanitize_colname)

APP_NAME = "HEC-RAS SUFI-2 Calibrator"
ORG = "University of West London"

# --------------------------------------------------------------------------- resources
def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "resources", name)
    if not os.path.exists(p):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", name)
    return p


def logo_path() -> Optional[str]:
    for n in ("uwl_logo.png", "uwl_logo.jpg", "uwl_logo.svg", "logo.png"):
        p = resource_path(n)
        if os.path.exists(p):
            return p
    return None


NAVY, ACCENT, ACCENT_DARK = "#13294b", "#0e6e8c", "#0a5770"
COL_OBS, COL_BEST, COL_PPU, COL_BEH, COL_NON = "#1f4e79", "#c0392b", "#9aa5b1", "#2e8b57", "#b8c0ca"

STYLE = f"""
QMainWindow, QWidget#Page {{ background: #f4f6f9; }}
QWidget {{ font-size: 10pt; color: #1d2633; }}
QFrame#Header {{ background: {NAVY}; }}
QLabel#Title {{ color: white; font-size: 17pt; font-weight: 600; }}
QLabel#Subtitle {{ color: #c7d3e3; font-size: 10pt; }}
QLabel#Version {{ color: #c7d3e3; font-size: 9pt; }}
QFrame#LogoBox {{ background: white; border-radius: 8px; }}
QListWidget#Nav {{ background: #e9edf2; border: none; padding-top: 10px; outline: 0; }}
QListWidget#Nav::item {{ padding: 12px 14px; margin: 2px 8px; border-radius: 6px; color: #33415c; }}
QListWidget#Nav::item:selected {{ background: white; color: {ACCENT_DARK}; font-weight: 600; }}
QListWidget#Nav::item:hover:!selected {{ background: #dfe5ec; }}
QGroupBox {{ background: white; border: 1px solid #dde3ea; border-radius: 8px; margin-top: 14px;
             padding: 14px 12px 10px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {NAVY}; }}
QLabel#PageTitle {{ font-size: 15pt; font-weight: 600; color: {NAVY}; }}
QLabel#Hint {{ color: #5b6778; font-weight: normal; }}
QLineEdit, QComboBox {{ background: white; border: 1px solid #c9d1db;
             border-radius: 5px; padding: 4px 6px; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QSpinBox, QDoubleSpinBox {{ min-height: 26px; }}
QPushButton {{ background: white; border: 1px solid #c9d1db; border-radius: 5px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT_DARK}; }}
QPushButton:disabled {{ color: #9aa5b1; background: #f0f2f5; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 8px 18px; }}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; color: white; }}
QPushButton#Primary:disabled {{ background: #9fbfca; }}
QPushButton#Danger {{ color: #a93226; }}
QPushButton#Danger:hover {{ border-color: #a93226; }}
QTableWidget {{ background: white; border: 1px solid #dde3ea; border-radius: 6px; gridline-color: #edf0f4; }}
QHeaderView::section {{ background: #eef2f6; border: none; border-bottom: 1px solid #dde3ea;
                        padding: 6px; font-weight: 600; color: #33415c; }}
QPlainTextEdit#Log {{ background: #0f1b2d; color: #d6e2f0; border-radius: 6px;
                      font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 9pt; }}
QProgressBar {{ border: 1px solid #c9d1db; border-radius: 5px; background: white; text-align: center; height: 18px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QFrame#Card {{ background: white; border: 1px solid #dde3ea; border-radius: 8px; }}
QLabel#CardTitle {{ color: #5b6778; font-size: 9pt; }}
QLabel#CardValue {{ color: {NAVY}; font-size: 16pt; font-weight: 600; }}
QFrame#Banner {{ background: #fff6dd; border: 1px solid #f0d58a; border-radius: 8px; }}
QTabWidget::pane {{ border: 1px solid #dde3ea; border-radius: 6px; background: white; top: -1px; }}
QTabBar::tab {{ background: #e9edf2; padding: 6px 14px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: white; color: {ACCENT_DARK}; font-weight: 600; }}
"""

TIMEZONES = ["Europe/London", "UTC", "Europe/Paris", "Europe/Berlin", "Asia/Tehran", "America/New_York",
             "America/Chicago", "America/Denver", "America/Los_Angeles", "Australia/Sydney", "Asia/Tokyo"]


# --------------------------------------------------------------------------- small widgets
class FilePicker(QWidget):
    changed = Signal(str)

    def __init__(self, caption: str, filt: str, save: bool = False, directory: bool = False):
        super().__init__()
        self.caption, self.filt, self.save, self.directory = caption, filt, save, directory
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(); self.edit.setPlaceholderText("Not selected")
        btn = QPushButton("Browse…"); btn.clicked.connect(self.browse)
        lay.addWidget(self.edit, 1); lay.addWidget(btn)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.text()))

    def browse(self):
        start = os.path.dirname(self.text()) if self.text() else ""
        if self.directory:
            p = QFileDialog.getExistingDirectory(self, self.caption, self.text() or start)
        elif self.save:
            p, _ = QFileDialog.getSaveFileName(self, self.caption, start, self.filt)
        else:
            p, _ = QFileDialog.getOpenFileName(self, self.caption, start, self.filt)
        if p:
            self.setText(os.path.normpath(p)); self.changed.emit(self.text())

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, t: str):
        self.edit.setText(t or "")


def dspin(lo, hi, val, dec=4, step=0.001, suffix=""):
    s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec); s.setSingleStep(step); s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


def ispin(lo, hi, val):
    s = QSpinBox(); s.setRange(lo, hi); s.setValue(val); return s


def hint(text: str) -> QLabel:
    l = QLabel(text); l.setObjectName("Hint"); l.setWordWrap(True); return l


class PlotCanvas(QWidget):
    def __init__(self, figsize=(7, 4)):
        super().__init__()
        self.fig = Figure(figsize=figsize, tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(NavigationToolbar2QT(self.canvas, self)); lay.addWidget(self.canvas, 1)
        self.placeholder("Results will appear here")

    def placeholder(self, text):
        self.ax.clear(); self.ax.set_axis_off()
        self.ax.text(0.5, 0.5, text, ha="center", va="center", color="#8a96a8", fontsize=11,
                     transform=self.ax.transAxes)
        self.canvas.draw_idle()

    def reset(self):
        self.ax.clear(); self.ax.set_axis_on(); self.ax.grid(True, ls="--", lw=0.5, alpha=0.7)
        for s in ("top", "right"):
            self.ax.spines[s].set_visible(False)


class Card(QFrame):
    def __init__(self, title: str):
        super().__init__(); self.setObjectName("Card")
        lay = QVBoxLayout(self); lay.setContentsMargins(12, 8, 12, 8); lay.setSpacing(0)
        t = QLabel(title); t.setObjectName("CardTitle")
        self.value = QLabel("—"); self.value.setObjectName("CardValue")
        lay.addWidget(t); lay.addWidget(self.value)

    def set(self, v):
        self.value.setText(v)


# --------------------------------------------------------------------------- worker thread
class Worker(QObject):
    log = Signal(str)
    progress = Signal(int, int, str)
    baseline = Signal(object, object)
    sample = Signal(object)
    iteration = Signal(int, object, object, object, object)
    finished = Signal(object)
    failed = Signal(str, bool)
    manual = Signal(str)

    def __init__(self, cfg: Dict[str, Any], do_sufi: bool):
        super().__init__()
        self.cfg, self.do_sufi = cfg, do_sufi
        self._stop = threading.Event()
        self._manual_event = threading.Event()
        self._manual_ok = True

    def stop(self):
        self._stop.set(); self._manual_ok = False; self._manual_event.set()

    def manual_answer(self, ok: bool):
        self._manual_ok = ok; self._manual_event.set()

    def run(self):
        w = self

        class CB(Callbacks):
            def log(self, m): w.log.emit(m)
            def progress(self, d, t, s): w.progress.emit(d, t, s)
            def baseline(self, df, m): w.baseline.emit(df, m)
            def sample(self, r): w.sample.emit(r)
            def iteration(self, it, ppu, obs, best, b): w.iteration.emit(it, ppu, obs, best, b)
            def should_stop(self): return w._stop.is_set()

            def wait_for_manual_run(self, message):
                w._manual_event.clear(); w.manual.emit(message); w._manual_event.wait()
                return w._manual_ok and not w._stop.is_set()

        try:
            summary = SufiEngine(self.cfg, CB()).run(self.do_sufi)
            self.finished.emit(summary)
        except CalibrationStopped as e:
            self.failed.emit(str(e), True)
        except Exception as e:  # report everything to the UI
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(e), False)


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)
        self.settings_path: Optional[str] = None
        self.thread: Optional[QThread] = None
        self.worker: Optional[Worker] = None
        self.history: List[Dict[str, Any]] = []
        self.qsettings = QSettings("UWL", "HECRAS-SUFI2")

        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(self._header())

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        self.nav = QListWidget(); self.nav.setObjectName("Nav"); self.nav.setFixedWidth(220)
        self.stack = QStackedWidget()
        pages = [("1   Project & data", self._page_project()),
                 ("2   Gauge & transect", self._page_transect()),
                 ("3   Roughness parameters", self._page_params()),
                 ("4   SUFI-2 settings", self._page_sufi()),
                 ("5   Run & results", self._page_run())]
        for label, page in pages:
            self.nav.addItem(QListWidgetItem(label)); self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        body.addWidget(self.nav); body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        self._menus()
        self.statusBar().showMessage("Ready")
        self.load_config(DEFAULT_CONFIG)
        last = self.qsettings.value("last_config", "")
        if last and os.path.isfile(last):
            try:
                self.open_settings(last)
            except Exception:
                pass
        self._update_run_count()

    # ---- header ---------------------------------------------------------
    def _header(self) -> QWidget:
        h = QFrame(); h.setObjectName("Header"); h.setFixedHeight(92)
        lay = QHBoxLayout(h); lay.setContentsMargins(18, 10, 22, 10); lay.setSpacing(18)
        box = QFrame(); box.setObjectName("LogoBox")
        bl = QHBoxLayout(box); bl.setContentsMargins(12, 6, 12, 6)
        logo = QLabel()
        lp = logo_path()
        if lp:
            pm = QPixmap(lp)
            logo.setPixmap(pm.scaledToHeight(58, Qt.SmoothTransformation))
        else:
            logo.setText("University of\nWest London")
            logo.setStyleSheet(f"color:{NAVY}; font-weight:700; font-size:11pt;")
        bl.addWidget(logo)
        lay.addWidget(box)
        tl = QVBoxLayout(); tl.setSpacing(2)
        t = QLabel(APP_NAME); t.setObjectName("Title")
        s = QLabel("Automatic Manning's n calibration and 95PPU uncertainty analysis for HEC-RAS 2D models")
        s.setObjectName("Subtitle")
        tl.addStretch(); tl.addWidget(t); tl.addWidget(s); tl.addStretch()
        lay.addLayout(tl, 1)
        v = QLabel(f"v{__version__}\n{ORG}"); v.setObjectName("Version"); v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(v)
        return h

    def _menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        for text, slot, sc in (("&New settings", self.new_settings, "Ctrl+N"),
                               ("&Open settings…", lambda: self.open_settings(), "Ctrl+O"),
                               ("&Save settings", self.save_settings, "Ctrl+S"),
                               ("Save settings &as…", lambda: self.save_settings(True), "Ctrl+Shift+S")):
            a = QAction(text, self); a.setShortcut(sc); a.triggered.connect(slot); fm.addAction(a)
        fm.addSeparator()
        a = QAction("Restore original geometry (.bak)…", self); a.triggered.connect(self.restore_backup); fm.addAction(a)
        fm.addSeparator()
        a = QAction("E&xit", self); a.triggered.connect(self.close); fm.addAction(a)
        hm = mb.addMenu("&Help")
        a = QAction("User guide", self); a.setShortcut("F1"); a.triggered.connect(self.show_guide); hm.addAction(a)
        a = QAction("About", self); a.triggered.connect(self.show_about); hm.addAction(a)

    # ---- page helpers ---------------------------------------------------
    def _page(self, title: str, subtitle: str):
        outer = QWidget(); outer.setObjectName("Page")
        ol = QVBoxLayout(outer); ol.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget(); inner.setObjectName("Page")
        lay = QVBoxLayout(inner); lay.setContentsMargins(26, 20, 26, 20); lay.setSpacing(10)
        t = QLabel(title); t.setObjectName("PageTitle")
        lay.addWidget(t); lay.addWidget(hint(subtitle))
        sc.setWidget(inner); ol.addWidget(sc)
        return outer, lay

    def _nav_buttons(self, lay, idx):
        row = QHBoxLayout(); row.addStretch()
        if idx > 0:
            b = QPushButton("← Back"); b.clicked.connect(lambda: self.nav.setCurrentRow(idx - 1)); row.addWidget(b)
        b = QPushButton("Next →"); b.setObjectName("Primary")
        b.clicked.connect(lambda: self.nav.setCurrentRow(idx + 1)); row.addWidget(b)
        lay.addStretch(); lay.addLayout(row)

    # ---- page 1: project -------------------------------------------------
    def _page_project(self):
        page, lay = self._page("Project & data",
                               "Select the HEC-RAS project and plan to calibrate, and the observed discharge record.")
        g = QGroupBox("HEC-RAS model"); f = QFormLayout(g); f.setLabelAlignment(Qt.AlignRight)
        self.prj = FilePicker("HEC-RAS project", "HEC-RAS project (*.prj);;All files (*)")
        self.prj.changed.connect(self._on_prj)
        self.plan = QComboBox(); self.plan.setEditable(True); self.plan.setMinimumWidth(260)
        self.plan.currentTextChanged.connect(self._on_plan)
        self.results = FilePicker("Results HDF", "HDF5 (*.hdf *.h5);;All files (*)")
        self.geom = FilePicker("Geometry HDF", "HDF5 (*.hdf *.h5);;All files (*)")
        self.epsg = ispin(1000, 999999, 27700)
        f.addRow("Project file (.prj):", self.prj)
        f.addRow("Plan:", self.plan)
        f.addRow("Results HDF:", self.results)
        f.addRow("", hint("The plan output file (e.g. Project.p03.hdf), or a post-processing HDF containing 'Face Flow'."))
        f.addRow("Geometry HDF:", self.geom)
        f.addRow("", hint("The geometry file whose land-cover Manning's n table will be modified (e.g. Project.g02.hdf). "
                          "A .bak copy is made before the first change."))
        f.addRow("Model CRS (EPSG):", self.epsg)
        lay.addWidget(g)

        g = QGroupBox("Observed discharge"); f = QFormLayout(g); f.setLabelAlignment(Qt.AlignRight)
        self.obs = FilePicker("Observation file", "CSV / Excel (*.csv *.txt *.xlsx *.xls);;All files (*)")
        self.obs_tz = QComboBox(); self.obs_tz.setEditable(True); self.obs_tz.addItems(TIMEZONES)
        self.obs_dayfirst = QCheckBox("Dates are day-first (dd/mm/yyyy)")
        prev = QPushButton("Preview observations"); prev.clicked.connect(self.preview_obs)
        f.addRow("File:", self.obs)
        f.addRow("", hint("Column 1: date/time, column 2: discharge (m³/s). No header needed."))
        f.addRow("Time zone of observations:", self.obs_tz)
        f.addRow("", self.obs_dayfirst)
        f.addRow("", prev)
        lay.addWidget(g)

        g = QGroupBox("Running HEC-RAS"); v = QVBoxLayout(g)
        self.rb_auto = QRadioButton("Automatic — run the plan through the HEC-RAS controller (recommended)")
        self.rb_manual = QRadioButton("Manual — pause after each parameter update so I can run the plan myself")
        grp = QButtonGroup(g); grp.addButton(self.rb_auto); grp.addButton(self.rb_manual)
        row = QHBoxLayout(); row.addSpacing(24); row.addWidget(QLabel("HEC-RAS version:"))
        self.controller = QComboBox(); self.controller.addItem("Auto-detect", "auto")
        for pid in ras_controller.available_controllers() or ras_controller.KNOWN_PROGIDS:
            self.controller.addItem(pid.replace(".HECRASController", "").replace("RAS", "HEC-RAS "), pid)
        self.controller.addItem("hecrascontroller (Python package)", "hecrascontroller")
        row.addWidget(self.controller); row.addStretch()
        self.rb_auto.toggled.connect(self.controller.setEnabled)
        v.addWidget(self.rb_auto); v.addLayout(row); v.addWidget(self.rb_manual)
        lay.addWidget(g)

        g = QGroupBox("Outputs"); f = QFormLayout(g); f.setLabelAlignment(Qt.AlignRight)
        self.out_dir = FilePicker("Output folder", "", directory=True)
        f.addRow("Output folder:", self.out_dir)
        lay.addWidget(g)
        self._nav_buttons(lay, 0)
        return page

    def _on_prj(self, path):
        plans = hecras_project.list_plans(path)
        cur = self.plan.currentText()
        self.plan.blockSignals(True); self.plan.clear()
        for p in plans:
            self.plan.addItem(p.title, p.code)
        self.plan.blockSignals(False)
        if cur and self.plan.findText(cur) >= 0:
            self.plan.setCurrentText(cur)
        elif plans:
            self.plan.setCurrentIndex(0); self._on_plan(self.plan.currentText())
        if path and not self.out_dir.text():
            self.out_dir.setText(os.path.join(os.path.dirname(path), "sufi_outputs"))

    def _on_plan(self, title):
        p = hecras_project.find_plan(self.prj.text(), title)
        if not p:
            return
        if os.path.exists(p.results_hdf):
            self.results.setText(p.results_hdf)
        if p.geom_hdf and os.path.exists(p.geom_hdf):
            self.geom.setText(p.geom_hdf)

    def preview_obs(self):
        try:
            s = read_obs_series(self.obs.text(), self.obs_tz.currentText(), self.obs_dayfirst.isChecked())
        except Exception as e:
            QMessageBox.warning(self, "Observations", str(e)); return
        dlg = QDialog(self); dlg.setWindowTitle("Observed discharge"); dlg.resize(820, 440)
        l = QVBoxLayout(dlg); pc = PlotCanvas(); pc.reset()
        pc.ax.plot(s.index, s.values, color=COL_OBS, lw=1.4)
        pc.ax.set_ylabel("Discharge (m³/s)"); pc.ax.set_title("Observed discharge (times in UTC)")
        pc.fig.autofmt_xdate(); pc.canvas.draw_idle()
        l.addWidget(pc)
        l.addWidget(hint(f"{len(s):,} values · {s.index.min()} → {s.index.max()} (UTC) · "
                         f"min {s.min():.1f}, mean {s.mean():.1f}, max {s.max():.1f} m³/s"))
        dlg.exec()

    # ---- page 2: transect ------------------------------------------------
    def _page_transect(self):
        page, lay = self._page("Gauge & transect",
                               "Define the cross-section where modelled flow is extracted and compared with the gauge.")
        top = QHBoxLayout(); top.setSpacing(14)
        left = QVBoxLayout()
        g = QGroupBox("Transect definition"); v = QVBoxLayout(g)
        self.rb_tauto = QRadioButton("Automatic — perpendicular to the flow through a gauge point")
        self.rb_tman = QRadioButton("Manual — two end points")
        grp = QButtonGroup(g); grp.addButton(self.rb_tauto); grp.addButton(self.rb_tman)
        v.addWidget(self.rb_tauto)
        fa = QFormLayout(); fa.setContentsMargins(24, 0, 0, 6)
        self.g_lon = dspin(-180, 180, -0.308351, 6, 0.0001); self.g_lat = dspin(-90, 90, 51.415005, 6, 0.0001)
        self.t_len = dspin(1, 100000, 80, 1, 5, " m"); self.t_rad = dspin(1, 100000, 150, 1, 10, " m")
        fa.addRow("Gauge longitude (WGS84):", self.g_lon); fa.addRow("Gauge latitude (WGS84):", self.g_lat)
        fa.addRow("Transect length:", self.t_len); fa.addRow("Flow-direction search radius:", self.t_rad)
        self.auto_box = QWidget(); self.auto_box.setLayout(fa); v.addWidget(self.auto_box)
        v.addWidget(self.rb_tman)
        fm = QGridLayout(); fm.setContentsMargins(24, 0, 0, 0)
        self.t_wgs = QCheckBox("Coordinates are WGS84 longitude/latitude (otherwise model CRS)")
        self.p0x, self.p0y = dspin(-1e7, 1e7, -0.308528, 6), dspin(-1e7, 1e7, 51.4125, 6)
        self.p1x, self.p1y = dspin(-1e7, 1e7, -0.308496, 6), dspin(-1e7, 1e7, 51.4132, 6)
        fm.addWidget(self.t_wgs, 0, 0, 1, 3)
        fm.addWidget(QLabel("Start (x / lon, y / lat):"), 1, 0); fm.addWidget(self.p0x, 1, 1); fm.addWidget(self.p0y, 1, 2)
        fm.addWidget(QLabel("End (x / lon, y / lat):"), 2, 0); fm.addWidget(self.p1x, 2, 1); fm.addWidget(self.p1y, 2, 2)
        self.man_box = QWidget(); self.man_box.setLayout(fm); v.addWidget(self.man_box)
        self.rb_tauto.toggled.connect(lambda on: (self.auto_box.setEnabled(on), self.man_box.setEnabled(not on)))
        left.addWidget(g)

        g = QGroupBox("Site && export"); f = QFormLayout(g)
        self.site = QLineEdit("Gauge")
        self.gpkg = QCheckBox("Export transect as GeoPackage (GeoJSON is always written)")
        f.addRow("Site name:", self.site); f.addRow("", self.gpkg)
        left.addWidget(g)
        b = QPushButton("Preview transect on mesh"); b.setObjectName("Primary"); b.clicked.connect(self.preview_transect)
        left.addWidget(b)
        self.t_info = hint("Preview checks that the transect crosses the 2D mesh and shows the baseline flow.")
        left.addWidget(self.t_info); left.addStretch()
        top.addLayout(left, 2)

        self.t_plot = PlotCanvas((6, 5)); self.t_plot.setMinimumHeight(430)
        self.t_plot.placeholder("Click “Preview transect on mesh”")
        tg = QGroupBox("Mesh preview"); tl = QVBoxLayout(tg); tl.addWidget(self.t_plot)
        top.addWidget(tg, 3)
        lay.addLayout(top)
        self._nav_buttons(lay, 1)
        return page

    def preview_transect(self):
        cfg = self.collect_config()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            eng = SufiEngine(cfg, Callbacks())
            eng.cb.log = lambda m: None
            geom = eng.geometry_source_path()
            p0, p1 = eng.transect(geom)
            centre = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            L = max(np.hypot(p1[0] - p0[0], p1[1] - p0[1]), 20.0)
            segs = eng.mesh_near(geom, centre, 1.5 * L)
            cut = eng.flow_across_line(cfg["RESULTS_HDF"], geom, p0, p1)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Transect preview", str(e)); return
        QApplication.restoreOverrideCursor()
        pc = self.t_plot; pc.fig.clear()
        ax1 = pc.fig.add_subplot(2, 1, 1); ax2 = pc.fig.add_subplot(2, 1, 2)
        from matplotlib.collections import LineCollection
        ax1.add_collection(LineCollection(segs, colors="#9aa5b1", linewidths=0.6))
        ax1.plot([p0[0], p1[0]], [p0[1], p1[1]], color=COL_BEST, lw=2.4, label="Transect")
        ax1.plot(*centre, "o", color=NAVY, ms=6, label="Centre / gauge")
        ax1.set_aspect("equal"); ax1.set_xlim(centre[0] - 1.5 * L, centre[0] + 1.5 * L)
        ax1.set_ylim(centre[1] - 1.5 * L, centre[1] + 1.5 * L); ax1.legend(loc="upper right", fontsize=8)
        ax1.set_title(f"2D mesh faces (EPSG:{cfg['MODEL_EPSG']})", fontsize=10); ax1.tick_params(labelsize=7)
        ax2.plot(pd.DatetimeIndex(cut.time), cut.q, color=COL_BEST, lw=1.3, label="Model (current results)")
        try:
            obs = read_obs_series(cfg["OBS_PATH"], cfg["OBS_TZ"], cfg["OBS_DAYFIRST"])
            ax2.plot(obs.index, obs.values, color=COL_OBS, lw=1.2, label="Observed")
        except Exception:
            pass
        ax2.set_ylabel("Q (m³/s)"); ax2.grid(True, ls="--", lw=0.5); ax2.legend(fontsize=8); ax2.tick_params(labelsize=7)
        pc.fig.autofmt_xdate(); pc.canvas.draw_idle()
        self.t_info.setText(f"Transect from ({p0[0]:.1f}, {p0[1]:.1f}) to ({p1[0]:.1f}, {p1[1]:.1f}), "
                            f"length {np.hypot(p1[0]-p0[0], p1[1]-p0[1]):.1f} m. Mean modelled discharge "
                            f"{np.nanmean(cut.q):.1f} m³/s.")

    # ---- page 3: parameters ---------------------------------------------
    def _page_params(self):
        page, lay = self._page("Roughness parameters",
                               "Manning's n per land-cover class. Ticked classes are calibrated within their "
                               "lower/upper bounds; the initial value is applied before the baseline run.")
        g = QGroupBox("Land-cover classes"); v = QVBoxLayout(g)
        bar = QHBoxLayout()
        b1 = QPushButton("Load classes from geometry HDF"); b1.clicked.connect(self.load_classes)
        b2 = QPushButton("Add class"); b2.clicked.connect(lambda: self._add_param_row("New class", 0.035, 0.02, 0.06, True))
        b3 = QPushButton("Remove selected"); b3.clicked.connect(self._remove_param_rows)
        b4 = QPushButton("Select all"); b4.clicked.connect(lambda: self._check_all(True))
        b5 = QPushButton("Select none"); b5.clicked.connect(lambda: self._check_all(False))
        for b in (b1, b2, b3, b4, b5):
            bar.addWidget(b)
        bar.addStretch(); v.addLayout(bar)
        self.ptable = QTableWidget(0, 5)
        self.ptable.setHorizontalHeaderLabels(["Calibrate", "Land-cover class", "Initial n", "Lower bound", "Upper bound"])
        hh = self.ptable.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.ptable.verticalHeader().setVisible(False)
        self.ptable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ptable.setMinimumHeight(420)
        v.addWidget(self.ptable)
        self.apply_init = QCheckBox("Apply the initial Manning's n values to the geometry before the baseline evaluation")
        v.addWidget(self.apply_init)
        self.p_count = hint("")
        v.addWidget(self.p_count)
        lay.addWidget(g)
        self._nav_buttons(lay, 2)
        return page

    def _add_param_row(self, name, init, lo, hi, cal):
        r = self.ptable.rowCount(); self.ptable.insertRow(r)
        chk = QCheckBox(); chk.setChecked(cal); chk.stateChanged.connect(self._update_run_count)
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.setAlignment(Qt.AlignCenter); l.addWidget(chk)
        self.ptable.setCellWidget(r, 0, w)
        self.ptable.setItem(r, 1, QTableWidgetItem(name))
        for c, val in ((2, init), (3, lo), (4, hi)):
            s = dspin(0.0, 1.0, float(val), 4, 0.001); s.setFrame(False)
            s.setButtonSymbols(QDoubleSpinBox.NoButtons); s.setAlignment(Qt.AlignCenter)
            self.ptable.setCellWidget(r, c, s)
        self._update_run_count()

    def _row_values(self, r):
        chk = self.ptable.cellWidget(r, 0).findChild(QCheckBox)
        name = (self.ptable.item(r, 1).text() if self.ptable.item(r, 1) else "").strip()
        return (chk.isChecked(), name, self.ptable.cellWidget(r, 2).value(),
                self.ptable.cellWidget(r, 3).value(), self.ptable.cellWidget(r, 4).value())

    def _remove_param_rows(self):
        for r in sorted({i.row() for i in self.ptable.selectedIndexes()}, reverse=True):
            self.ptable.removeRow(r)
        self._update_run_count()

    def _check_all(self, on):
        for r in range(self.ptable.rowCount()):
            self.ptable.cellWidget(r, 0).findChild(QCheckBox).setChecked(on)

    def load_classes(self):
        path = self.geom.text()
        try:
            tbl = read_landcover_table(path)
        except Exception as e:
            QMessageBox.warning(self, "Load classes", f"Could not read the land-cover table:\n{e}"); return
        existing = {self._row_values(r)[1]: self._row_values(r) for r in range(self.ptable.rowCount())}
        self.ptable.setRowCount(0)
        for _, row in tbl.iterrows():
            nm, n = row["name"], float(row["n"])
            if nm in existing:
                cal, _, init, lo, hi = existing[nm]
            else:
                cal, init, lo, hi = True, n, max(0.001, round(n * 0.6, 4)), round(n * 1.6, 4)
            self._add_param_row(nm, init, lo, hi, cal)
        self.statusBar().showMessage(f"Loaded {len(tbl)} land-cover classes from geometry", 5000)

    # ---- page 4: SUFI ---------------------------------------------------
    def _page_sufi(self):
        page, lay = self._page("SUFI-2 settings",
                               "Sequential Uncertainty Fitting: Latin-hypercube sampling, behavioural screening, "
                               "and iterative narrowing of the parameter ranges.")
        row = QHBoxLayout(); row.setSpacing(14)
        g = QGroupBox("Sampling"); f = QFormLayout(g)
        self.n_samples = ispin(2, 10000, 10); self.n_iters = ispin(1, 100, 3)
        self.top_k = ispin(2, 10000, 4); self.shrink = dspin(0.05, 2.0, 0.75, 2, 0.05)
        self.seed = QLineEdit(); self.seed.setPlaceholderText("random")
        f.addRow("Samples per iteration:", self.n_samples); f.addRow("Iterations:", self.n_iters)
        f.addRow("Keep top K runs:", self.top_k); f.addRow("Range shrink factor:", self.shrink)
        f.addRow("Random seed (optional):", self.seed)
        self.run_count = hint(""); f.addRow("", self.run_count)
        for s in (self.n_samples, self.n_iters):
            s.valueChanged.connect(self._update_run_count)
        row.addWidget(g)
        g = QGroupBox("Behavioural thresholds && 95PPU"); f = QFormLayout(g)
        self.use_rmse = QCheckBox("Max RMSE"); self.max_rmse = dspin(0, 1e9, 40, 2, 1, " m³/s")
        self.use_r2 = QCheckBox("Min R²"); self.min_r2 = dspin(-10, 1, 0.70, 3, 0.01)
        self.use_rmse.toggled.connect(self.max_rmse.setEnabled); self.use_r2.toggled.connect(self.min_r2.setEnabled)
        self.q_low = dspin(0, 0.5, 0.025, 3, 0.005); self.q_high = dspin(0.5, 1, 0.975, 3, 0.005)
        self.save_beh = QCheckBox("Keep behavioural time series for the 95PPU band")
        f.addRow(self.use_rmse, self.max_rmse); f.addRow(self.use_r2, self.min_r2)
        f.addRow("Lower PPU quantile:", self.q_low); f.addRow("Upper PPU quantile:", self.q_high)
        f.addRow("", self.save_beh)
        row.addWidget(g)
        lay.addLayout(row)
        g = QGroupBox("How it works"); v = QVBoxLayout(g)
        v.addWidget(hint(
            "Each iteration draws N Latin-hypercube samples of Manning's n within the current ranges, writes them "
            "to the geometry's land-cover table, runs the plan and compares the transect discharge with the "
            "observations. Runs meeting the thresholds are behavioural and form the 95PPU band. The best K runs "
            "set the ranges for the next iteration (median ± shrink × half-range, clipped to the previous "
            "range). Finally the best parameter set is written back and run once more.\n\n"
            "P-factor: fraction of observations inside the 95PPU (ideal → 1). "
            "R-factor: mean band width / std of observations (ideal → small, < 1.5)."))
        lay.addWidget(g)
        self._nav_buttons(lay, 3)
        return page

    def _update_run_count(self, *_):
        if not hasattr(self, "run_count") or not hasattr(self, "ptable"):
            return
        n = self.n_samples.value() * self.n_iters.value() + 1
        k = sum(1 for r in range(self.ptable.rowCount()) if self._row_values(r)[0])
        self.run_count.setText(f"Total HEC-RAS runs: {n} ({self.n_iters.value()} × {self.n_samples.value()} + 1 final)")
        self.p_count.setText(f"{k} of {self.ptable.rowCount()} classes will be calibrated.")

    # ---- page 5: run & results ------------------------------------------
    def _page_run(self):
        page = QWidget(); page.setObjectName("Page")
        lay = QVBoxLayout(page); lay.setContentsMargins(22, 16, 22, 16); lay.setSpacing(10)
        top = QHBoxLayout()
        t = QLabel("Run & results"); t.setObjectName("PageTitle"); top.addWidget(t); top.addStretch()
        self.btn_base = QPushButton("Evaluate baseline only"); self.btn_base.clicked.connect(lambda: self.start(False))
        self.btn_run = QPushButton("▶  Run SUFI-2 calibration"); self.btn_run.setObjectName("Primary")
        self.btn_run.clicked.connect(lambda: self.start(True))
        self.btn_stop = QPushButton("■  Stop"); self.btn_stop.setObjectName("Danger"); self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_open = QPushButton("Open output folder"); self.btn_open.clicked.connect(self.open_output)
        for b in (self.btn_base, self.btn_run, self.btn_stop, self.btn_open):
            top.addWidget(b)
        lay.addLayout(top)

        self.banner = QFrame(); self.banner.setObjectName("Banner"); self.banner.hide()
        bl = QHBoxLayout(self.banner); bl.setContentsMargins(14, 10, 14, 10)
        self.banner_text = QLabel(); self.banner_text.setWordWrap(True)
        bc = QPushButton("Continue"); bc.setObjectName("Primary"); bc.clicked.connect(lambda: self._manual_reply(True))
        bs = QPushButton("Stop"); bs.clicked.connect(lambda: self._manual_reply(False))
        bl.addWidget(self.banner_text, 1); bl.addWidget(bc); bl.addWidget(bs)
        lay.addWidget(self.banner)

        prow = QHBoxLayout()
        self.pbar = QProgressBar(); self.pbar.setValue(0)
        self.pstatus = QLabel("Idle"); self.pstatus.setMinimumWidth(280)
        prow.addWidget(self.pbar, 1); prow.addWidget(self.pstatus)
        lay.addLayout(prow)

        cards = QHBoxLayout(); cards.setSpacing(10)
        self.c_base = Card("Baseline RMSE / R²"); self.c_best = Card("Best RMSE / R²")
        self.c_p = Card("P-factor"); self.c_r = Card("R-factor"); self.c_runs = Card("Runs (behavioural)")
        for c in (self.c_base, self.c_best, self.c_p, self.c_r, self.c_runs):
            cards.addWidget(c)
        lay.addLayout(cards)

        split = QSplitter(Qt.Vertical)
        upper = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        self.pl_hydro = PlotCanvas((8, 4)); self.pl_cloud = PlotCanvas((5, 4)); self.pl_range = PlotCanvas((7, 4))
        self.pl_dotty = PlotCanvas((7, 4))
        self.tabs.addTab(self.pl_hydro, "Hydrograph && 95PPU"); self.tabs.addTab(self.pl_cloud, "RMSE–R² cloud")
        self.tabs.addTab(self.pl_dotty, "Dotty plots"); self.tabs.addTab(self.pl_range, "Parameter ranges")
        upper.addWidget(self.tabs)
        self.rtable = QTableWidget(0, 5); self.rtable.setHorizontalHeaderLabels(["Iter", "Sample", "RMSE", "R²", "Behav."])
        self.rtable.verticalHeader().setVisible(False); self.rtable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rtable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rtable.setSortingEnabled(True)
        upper.addWidget(self.rtable); upper.setSizes([900, 330])
        split.addWidget(upper)
        self.logbox = QPlainTextEdit(); self.logbox.setObjectName("Log"); self.logbox.setReadOnly(True)
        self.logbox.setMaximumBlockCount(20000)
        split.addWidget(self.logbox); split.setSizes([520, 170])
        lay.addWidget(split, 1)
        return page

    # ---- config <-> widgets ---------------------------------------------
    def collect_config(self) -> Dict[str, Any]:
        init, bounds = {}, {}
        for r in range(self.ptable.rowCount()):
            cal, name, n0, lo, hi = self._row_values(r)
            if not name:
                continue
            init[name] = round(n0, 6)
            if cal:
                bounds[name] = [round(lo, 6), round(hi, 6)]
        seed = self.seed.text().strip()
        return {
            "RESULTS_HDF": self.results.text(), "GEOM_HDF": self.geom.text(),
            "PROJECT_PRJ_FILE": self.prj.text(), "PLAN_NAME": self.plan.currentText().strip(),
            "OBS_PATH": self.obs.text(), "OBS_TZ": self.obs_tz.currentText().strip(),
            "OBS_DAYFIRST": self.obs_dayfirst.isChecked(), "MODEL_EPSG": self.epsg.value(),
            "AUTO_TRANSECT": self.rb_tauto.isChecked(),
            "POINT_LONLAT": [self.g_lon.value(), self.g_lat.value()],
            "TRANSECT_LEN_M": self.t_len.value(), "SEARCH_RADIUS_M": self.t_rad.value(),
            "TRANSECT_LONLAT": [[self.p0x.value(), self.p0y.value()], [self.p1x.value(), self.p1y.value()]],
            "TRANSECT_IS_WGS84": self.t_wgs.isChecked(),
            "AUTOMATE_RUNS": self.rb_auto.isChecked(), "RAS_CONTROLLER": self.controller.currentData(),
            "N_SAMPLES": self.n_samples.value(), "N_ITERS": self.n_iters.value(),
            "KEEP_TOP_K": self.top_k.value(), "SHRINK_Q": self.shrink.value(),
            "RANDOM_SEED": int(seed) if seed.isdigit() else None,
            "BEHAVIOR_MAX_RMSE": self.max_rmse.value() if self.use_rmse.isChecked() else None,
            "BEHAVIOR_MIN_R2": self.min_r2.value() if self.use_r2.isChecked() else None,
            "PPU_Q_LOW": self.q_low.value(), "PPU_Q_HIGH": self.q_high.value(),
            "SAVE_BEHAVIOR_TS": self.save_beh.isChecked(), "APPLY_INITIAL_N": self.apply_init.isChecked(),
            "INITIAL_N_BY_NAME": init, "ROUGHNESS_BOUNDS_BY_NAME": bounds,
            "OUT_DIR": self.out_dir.text() or os.path.join(os.path.expanduser("~"), "sufi_outputs"),
            "EXPORT_TRANSECT_GPKG": self.gpkg.isChecked(),
            "TRANSECT_GPKG": f"{self.site.text().strip() or 'transect'}_transect.gpkg",
            "SITE_NAME": self.site.text().strip() or "Gauge",
        }

    def load_config(self, cfg: Dict[str, Any]):
        c = copy.deepcopy(DEFAULT_CONFIG); c.update(cfg or {})
        self.prj.setText(c["PROJECT_PRJ_FILE"]); self._on_prj(c["PROJECT_PRJ_FILE"])
        self.plan.setCurrentText(c["PLAN_NAME"])
        self.results.setText(c["RESULTS_HDF"]); self.geom.setText(c["GEOM_HDF"])
        self.epsg.setValue(int(c["MODEL_EPSG"]))
        self.obs.setText(c["OBS_PATH"]); self.obs_tz.setCurrentText(c["OBS_TZ"] or "")
        self.obs_dayfirst.setChecked(bool(c.get("OBS_DAYFIRST", True)))
        (self.rb_auto if c["AUTOMATE_RUNS"] else self.rb_manual).setChecked(True)
        self.controller.setEnabled(bool(c["AUTOMATE_RUNS"]))
        i = self.controller.findData(c.get("RAS_CONTROLLER", "auto"))
        self.controller.setCurrentIndex(max(i, 0))
        self.out_dir.setText(c["OUT_DIR"] if os.path.isabs(str(c["OUT_DIR"])) else "")
        (self.rb_tauto if c["AUTO_TRANSECT"] else self.rb_tman).setChecked(True)
        self.auto_box.setEnabled(bool(c["AUTO_TRANSECT"])); self.man_box.setEnabled(not c["AUTO_TRANSECT"])
        self.g_lon.setValue(float(c["POINT_LONLAT"][0])); self.g_lat.setValue(float(c["POINT_LONLAT"][1]))
        self.t_len.setValue(float(c["TRANSECT_LEN_M"])); self.t_rad.setValue(float(c.get("SEARCH_RADIUS_M", 150)))
        self.t_wgs.setChecked(bool(c["TRANSECT_IS_WGS84"]))
        for sp in (self.p0x, self.p0y, self.p1x, self.p1y):
            sp.setDecimals(6 if c["TRANSECT_IS_WGS84"] else 2)
        (a, b) = c["TRANSECT_LONLAT"]
        self.p0x.setValue(float(a[0])); self.p0y.setValue(float(a[1]))
        self.p1x.setValue(float(b[0])); self.p1y.setValue(float(b[1]))
        self.site.setText(c.get("SITE_NAME", "Gauge")); self.gpkg.setChecked(bool(c["EXPORT_TRANSECT_GPKG"]))
        self.ptable.setRowCount(0)
        names = list(dict.fromkeys(list(c["INITIAL_N_BY_NAME"].keys()) + list(c["ROUGHNESS_BOUNDS_BY_NAME"].keys())))
        for nm in names:
            n0 = float(c["INITIAL_N_BY_NAME"].get(nm, np.mean(c["ROUGHNESS_BOUNDS_BY_NAME"].get(nm, [0.035, 0.035]))))
            b_ = c["ROUGHNESS_BOUNDS_BY_NAME"].get(nm)
            self._add_param_row(nm, n0, b_[0] if b_ else n0 * 0.6, b_[1] if b_ else n0 * 1.6, b_ is not None)
        self.apply_init.setChecked(bool(c.get("APPLY_INITIAL_N", True)))
        self.n_samples.setValue(int(c["N_SAMPLES"])); self.n_iters.setValue(int(c["N_ITERS"]))
        self.top_k.setValue(int(c["KEEP_TOP_K"])); self.shrink.setValue(float(c["SHRINK_Q"]))
        self.seed.setText("" if c.get("RANDOM_SEED") in (None, "") else str(c["RANDOM_SEED"]))
        self.use_rmse.setChecked(c["BEHAVIOR_MAX_RMSE"] is not None)
        self.max_rmse.setEnabled(c["BEHAVIOR_MAX_RMSE"] is not None)
        if c["BEHAVIOR_MAX_RMSE"] is not None:
            self.max_rmse.setValue(float(c["BEHAVIOR_MAX_RMSE"]))
        self.use_r2.setChecked(c["BEHAVIOR_MIN_R2"] is not None)
        self.min_r2.setEnabled(c["BEHAVIOR_MIN_R2"] is not None)
        if c["BEHAVIOR_MIN_R2"] is not None:
            self.min_r2.setValue(float(c["BEHAVIOR_MIN_R2"]))
        self.q_low.setValue(float(c["PPU_Q_LOW"])); self.q_high.setValue(float(c["PPU_Q_HIGH"]))
        self.save_beh.setChecked(bool(c["SAVE_BEHAVIOR_TS"]))
        self._update_run_count()

    # ---- settings files -------------------------------------------------
    def new_settings(self):
        self.settings_path = None; self.load_config(DEFAULT_CONFIG); self._title()

    def open_settings(self, path: Optional[str] = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open settings", "", "SUFI-2 settings (*.json)")
            if not path:
                return
        with open(path) as f:
            self.load_config(json.load(f))
        self.settings_path = path; self.qsettings.setValue("last_config", path); self._title()
        self.statusBar().showMessage(f"Loaded {path}", 5000)

    def save_settings(self, ask: bool = False):
        if ask or not self.settings_path:
            p, _ = QFileDialog.getSaveFileName(self, "Save settings", self.settings_path or "sufi2_settings.json",
                                               "SUFI-2 settings (*.json)")
            if not p:
                return
            self.settings_path = p
        with open(self.settings_path, "w") as f:
            json.dump(self.collect_config(), f, indent=2)
        self.qsettings.setValue("last_config", self.settings_path); self._title()
        self.statusBar().showMessage(f"Saved {self.settings_path}", 5000)

    def _title(self):
        self.setWindowTitle(f"{APP_NAME} — {os.path.basename(self.settings_path)}" if self.settings_path else APP_NAME)

    def restore_backup(self):
        g = self.geom.text(); bak = g + ".bak"
        if not os.path.exists(bak):
            QMessageBox.information(self, "Restore", f"No backup found:\n{bak}"); return
        if QMessageBox.question(self, "Restore geometry",
                                f"Overwrite\n{g}\nwith the original backup?\n{bak}") == QMessageBox.Yes:
            import shutil
            shutil.copy2(bak, g)
            QMessageBox.information(self, "Restore", "Original geometry restored.")

    # ---- running ----------------------------------------------------------
    def start(self, do_sufi: bool):
        cfg = self.collect_config()
        errs = SufiEngine(cfg, Callbacks()).validate(do_sufi)
        if errs:
            QMessageBox.warning(self, "Check settings", "Please fix the following:\n\n• " + "\n• ".join(errs)); return
        if do_sufi:
            n = cfg["N_SAMPLES"] * cfg["N_ITERS"] + 1
            msg = (f"This will run HEC-RAS {n} times and modify the Manning's n table in:\n{cfg['GEOM_HDF']}\n\n"
                   "A backup (.bak) is created before the first change. Continue?")
            if QMessageBox.question(self, "Start calibration", msg) != QMessageBox.Yes:
                return
        self.history.clear(); self.rtable.setRowCount(0); self.logbox.clear()
        for c in (self.c_base, self.c_best, self.c_p, self.c_r, self.c_runs):
            c.set("—")
        for p in (self.pl_hydro, self.pl_cloud, self.pl_dotty, self.pl_range):
            p.placeholder("Waiting for results…")
        self.pbar.setValue(0); self.pstatus.setText("Starting…")
        self._set_running(True)
        self.thread = QThread(); self.worker = Worker(cfg, do_sufi); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        w = self.worker
        w.log.connect(self._log); w.progress.connect(self._progress); w.baseline.connect(self._baseline)
        w.sample.connect(self._sample); w.iteration.connect(self._iteration)
        w.finished.connect(self._finished); w.failed.connect(self._failed); w.manual.connect(self._manual)
        for sig in (w.finished, w.failed):
            sig.connect(self.thread.quit)
        self.thread.finished.connect(lambda: self._set_running(False))
        self._cfg_running = cfg
        self.thread.start()

    def stop(self):
        if self.worker:
            self.worker.stop(); self.pstatus.setText("Stopping after the current HEC-RAS run…")
            self.banner.hide()

    def _set_running(self, on: bool):
        self.btn_run.setEnabled(not on); self.btn_base.setEnabled(not on); self.btn_stop.setEnabled(on)
        for i in range(4):
            self.stack.widget(i).setEnabled(not on)

    def _manual(self, message):
        self.banner_text.setText("⏸  " + message); self.banner.show()
        QApplication.alert(self)

    def _manual_reply(self, ok):
        self.banner.hide()
        if self.worker:
            self.worker.manual_answer(ok)

    def _log(self, m):
        self.logbox.appendPlainText(m.rstrip()); self.logbox.moveCursor(QTextCursor.End)

    def _progress(self, d, t, s):
        self.pbar.setMaximum(max(t, 1)); self.pbar.setValue(d); self.pstatus.setText(s)

    def _baseline(self, df, m):
        self.c_base.set(f"{m['RMSE']:.2f} / {m['R2']:.3f}")
        pc = self.pl_hydro; pc.reset()
        pc.ax.plot(df.index, df["obs_cms"], color=COL_OBS, lw=1.6, label="Observed")
        pc.ax.plot(df.index, df["model"], color=COL_BEST, lw=1.3, ls="--", label="Baseline model")
        pc.ax.set_ylabel("Discharge (m³/s)"); pc.ax.legend(); pc.ax.set_title("Baseline: model vs observed")
        pc.fig.autofmt_xdate(); pc.canvas.draw_idle()

    def _sample(self, row):
        self.history.append(row)
        self.rtable.setSortingEnabled(False)
        r = self.rtable.rowCount(); self.rtable.insertRow(r)
        vals = [row["iter"], row["sample"], row["RMSE"], row["R2"], "✓" if row["behavior"] else ""]
        for c, v in enumerate(vals):
            it = QTableWidgetItem()
            if isinstance(v, float):
                it.setData(Qt.DisplayRole, None if np.isnan(v) else round(v, 3))
            else:
                it.setData(Qt.DisplayRole, v)
            it.setTextAlignment(Qt.AlignCenter)
            if row["behavior"]:
                it.setBackground(QColor("#e6f4ea"))
            self.rtable.setItem(r, c, it)
        self.rtable.setSortingEnabled(True); self.rtable.scrollToBottom()
        h = pd.DataFrame(self.history)
        nb = int(h["behavior"].sum())
        self.c_runs.set(f"{len(h)} ({nb})")
        ok = h.dropna(subset=["RMSE"])
        if not ok.empty:
            b = ok.sort_values(["RMSE", "R2"], ascending=[True, False]).iloc[0]
            self.c_best.set(f"{b['RMSE']:.2f} / {b['R2']:.3f}")
        self._draw_cloud(h); self._draw_dotty(h)

    def _draw_cloud(self, h):
        cfg = self._cfg_running
        pc = self.pl_cloud; pc.reset()
        beh = h["behavior"] == 1
        pc.ax.scatter(h.loc[~beh, "RMSE"], h.loc[~beh, "R2"], s=28, c=COL_NON, label="Non-behavioural", edgecolors="none")
        pc.ax.scatter(h.loc[beh, "RMSE"], h.loc[beh, "R2"], s=28, c=COL_BEH, label="Behavioural", edgecolors="none")
        if cfg["BEHAVIOR_MAX_RMSE"] is not None:
            pc.ax.axvline(cfg["BEHAVIOR_MAX_RMSE"], ls="--", c="#333", lw=0.8)
        if cfg["BEHAVIOR_MIN_R2"] is not None:
            pc.ax.axhline(cfg["BEHAVIOR_MIN_R2"], ls="--", c="#333", lw=0.8)
        pc.ax.set_xlabel("RMSE (m³/s)"); pc.ax.set_ylabel("R²"); pc.ax.legend(fontsize=8)
        pc.ax.set_title("RMSE–R² cloud"); pc.canvas.draw_idle()

    def _draw_dotty(self, h):
        names = list(self._cfg_running["ROUGHNESS_BOUNDS_BY_NAME"].keys())
        pc = self.pl_dotty; pc.fig.clear()
        n = len(names)
        if n == 0:
            return
        cols = min(4, n); rows = int(np.ceil(n / cols))
        beh = h["behavior"] == 1
        for i, nm in enumerate(names):
            ax = pc.fig.add_subplot(rows, cols, i + 1)
            col = sanitize_colname(nm)
            if col in h:
                ax.scatter(h.loc[~beh, col], h.loc[~beh, "RMSE"], s=10, c=COL_NON, edgecolors="none")
                ax.scatter(h.loc[beh, col], h.loc[beh, "RMSE"], s=10, c=COL_BEH, edgecolors="none")
            ax.set_title(nm, fontsize=7.5); ax.tick_params(labelsize=6.5); ax.grid(True, ls="--", lw=0.4)
            if i % cols == 0:
                ax.set_ylabel("RMSE", fontsize=7)
        pc.canvas.draw_idle()

    def _iteration(self, it, ppu, obs, best, bounds):
        final = it > self._cfg_running["N_ITERS"]
        if ppu is not None:
            self.c_p.set(f"{ppu.p_factor:.2f}"); self.c_r.set(f"{ppu.r_factor:.2f}")
            pc = self.pl_hydro; pc.reset()
            pc.ax.fill_between(ppu.time, ppu.q_low, ppu.q_high, color=COL_PPU, alpha=0.45, lw=0, label="95PPU")
            pc.ax.plot(obs.index, obs.values, color=COL_OBS, lw=1.6, label="Observed")
            if best is not None:
                pc.ax.plot(best.index, best.values, color=COL_BEST, lw=1.3, ls="--", label="Best simulation")
            pc.ax.set_ylabel("Discharge (m³/s)"); pc.ax.legend()
            pc.ax.set_title(f"{'Final' if final else f'Iteration {it}'} — P-factor {ppu.p_factor:.2f}, "
                            f"R-factor {ppu.r_factor:.2f}")
            pc.fig.autofmt_xdate(); pc.canvas.draw_idle()
        if it < self._cfg_running["N_ITERS"]:  # bounds for the next iteration
            self._draw_ranges(it, bounds)

    def _draw_ranges(self, it, bounds):
        if not hasattr(self, "_range_hist"):
            self._range_hist = []
        if it == 1:
            self._range_hist = [{k: tuple(v) for k, v in self._cfg_running["ROUGHNESS_BOUNDS_BY_NAME"].items()}]
        self._range_hist.append(bounds)
        names = list(self._range_hist[0].keys())
        pc = self.pl_range; pc.reset()
        n_it = len(self._range_hist)
        width = 0.8 / n_it
        cmap = matplotlib.colormaps["Blues"]
        for j, b in enumerate(self._range_hist):
            y = np.arange(len(names)) + (j - (n_it - 1) / 2) * width
            lo = np.array([b[nm][0] for nm in names]); hi = np.array([b[nm][1] for nm in names])
            pc.ax.barh(y, hi - lo, left=lo, height=width * 0.9, color=cmap(0.35 + 0.6 * j / max(n_it - 1, 1)),
                       label=f"Iteration {j + 1}")
        pc.ax.set_yticks(np.arange(len(names))); pc.ax.set_yticklabels(names, fontsize=7.5)
        pc.ax.invert_yaxis(); pc.ax.set_xlabel("Manning's n"); pc.ax.legend(fontsize=7, loc="lower right")
        pc.ax.set_title("Parameter ranges by iteration"); pc.canvas.draw_idle()

    def _finished(self, summary):
        self.pbar.setValue(self.pbar.maximum()); self.pstatus.setText("Finished ✓")
        msg = f"Done. Outputs written to:\n{summary.get('out_dir')}"
        if "best_metrics" in summary:
            m = summary["best_metrics"]
            self.c_best.set(f"{m['RMSE']:.2f} / {m['R2']:.3f}")
            msg = (f"Calibration complete.\n\nBest run: RMSE {m['RMSE']:.2f} m³/s, R² {m['R2']:.3f}\n"
                   + (f"P-factor {summary['p_factor']:.2f}, R-factor {summary['r_factor']:.2f}\n"
                      if "p_factor" in summary else "") +
                   f"\nThe best Manning's n set has been written to the geometry.\nOutputs: {summary.get('out_dir')}")
        self.statusBar().showMessage("Finished", 8000)
        QApplication.alert(self)
        QMessageBox.information(self, APP_NAME, msg)

    def _failed(self, msg, stopped):
        self.banner.hide()
        self.pstatus.setText("Stopped" if stopped else "Failed ✗")
        self._log(("\n[STOPPED] " if stopped else "\n[ERROR] ") + msg)
        if not stopped:
            QMessageBox.critical(self, "Calibration failed", msg)

    def open_output(self):
        d = self.out_dir.text()
        if d and os.path.isdir(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        else:
            QMessageBox.information(self, "Output folder", "The output folder does not exist yet.")

    # ---- help -------------------------------------------------------------
    def show_about(self):
        dlg = QDialog(self); dlg.setWindowTitle("About"); dlg.setFixedWidth(520)
        l = QVBoxLayout(dlg)
        lp = logo_path()
        if lp:
            lb = QLabel(); lb.setPixmap(QPixmap(lp).scaledToHeight(80, Qt.SmoothTransformation))
            lb.setAlignment(Qt.AlignCenter); l.addWidget(lb)
        t = QLabel(f"<h2>{APP_NAME}</h2><p>Version {__version__}</p>"
                   f"<p>SUFI-2 automatic calibration of land-cover Manning's n and 95PPU uncertainty analysis "
                   f"for HEC-RAS 2D models.</p>"
                   f"<p>Model: Saeid Najjarghabel<br>{ORG}</p>"
                   f"<p><a href='https://github.com/Saeid-Najjarghabel/HECRAS-SUFI2'>"
                   f"github.com/Saeid-Najjarghabel/HECRAS-SUFI2</a></p>")
        t.setOpenExternalLinks(True); t.setWordWrap(True); t.setAlignment(Qt.AlignCenter); l.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok); bb.accepted.connect(dlg.accept); l.addWidget(bb)
        dlg.exec()

    def show_guide(self):
        dlg = QDialog(self); dlg.setWindowTitle("User guide"); dlg.resize(760, 640)
        l = QVBoxLayout(dlg); tb = QTextBrowser(); tb.setOpenExternalLinks(True)
        tb.setHtml(GUIDE_HTML); l.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.Close); bb.rejected.connect(dlg.reject); l.addWidget(bb)
        dlg.exec()

    def closeEvent(self, e):
        if self.thread and self.thread.isRunning():
            if QMessageBox.question(self, "Quit", "A calibration is running. Stop it and quit?") != QMessageBox.Yes:
                e.ignore(); return
            self.worker.stop(); self.thread.quit(); self.thread.wait(3000)
        e.accept()


GUIDE_HTML = """
<h2>Quick start</h2>
<ol>
<li><b>Project &amp; data</b> — pick the HEC-RAS <code>.prj</code>. Plans are read from the project; choosing a plan fills in
the results and geometry HDF files. Select the observed discharge file (CSV/Excel: column 1 date/time, column 2 m³/s)
and its time zone. Choose <i>Automatic</i> to let the tool drive HEC-RAS, or <i>Manual</i> to run each plan yourself.</li>
<li><b>Gauge &amp; transect</b> — enter the gauge location (WGS84) and transect length, or two end points.
Click <i>Preview transect on mesh</i> to check that the line crosses the channel and that modelled flow looks sensible.</li>
<li><b>Roughness parameters</b> — click <i>Load classes from geometry HDF</i> to list the land-cover classes,
tick the ones to calibrate and set their initial value and bounds.</li>
<li><b>SUFI-2 settings</b> — samples per iteration, iterations, top-K, shrink factor and behavioural thresholds.</li>
<li><b>Run &amp; results</b> — <i>Evaluate baseline only</i> compares the current results with the observations without
running HEC-RAS. <i>Run SUFI-2 calibration</i> performs the full loop. Plots and the run table update live.</li>
</ol>
<h3>Before you run</h3>
<ul>
<li>The plan must write <b>Face Flow</b> to HDF (Unsteady Flow Analysis &rarr; Options &rarr; Output Options &rarr; HDF5 Write Parameters).</li>
<li>The geometry must have a land-cover layer with a Manning's n calibration table.</li>
<li>Close the project in HEC-RAS before an automatic run. A <code>.bak</code> copy of the geometry HDF is made before the first change;
use <i>File &rarr; Restore original geometry</i> to put it back.</li>
</ul>
<h3>Outputs</h3>
<p><code>baseline_model_vs_obs.csv</code>, <code>sufi_iter_XX_summary.csv</code>, <code>sufi_history_all.csv</code>,
<code>sufi_parameter_ranges.csv</code>, <code>best_parameters.json</code>, <code>best_model_vs_obs.csv</code>,
<code>sufi_final_95PPU.csv</code>, 95PPU and RMSE–R² plots (PNG), the transect (GeoJSON/GeoPackage) and <code>run_config.json</code>.</p>
<h3>Indices</h3>
<p><b>P-factor</b>: fraction of observations bracketed by the 95PPU band (closer to 1 is better).
<b>R-factor</b>: average band width divided by the standard deviation of observations (smaller is better; &lt; 1.5 is commonly targeted).</p>
"""


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UWL.HECRAS.SUFI2")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME); app.setOrganizationName(ORG)
    app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    ico = resource_path("app_icon.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
