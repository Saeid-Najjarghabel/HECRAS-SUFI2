"""End-to-end engine test on synthetic data (run: python -m tests.test_engine)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sufi2_gui.engine import SufiEngine, read_landcover_table  # noqa: E402
from tests import synthetic  # noqa: E402


def main():
    d = tempfile.mkdtemp()
    case = synthetic.make(os.path.join(d, "case"))
    names = synthetic.CLASSES
    cfg = {
        "RESULTS_HDF": case["results"], "GEOM_HDF": case["geom"], "PROJECT_PRJ_FILE": case["prj"],
        "PLAN_NAME": "Plan 01", "OBS_PATH": case["obs"], "OBS_TZ": "Europe/London",
        "INITIAL_N_BY_NAME": {n: 0.05 for n in names},
        "ROUGHNESS_BOUNDS_BY_NAME": {n: [0.02, 0.10] for n in names},
        "N_SAMPLES": 12, "N_ITERS": 3, "KEEP_TOP_K": 4, "BEHAVIOR_MAX_RMSE": 30, "BEHAVIOR_MIN_R2": 0.8,
        "OUT_DIR": os.path.join(d, "out"), "RANDOM_SEED": 42,
    }
    eng = SufiEngine(cfg, run_plan=lambda prj, plan: synthetic.simulate(case["geom"], case["results"]))
    p0, p1 = eng.transect(case["geom"])
    print("transect", p0, p1)
    assert abs(p0[0] - p1[0]) < 1.0, "auto transect should run north-south (across eastward flow)"
    s = eng.run()
    print("baseline", s["baseline"])
    print("best", s["best_metrics"], "P", s.get("p_factor"), "R", s.get("r_factor"))
    print("best params", s["best_params"])
    print(sorted(os.listdir(cfg["OUT_DIR"])))
    print(read_landcover_table(case["geom"]))
    assert s["best_metrics"]["R2"] > 0.9


if __name__ == "__main__":
    main()
