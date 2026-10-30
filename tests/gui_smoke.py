"""Drive the GUI headless on synthetic data and save screenshots (QT_QPA_PLATFORM=offscreen)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from sufi2_gui import app as gui, ras_controller  # noqa: E402
from tests import synthetic  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(OUT, exist_ok=True)
d = tempfile.mkdtemp()
case = synthetic.make(os.path.join(d, "case"))
# write a plan file so the .prj parsing is exercised
open(case["prj"], "w").write("Proj Title=Synthetic\nGeom File=g01\nPlan File=p01\n")
open(os.path.join(d, "case", "Synthetic.p01"), "w").write("Plan Title=Plan 01 calibration\nGeom File=g01\n")
ras_controller.run_plan = lambda prj, plan, pid, log=None: synthetic.simulate(case["geom"], case["results"])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN", a[2]))
QMessageBox.critical = staticmethod(lambda *a, **k: print("CRIT", a[2]))

qapp = QApplication(sys.argv)
qapp.setStyle("Fusion"); qapp.setStyleSheet(gui.STYLE)
w = gui.MainWindow(); w.resize(1360, 880); w.show()
w.prj.setText(case["prj"]); w._on_prj(case["prj"])
w.obs.setText(case["obs"]); w.out_dir.setText(os.path.join(d, "out"))
w.load_classes()
w.n_samples.setValue(10); w.n_iters.setValue(3); w.seed.setText("7")
w.max_rmse.setValue(30); w.min_r2.setValue(0.8)
print("plan:", w.plan.currentText(), "| results:", w.results.text())


def shot(name):
    qapp.processEvents()
    w.grab().save(os.path.join(OUT, name + ".png"))


def step():
    for i, nm in enumerate(["1_project", "2_transect", "3_params", "4_sufi"]):
        w.nav.setCurrentRow(i)
        if i == 1:
            w.preview_transect()
        shot(nm)
    w.nav.setCurrentRow(4)
    w.start(True)
    poll()


def poll():
    if w.thread and w.thread.isRunning():
        QTimer.singleShot(200, poll); return
    qapp.processEvents()
    for i, nm in enumerate(["5_results_ppu", "5_results_cloud", "5_results_dotty", "5_results_ranges"]):
        w.tabs.setCurrentIndex(i); shot(nm)
    print("status:", w.pstatus.text(), "| best:", w.c_best.value.text(), "| P:", w.c_p.value.text(),
          "| runs:", w.c_runs.value.text())
    print(sorted(os.listdir(os.path.join(d, "out"))))
    qapp.quit()


QTimer.singleShot(300, step)
qapp.exec()
