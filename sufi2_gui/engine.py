# -*- coding: utf-8 -*-
"""
HEC-RAS SUFI-2 calibration engine.

Refactored from HECRAS_SUFI_Calibration.py (S. Najjarghabel, 2025) so that it can be
driven from a graphical interface:

* all settings come from a config dict (no module-level paths),
* progress, log lines, per-sample results and plots are reported through callbacks,
* a run can be stopped cleanly between HEC-RAS simulations,
* "manual" mode asks the interface to pause instead of calling input(),
* face geometry is read once and cached (it does not change with Manning's n).
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import shutil
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import h5py
import numpy as np
import pandas as pd

from . import ras_controller

# ---------------------------------------------------------------------------
# Default configuration (mirrors the CONFIG block of the original script)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    # --- Required inputs ---
    "RESULTS_HDF": "",
    "GEOM_HDF": "",
    "PROJECT_PRJ_FILE": "",
    "PLAN_NAME": "",
    "OBS_PATH": "",
    "OBS_TZ": "Europe/London",
    "OBS_DAYFIRST": True,
    "MODEL_EPSG": 27700,
    # --- Section definition ---
    "AUTO_TRANSECT": True,
    "POINT_LONLAT": [-0.308351, 51.415005],
    "TRANSECT_LEN_M": 80.0,
    "SEARCH_RADIUS_M": 150.0,
    "TRANSECT_LONLAT": [[-0.308528, 51.412500], [-0.308496, 51.413200]],
    "TRANSECT_IS_WGS84": True,
    # --- SUFI settings ---
    "DO_SUFI": True,
    "AUTOMATE_RUNS": True,
    "RAS_CONTROLLER": "auto",
    "N_SAMPLES": 10,
    "N_ITERS": 3,
    "KEEP_TOP_K": 4,
    "SHRINK_Q": 0.75,
    "RANDOM_SEED": None,
    "BEHAVIOR_MAX_RMSE": 40.0,
    "BEHAVIOR_MIN_R2": 0.70,
    "PPU_Q_LOW": 0.025,
    "PPU_Q_HIGH": 0.975,
    "SAVE_BEHAVIOR_TS": True,
    "APPLY_INITIAL_N": True,
    "INITIAL_N_BY_NAME": {
        "NoData": 0.035, "Developed - Low Intensity": 0.030,
        "Developed - Medium Intensity": 0.030, "Barren Land": 0.020,
        "Open Water": 0.025, "Unclassified": 0.035,
        "Developed - Open Space": 0.030, "Palustrine Scrub-Shrub Wetland": 0.050,
        "Developed - High Intensity": 0.025, "Grassland-Herbaceous": 0.035,
        "Evergreen Forest": 0.080, "Palustrine Emergent Wetland": 0.075,
        "Deciduous Forest": 0.070, "Pasture-Hay": 0.035,
        "Cultivated Crops": 0.040, "Palustrine Forested Wetland": 0.100,
        "Scrub-Shrub": 0.040,
    },
    "ROUGHNESS_BOUNDS_BY_NAME": {
        "Developed - Low Intensity": [0.020, 0.050], "Developed - Medium Intensity": [0.020, 0.050],
        "Developed - High Intensity": [0.018, 0.045], "Developed - Open Space": [0.020, 0.050],
        "Grassland-Herbaceous": [0.025, 0.060], "Pasture-Hay": [0.025, 0.060],
        "Cultivated Crops": [0.025, 0.060], "Evergreen Forest": [0.050, 0.120],
        "Deciduous Forest": [0.045, 0.110], "Palustrine Emergent Wetland": [0.040, 0.120],
        "Palustrine Scrub-Shrub Wetland": [0.030, 0.090], "Scrub-Shrub": [0.025, 0.070],
        "Barren Land": [0.015, 0.035], "Open Water": [0.020, 0.040],
        "Unclassified": [0.025, 0.060], "NoData": [0.025, 0.060],
    },
    # --- Outputs ---
    "OUT_DIR": "sufi_outputs",
    "EXPORT_TRANSECT_GPKG": True,
    "TRANSECT_GPKG": "transect.gpkg",
    "SITE_NAME": "Gauge",
}

LANDCOVER_TABLE = "/Geometry/Land Cover (Manning's n)/Calibration Table"


# ---------------------------------------------------------------------------
# Data classes & callbacks
# ---------------------------------------------------------------------------
@dataclass
class FaceFlowCut:
    time: np.ndarray
    q: np.ndarray


@dataclass
class UncertaintyResult:
    time: pd.DatetimeIndex
    q_low: np.ndarray
    q_high: np.ndarray
    p_factor: float
    r_factor: float


class CalibrationStopped(Exception):
    """Raised when the user stops a calibration."""


class Callbacks:
    """Override any of these in the interface. Defaults print to the console."""

    def log(self, msg: str) -> None:
        print(msg)

    def progress(self, done: int, total: int, text: str) -> None:
        pass

    def baseline(self, df: pd.DataFrame, metrics: Dict[str, float]) -> None:
        pass

    def sample(self, row: Dict[str, Any]) -> None:
        pass

    def iteration(self, it: int, ppu: Optional[UncertaintyResult], obs: pd.Series,
                  best: Optional[pd.Series], bounds: Dict[str, Tuple[float, float]]) -> None:
        pass

    def finished(self, summary: Dict[str, Any]) -> None:
        pass

    def wait_for_manual_run(self, message: str) -> bool:
        """Return True to continue, False to stop. Default: console prompt."""
        input(message + " Press Enter to continue... ")
        return True

    def should_stop(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Metrics & sampling
# ---------------------------------------------------------------------------
def rmse(y_true, y_pred) -> float:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2))) if m.any() else np.nan


def r2(y_true, y_pred) -> float:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if m.sum() < 2:
        return np.nan
    ss_res = np.sum((y_true[m] - y_pred[m]) ** 2)
    ss_tot = np.sum((y_true[m] - np.mean(y_true[m])) ** 2)
    return float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan


def nse(y_true, y_pred) -> float:
    """Nash-Sutcliffe efficiency (reported for information)."""
    return r2(y_true, y_pred)


def pbias(y_true, y_pred) -> float:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    s = np.sum(y_true[m])
    return float(100.0 * np.sum(y_pred[m] - y_true[m]) / s) if m.any() and s != 0 else np.nan


def latin_hypercube(n: int, d: int, rng: np.random.Generator) -> np.ndarray:
    cut = np.linspace(0, 1, n + 1)
    u = rng.random((n, d))
    a, b = cut[:n], cut[1:n + 1]
    pts = u * (b - a)[:, None] + a[:, None]
    for j in range(d):
        rng.shuffle(pts[:, j])
    return pts


def sample_params_by_name(bounds: Dict[str, Tuple[float, float]], n_samples: int,
                          rng: np.random.Generator) -> List[Dict[str, float]]:
    names = list(bounds.keys())
    L = np.array([bounds[n][0] for n in names], float)
    U = np.array([bounds[n][1] for n in names], float)
    X = latin_hypercube(n_samples, len(names), rng)
    vals = L + X * (U - L)
    return [{names[j]: float(vals[k, j]) for j in range(len(names))} for k in range(n_samples)]


def sanitize_colname(name: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]+", "_", name).lower()


# ---------------------------------------------------------------------------
# Observations & projections
# ---------------------------------------------------------------------------
def read_obs_series(path: str, tz: str = "UTC", dayfirst: bool = True) -> pd.Series:
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Observation file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    df = pd.read_excel(path, header=None) if ext in (".xls", ".xlsx") else pd.read_csv(path, header=None)
    t = pd.to_datetime(df.iloc[:, 0].astype(str), dayfirst=dayfirst, errors="coerce")
    if tz:
        t = (t.dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT")
              .dt.tz_convert("UTC").dt.tz_localize(None))
    q = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s = pd.Series(q.values, index=t, name="obs_cms")
    s = s[s.index.notna()].dropna()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    if s.empty:
        raise ValueError("No valid (time, discharge) rows found in the observation file. "
                         "Expected column 1 = date/time, column 2 = discharge (m³/s).")
    return s


def project_point(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    from pyproj import Transformer
    tf = Transformer.from_crs(4326, int(epsg), always_xy=True)
    x, y = tf.transform(lon, lat)
    return float(x), float(y)


def unproject_point(x: float, y: float, epsg: int) -> Tuple[float, float]:
    from pyproj import Transformer
    tf = Transformer.from_crs(int(epsg), 4326, always_xy=True)
    lon, lat = tf.transform(x, y)
    return float(lon), float(lat)


# ---------------------------------------------------------------------------
# HDF5 helpers
# ---------------------------------------------------------------------------
def _walk_datasets(h5obj, path: str = "/"):
    if hasattr(h5obj, "keys"):
        for k, v in h5obj.items():
            p = f"{path.rstrip('/')}/{k}"
            if isinstance(v, h5py.Group):
                yield from _walk_datasets(v, p)
            else:
                yield p, v


def read_landcover_table(geom_hdf_path: str) -> pd.DataFrame:
    """Return the land-cover calibration table (name, base Manning's n)."""
    with h5py.File(geom_hdf_path, "r") as g:
        if LANDCOVER_TABLE not in g:
            raise KeyError(f"'{LANDCOVER_TABLE}' not found in {geom_hdf_path}. "
                           "Is a land-cover layer associated with this geometry?")
        data = g[LANDCOVER_TABLE][:]
    names = [n.decode("utf-8", "ignore").strip() if isinstance(n, bytes) else str(n)
             for n in data["Land Cover Name"]]
    return pd.DataFrame({"name": names, "n": data["Base Manning's n Value"].astype(float)})


def list_2d_areas(geom_hdf_path: str) -> List[str]:
    with h5py.File(geom_hdf_path, "r") as g:
        grp = g.get("/Geometry/2D Flow Areas")
        if grp is None:
            return []
        return [k for k, v in grp.items() if isinstance(v, h5py.Group)]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class SufiEngine:
    def __init__(self, config: Dict[str, Any], callbacks: Optional[Callbacks] = None,
                 run_plan: Optional[Callable[[str, str], None]] = None):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg.update(copy.deepcopy(config or {}))
        self.cfg = cfg
        self.cb = callbacks or Callbacks()
        self._run_plan_override = run_plan
        self._geom_cache: Dict[str, Any] = {}
        seed = cfg.get("RANDOM_SEED")
        self.rng = np.random.default_rng(None if seed in (None, "") else int(seed))
        self.out_dir = os.path.abspath(cfg["OUT_DIR"] or "sufi_outputs")

    # ---- small utilities -------------------------------------------------
    def log(self, msg: str) -> None:
        self.cb.log(msg)

    def _check_stop(self) -> None:
        if self.cb.should_stop():
            raise CalibrationStopped("Calibration stopped by user.")

    def _out(self, name: str) -> str:
        return os.path.join(self.out_dir, name)

    # ---- validation --------------------------------------------------------
    def validate(self, need_sufi: bool) -> List[str]:
        c, errs = self.cfg, []
        if not os.path.isfile(c["RESULTS_HDF"]):
            errs.append("Results HDF file not found.")
        if not os.path.isfile(c["OBS_PATH"]):
            errs.append("Observation file not found.")
        if c["GEOM_HDF"] and not os.path.isfile(c["GEOM_HDF"]):
            errs.append("Geometry HDF file not found.")
        if need_sufi:
            if not c["ROUGHNESS_BOUNDS_BY_NAME"]:
                errs.append("No calibration parameters defined.")
            for nm, (lo, hi) in c["ROUGHNESS_BOUNDS_BY_NAME"].items():
                if not (0 < float(lo) < float(hi)):
                    errs.append(f"Invalid bounds for '{nm}': lower must be > 0 and < upper.")
            if c["AUTOMATE_RUNS"]:
                if not os.path.isfile(c["PROJECT_PRJ_FILE"]):
                    errs.append("HEC-RAS project (.prj) not found (required for automated runs).")
                if not str(c["PLAN_NAME"]).strip():
                    errs.append("Plan name is required for automated runs.")
            if int(c["KEEP_TOP_K"]) < 2:
                errs.append("'Keep top K' must be at least 2 to update parameter ranges.")
            if not (0 <= float(c["PPU_Q_LOW"]) < float(c["PPU_Q_HIGH"]) <= 1):
                errs.append("PPU quantiles must satisfy 0 ≤ low < high ≤ 1.")
        return errs

    # ---- geometry --------------------------------------------------------
    def geometry_source_path(self) -> str:
        geom = self.cfg["GEOM_HDF"]
        if geom and os.path.exists(geom):
            return geom
        results = self.cfg["RESULTS_HDF"]
        base_dir = os.path.dirname(results)
        parts = os.path.basename(results).split(".")
        if len(parts) >= 3:
            pattern = f"*.{parts[1]}.hdf"
            for d in (base_dir, os.path.join(base_dir, "..")):
                hits = glob.glob(os.path.join(d, pattern))
                if hits:
                    self.log(f"[INFO] Using companion plan file for geometry: {hits[0]}")
                    return hits[0]
        raise FileNotFoundError("Could not find a geometry source. Please set the Geometry HDF file.")

    def face_geometry(self, geom_path: str):
        if geom_path in self._geom_cache:
            return self._geom_cache[geom_path]
        import shapely.geometry as sg
        from shapely.strtree import STRtree

        with h5py.File(geom_path, "r") as g:
            parent = g["/Geometry/2D Flow Areas"]
            grp = next((v for v in parent.values() if isinstance(v, h5py.Group)), None)
            if grp is None:
                raise IOError("No 2D Flow Area sub-group found in '/Geometry/2D Flow Areas'.")
            self.log(f"[INFO] Using 2D flow area: '{grp.name}'")
            names = list(grp.keys())
            low = [n.lower().replace(" ", "") for n in names]

            def find(keys, required=True):
                for i, nm in enumerate(low):
                    if all(k.lower() in nm for k in keys):
                        return names[i]
                if required:
                    raise IOError(f"Dataset with keywords {keys} not found in {grp.name}. Available: {names}")
                return None

            face_xy = np.array(grp[find(["FacePoints", "Coordinate"])])
            faces_idx = np.array(grp[find(["Faces", "FacePoint", "Indexes"])], dtype=int)
            nname = find(["Faces", "NormalUnitVector", "Length"], required=False)
            normals = np.array(grp[nname]) if nname else None

        segs = [sg.LineString([tuple(face_xy[s]), tuple(face_xy[e])]) for s, e in faces_idx[:, :2]]
        tree = STRtree(segs)
        vecs = np.array([face_xy[e] - face_xy[s] for s, e in faces_idx[:, :2]], float)
        vecs /= (np.linalg.norm(vecs, axis=1)[:, None] + 1e-12)
        self._geom_cache[geom_path] = (face_xy, faces_idx, normals, segs, tree, vecs)
        self.log(f"[INFO] Geometry loaded: {len(segs):,} faces.")
        return self._geom_cache[geom_path]

    # ---- results ---------------------------------------------------------
    def face_flows(self, results_path: str) -> Tuple[str, np.ndarray]:
        with h5py.File(results_path, "r") as f:
            for p, ds in _walk_datasets(f, "/"):
                if p.split("/")[-1].lower() in ("face flows", "face flow") and ds.ndim == 2:
                    return p, np.array(ds)
        raise RuntimeError("'Face Flows' dataset not found in the results file. "
                           "Enable 'Face Flow' output in HEC-RAS (Output Options > HDF5 Write Parameters).")

    def time_stamps(self, results_path: str, hint: Optional[str] = None) -> pd.DatetimeIndex:
        with h5py.File(results_path, "r") as f:
            cands = []
            for p, ds in _walk_datasets(f, "/"):
                nm = p.split("/")[-1].lower()
                if (("time" in nm and "stamp" in nm) or "time strings" in nm) and ds.ndim == 1 and ds.shape[0] > 0:
                    cands.append(p)
            if not cands:
                raise RuntimeError("No timestamp dataset found in the results file.")
            if hint and len(cands) > 1:
                cands.sort(key=lambda c: len(os.path.commonpath([os.path.dirname(c), os.path.dirname(hint)])),
                           reverse=True)
            raw = f[cands[0]][:]
        if raw.dtype.kind in ("S", "O"):
            ts = [t.decode("utf-8").strip() if isinstance(t, bytes) else str(t).strip() for t in raw]
            # HEC-RAS format e.g. "01JAN2020 00:00:00:000" -> make the ms separator a dot
            ts = [s.rpartition(":")[0] + "." + s.rpartition(":")[2] if ":" in s[-4:] else s for s in ts]
            try:
                return pd.to_datetime(ts, format="%d%b%Y %H:%M:%S.%f")
            except (ValueError, TypeError):
                return pd.to_datetime(ts)
        return pd.to_datetime(raw)

    def flow_across_line(self, results_path: str, geom_path: str, p0, p1) -> FaceFlowCut:
        import shapely.geometry as sg
        face_xy, faces_idx, normals, segs, tree, _ = self.face_geometry(geom_path)
        data_path, flows = self.face_flows(results_path)
        times = self.time_stamps(results_path, hint=data_path)

        line = sg.LineString([p0, p1])
        idxs = sorted(i for i in set(np.atleast_1d(tree.query(line)).tolist()) if segs[i].intersects(line))
        if not idxs:
            raise RuntimeError("The transect does not intersect any 2D faces — move or lengthen it across the channel.")
        idxs = np.array(idxs, int)
        v = np.array([p1[0] - p0[0], p1[1] - p0[1]], float)
        n_tr = np.array([-v[1], v[0]], float)
        n_tr /= (np.linalg.norm(n_tr) + 1e-12)
        if normals is not None:
            signs = np.sign(normals[idxs, :2] @ n_tr)
            signs[signs == 0] = 1.0
        else:
            warnings.warn("Face normals not found; flow direction assumed.")
            signs = np.ones(len(idxs))
        q = (flows[:, idxs] * signs).sum(axis=1)
        if len(q) != len(times):
            raise ValueError(f"Flow length ({len(q)}) != time length ({len(times)}). Check HDF5 output options.")
        # Report positive discharge regardless of the user's drawing direction
        if np.nanmean(q) < 0:
            q = -q
        return FaceFlowCut(time=times.values, q=q)

    def auto_transect(self, results_path: str, geom_path: str, p_xy, length_m: float,
                      radius_m: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Build a transect through p_xy, perpendicular to the local mean flow direction.

        Note: the original script rotated the flow-weighted *face-edge* direction by 90°.
        Face edges already run across the flow, so that produced a line along the river.
        Here the flow direction is taken from the face normals (positive flow = along the
        normal), and the transect is drawn perpendicular to it. Without normals, the
        dominant edge direction (weighted by |q|) is used directly as the transect direction.
        """
        import shapely.geometry as sg
        _, _, normals, segs, tree, vecs = self.face_geometry(geom_path)
        _, flows = self.face_flows(results_path)
        q_mean = np.nanmean(flows, axis=0)
        cand = np.atleast_1d(tree.query(sg.Point(p_xy).buffer(radius_m)))
        if cand.size == 0:
            raise RuntimeError("No faces near the gauge point — check the coordinates/EPSG or enlarge the search radius.")
        if normals is not None:
            F = (normals[cand, :2] * q_mean[cand][:, None]).sum(axis=0)  # mean flow vector
            if np.linalg.norm(F) < 1e-12:
                raise RuntimeError("Mean flow near the gauge point is zero — cannot infer flow direction.")
            F /= np.linalg.norm(F)
            D = np.array([-F[1], F[0]])  # across the flow
        else:
            w = np.abs(q_mean[cand])
            T = (vecs[cand].T * w) @ vecs[cand]  # sign-free structure tensor of edge directions
            D = np.linalg.eigh(T)[1][:, -1]
        D /= (np.linalg.norm(D) + 1e-12)
        h = 0.5 * float(length_m)
        return (p_xy[0] - h * D[0], p_xy[1] - h * D[1]), (p_xy[0] + h * D[0], p_xy[1] + h * D[1])

    def mesh_near(self, geom_path: str, centre, radius_m: float):
        """Face segments within radius of centre (for the transect preview map)."""
        import shapely.geometry as sg
        face_xy, faces_idx, _, segs, tree, _ = self.face_geometry(geom_path)
        cand = np.atleast_1d(tree.query(sg.Point(centre).buffer(radius_m)))
        return np.array([[face_xy[faces_idx[i, 0]], face_xy[faces_idx[i, 1]]] for i in cand])

    def transect(self, geom_path: str):
        c = self.cfg
        if c["AUTO_TRANSECT"]:
            x, y = project_point(float(c["POINT_LONLAT"][0]), float(c["POINT_LONLAT"][1]), c["MODEL_EPSG"])
            return self.auto_transect(c["RESULTS_HDF"], geom_path, (x, y), c["TRANSECT_LEN_M"], c["SEARCH_RADIUS_M"])
        pts = c["TRANSECT_LONLAT"]
        if c["TRANSECT_IS_WGS84"]:
            return (project_point(float(pts[0][0]), float(pts[0][1]), c["MODEL_EPSG"]),
                    project_point(float(pts[1][0]), float(pts[1][1]), c["MODEL_EPSG"]))
        return (float(pts[0][0]), float(pts[0][1])), (float(pts[1][0]), float(pts[1][1]))

    # ---- Manning's n update ---------------------------------------------
    def update_mannings(self, geom_path: str, mapping: Dict[str, float], backup: bool) -> None:
        if backup:
            bkp = geom_path + ".bak"
            if not os.path.exists(bkp):
                shutil.copy2(geom_path, bkp)
                self.log(f"[BACKUP] Original geometry saved to: {bkp}")
        with h5py.File(geom_path, "r+") as g:
            ds = g[LANDCOVER_TABLE]
            data = ds[:]
            names = np.array([n.decode("utf-8", "ignore").strip() if isinstance(n, bytes) else str(n)
                              for n in data["Land Cover Name"]])
            values = data["Base Manning's n Value"].astype(float)
            missing, changed = [], 0
            for nm, val in mapping.items():
                idx = np.where(names == nm)[0]
                if idx.size:
                    if abs(values[idx[0]] - float(val)) > 1e-9:
                        values[idx[0]] = float(val)
                        changed += 1
                else:
                    missing.append(nm)
            if changed:
                data["Base Manning's n Value"] = values
                ds[...] = data
            if missing:
                self.log(f"[WARN] Land-cover classes not in geometry (ignored): {', '.join(missing)}")
        self.log(f"    Manning's n updated for {changed} class(es).")

    # ---- HEC-RAS -----------------------------------------------------------
    def run_plan(self) -> None:
        c = self.cfg
        if self._run_plan_override is not None:
            self._run_plan_override(c["PROJECT_PRJ_FILE"], c["PLAN_NAME"])
            return
        if c["AUTOMATE_RUNS"]:
            ras_controller.run_plan(c["PROJECT_PRJ_FILE"], c["PLAN_NAME"], c["RAS_CONTROLLER"], log=self.log)
        else:
            if not self.cb.wait_for_manual_run(
                    f"Run plan '{c['PLAN_NAME']}' in HEC-RAS with the updated Manning's n values, "
                    f"then click Continue."):
                raise CalibrationStopped("Calibration stopped by user.")

    # ---- evaluation --------------------------------------------------------
    def evaluate(self, geom_path: str, p0, p1, obs: pd.Series):
        cut = self.flow_across_line(self.cfg["RESULTS_HDF"], geom_path, p0, p1)
        q_mod = pd.Series(cut.q, index=pd.DatetimeIndex(cut.time), name="model")
        q_mod = q_mod[~q_mod.index.duplicated()]
        df = pd.concat([q_mod, obs], axis=1).dropna()
        if df.empty:
            raise RuntimeError("Model and observation time series do not overlap. "
                               "Check the observation time zone and the simulation window.")
        met = {"RMSE": rmse(df["obs_cms"], df["model"]), "R2": r2(df["obs_cms"], df["model"]),
               "PBIAS": pbias(df["obs_cms"], df["model"]), "N": int(len(df))}
        # model series on observation timestamps (interpolated) for PPU
        full = q_mod.reindex(q_mod.index.union(obs.index)).interpolate("time", limit_area="inside")
        return df, met, full.reindex(obs.index)

    def is_behavioral(self, rmse_v: float, r2_v: float) -> bool:
        c = self.cfg
        if c["BEHAVIOR_MAX_RMSE"] not in (None, "") and (np.isnan(rmse_v) or rmse_v > float(c["BEHAVIOR_MAX_RMSE"])):
            return False
        if c["BEHAVIOR_MIN_R2"] not in (None, "") and (np.isnan(r2_v) or r2_v < float(c["BEHAVIOR_MIN_R2"])):
            return False
        return True

    @staticmethod
    def compute_ppu(ensemble: List[pd.Series], obs: pd.Series, q_low: float, q_high: float) -> UncertaintyResult:
        M = np.column_stack([s.reindex(obs.index).values for s in ensemble])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            qL, qU = np.nanquantile(M, [q_low, q_high], axis=1)
        y = obs.values
        valid = np.isfinite(y) & np.isfinite(qL)
        inside = (y >= qL) & (y <= qU) & valid
        p = inside.sum() / valid.sum() if valid.any() else 0.0
        sd = np.nanstd(y[valid]) if valid.any() else np.nan
        r = float(np.nanmean(qU - qL) / sd) if sd and np.isfinite(sd) else np.nan
        return UncertaintyResult(time=obs.index, q_low=qL, q_high=qU, p_factor=float(p), r_factor=r)

    # ---- plots (saved to disk) ------------------------------------------
    def save_ppu_plot(self, ppu, obs, best, title, fname):
        import matplotlib
        matplotlib.use("Agg", force=False)
        from matplotlib.figure import Figure
        fig = Figure(figsize=(12, 5))
        ax = fig.add_subplot(111)
        ax.fill_between(ppu.time, ppu.q_low, ppu.q_high, color="#9aa5b1", alpha=0.45, label="95PPU", lw=0)
        ax.plot(obs.index, obs.values, color="#1f4e79", lw=1.6, label="Observed")
        if best is not None:
            ax.plot(best.index, best.values, color="#c0392b", lw=1.3, ls="--", label="Best simulation")
        ax.grid(True, ls="--", lw=0.5)
        ax.set_ylabel("Discharge (m³/s)")
        ax.set_title(f"{title}  |  P-factor={ppu.p_factor:.3f}, R-factor={ppu.r_factor:.3f}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(self._out(fname), dpi=200)
        self.log(f"[PLOT] {fname}")

    def save_cloud_plot(self, hist: pd.DataFrame, fname: str):
        from matplotlib.figure import Figure
        fig = Figure(figsize=(6.2, 5.2))
        ax = fig.add_subplot(111)
        beh = hist["behavior"] == 1
        ax.scatter(hist.loc[~beh, "RMSE"], hist.loc[~beh, "R2"], s=22, c="#9aa5b1", label="Non-behavioral")
        ax.scatter(hist.loc[beh, "RMSE"], hist.loc[beh, "R2"], s=22, c="#2e8b57", label="Behavioral")
        if self.cfg["BEHAVIOR_MAX_RMSE"] not in (None, ""):
            ax.axvline(float(self.cfg["BEHAVIOR_MAX_RMSE"]), ls="--", c="k", lw=0.8)
        if self.cfg["BEHAVIOR_MIN_R2"] not in (None, ""):
            ax.axhline(float(self.cfg["BEHAVIOR_MIN_R2"]), ls="--", c="k", lw=0.8)
        ax.set_xlabel("RMSE (m³/s)"); ax.set_ylabel("R²")
        ax.grid(True, ls="--", lw=0.5); ax.legend(); ax.set_title("RMSE–R² cloud")
        fig.tight_layout(); fig.savefig(self._out(fname), dpi=200)
        self.log(f"[PLOT] {fname}")

    def export_transect(self, p0, p1) -> None:
        c = self.cfg
        epsg = int(c["MODEL_EPSG"])
        gj = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": f"EPSG:{epsg}"}},
              "features": [{"type": "Feature", "properties": {"name": f"{c['SITE_NAME']}_transect"},
                            "geometry": {"type": "LineString", "coordinates": [list(p0), list(p1)]}}]}
        with open(self._out("transect.geojson"), "w") as f:
            json.dump(gj, f, indent=2)
        if c["EXPORT_TRANSECT_GPKG"]:
            try:
                import geopandas as gpd
                from shapely.geometry import LineString
                gdf = gpd.GeoDataFrame([{"name": f"{c['SITE_NAME']}_transect"}],
                                       geometry=[LineString([p0, p1])], crs=f"EPSG:{epsg}")
                gdf.to_file(self._out(c["TRANSECT_GPKG"] or "transect.gpkg"), layer="transect", driver="GPKG")
                self.log(f"[OUT] Transect exported: {c['TRANSECT_GPKG']}")
            except Exception as e:  # geopandas optional
                self.log(f"[WARN] GeoPackage export skipped ({e}); GeoJSON written instead.")

    # ---- main entry points ----------------------------------------------
    def run(self, do_sufi: Optional[bool] = None) -> Dict[str, Any]:
        c = self.cfg
        do_sufi = c["DO_SUFI"] if do_sufi is None else do_sufi
        errs = self.validate(do_sufi)
        if errs:
            raise ValueError("Please fix the following:\n• " + "\n• ".join(errs))
        os.makedirs(self.out_dir, exist_ok=True)
        with open(self._out("run_config.json"), "w") as f:
            json.dump(c, f, indent=2, default=str)

        geom = self.geometry_source_path()
        self.log(f"[INFO] Geometry: {geom}")
        self.log(f"[INFO] Results:  {c['RESULTS_HDF']}")
        obs = read_obs_series(c["OBS_PATH"], tz=c["OBS_TZ"], dayfirst=c.get("OBS_DAYFIRST", True))
        self.log(f"[INFO] Observations: {len(obs):,} values, {obs.index.min()} → {obs.index.max()}")

        if c["APPLY_INITIAL_N"] and c["INITIAL_N_BY_NAME"]:
            self.log("[INFO] Applying initial Manning's n values…")
            self.update_mannings(geom, c["INITIAL_N_BY_NAME"], backup=True)

        p0, p1 = self.transect(geom)
        self.log(f"[INFO] Transect (EPSG:{c['MODEL_EPSG']}): ({p0[0]:.1f}, {p0[1]:.1f}) → ({p1[0]:.1f}, {p1[1]:.1f})")
        self.export_transect(p0, p1)

        df, met, _ = self.evaluate(geom, p0, p1, obs)
        df.to_csv(self._out("baseline_model_vs_obs.csv"))
        self.log(f"[METRICS] Baseline (current results): RMSE={met['RMSE']:.2f} m³/s, R²={met['R2']:.3f}, "
                 f"PBIAS={met['PBIAS']:.1f}%")
        self.cb.baseline(df, met)
        summary: Dict[str, Any] = {"baseline": met, "out_dir": self.out_dir}
        if do_sufi:
            summary.update(self.sufi_loop(geom, p0, p1, obs))
        self.cb.finished(summary)
        return summary

    def sufi_loop(self, geom, p0, p1, obs) -> Dict[str, Any]:
        c = self.cfg
        bounds = {k: (float(v[0]), float(v[1])) for k, v in c["ROUGHNESS_BOUNDS_BY_NAME"].items()}
        names = list(bounds.keys())
        n_it, n_s = int(c["N_ITERS"]), int(c["N_SAMPLES"])
        total = n_it * n_s + 1
        done = 0
        history: List[Dict[str, Any]] = []
        all_behavior: List[pd.Series] = []
        bounds_log = [{"iter": 1, **{f"{sanitize_colname(k)}_lo": v[0] for k, v in bounds.items()},
                       **{f"{sanitize_colname(k)}_hi": v[1] for k, v in bounds.items()}}]
        first = True

        for it in range(1, n_it + 1):
            self.log(f"\n[SUFI-2] Iteration {it}/{n_it}")
            samples = sample_params_by_name(bounds, n_s, self.rng)
            rows, beh_series, series_by_sample = [], [], {}
            for k, ps in enumerate(samples, start=1):
                self._check_stop()
                self.cb.progress(done, total, f"Iteration {it}/{n_it} · sample {k}/{n_s}")
                self.log(f"  Sample {k:02d}/{n_s}")
                self.update_mannings(geom, ps, backup=first)
                first = False
                self.run_plan()
                self._check_stop()
                try:
                    _, met, s_obs = self.evaluate(geom, p0, p1, obs)
                except Exception as e:
                    self.log(f"    [ERROR] Could not evaluate this run: {e}")
                    met, s_obs = {"RMSE": np.nan, "R2": np.nan, "PBIAS": np.nan}, None
                beh = self.is_behavioral(met["RMSE"], met["R2"])
                row = {"iter": it, "sample": k, "RMSE": met["RMSE"], "R2": met["R2"],
                       "PBIAS": met["PBIAS"], "behavior": int(beh)}
                row.update({sanitize_colname(n): v for n, v in ps.items()})
                rows.append(row)
                history.append(row)
                if s_obs is not None:
                    series_by_sample[k] = s_obs
                    if beh and c["SAVE_BEHAVIOR_TS"]:
                        beh_series.append(s_obs.astype(float))
                self.log(f"    RMSE={met['RMSE']:.2f}  R²={met['R2']:.3f}  behavioral={'yes' if beh else 'no'}")
                done += 1
                self.cb.sample(row)

            it_df = pd.DataFrame(rows)
            it_df.to_csv(self._out(f"sufi_iter_{it:02d}_summary.csv"), index=False)
            ranked = it_df.dropna(subset=["RMSE"]).sort_values(["RMSE", "R2"], ascending=[True, False])
            best_series = series_by_sample.get(int(ranked.iloc[0]["sample"])) if not ranked.empty else None

            ppu = None
            if beh_series:
                ppu = self.compute_ppu(beh_series, obs, float(c["PPU_Q_LOW"]), float(c["PPU_Q_HIGH"]))
                self.log(f"  Iteration {it}: P-factor={ppu.p_factor:.3f}, R-factor={ppu.r_factor:.3f}, "
                         f"best RMSE={ranked.iloc[0]['RMSE']:.2f}")
                self.save_ppu_plot(ppu, obs, best_series, f"Iteration {it}", f"sufi_iter_{it:02d}_95PPU.png")
                all_behavior.extend(beh_series)
            else:
                self.log("  No behavioral runs in this iteration.")

            # --- SUFI-2 range update from the top-K runs ---
            top = ranked.head(int(c["KEEP_TOP_K"]))
            if len(top) >= 2 and it < n_it:
                new_b = {}
                for n in names:
                    arr = top[sanitize_colname(n)].values
                    centre, half = float(np.median(arr)), float(arr.max() - arr.min()) / 2.0
                    lo, hi = bounds[n]
                    nlo = max(lo, centre - float(c["SHRINK_Q"]) * half)
                    nhi = min(hi, centre + float(c["SHRINK_Q"]) * half)
                    if nlo >= nhi:
                        mid = (lo + hi) / 2
                        nlo, nhi = mid * 0.95, mid * 1.05
                    new_b[n] = (float(nlo), float(nhi))
                bounds = new_b
                bounds_log.append({"iter": it + 1, **{f"{sanitize_colname(k)}_lo": v[0] for k, v in bounds.items()},
                                   **{f"{sanitize_colname(k)}_hi": v[1] for k, v in bounds.items()}})
                self.log("  Updated parameter ranges for next iteration.")
            self.cb.iteration(it, ppu, obs, best_series, dict(bounds))

        hist = pd.DataFrame(history)
        hist.to_csv(self._out("sufi_history_all.csv"), index=False)
        pd.DataFrame(bounds_log).to_csv(self._out("sufi_parameter_ranges.csv"), index=False)
        self.log("\n[SUFI-2] Saved sufi_history_all.csv and sufi_parameter_ranges.csv")
        if hist["RMSE"].notna().any():
            self.save_cloud_plot(hist.dropna(subset=["RMSE"]), "sufi_rmse_r2_cloud.png")

        result: Dict[str, Any] = {"history": hist}
        ranked = hist.dropna(subset=["RMSE"]).sort_values(["RMSE", "R2"], ascending=[True, False])
        if ranked.empty:
            self.log("[SUFI-2] No successful runs — nothing to finalise.")
            return result

        best = ranked.iloc[0]
        best_params = {n: float(best[sanitize_colname(n)]) for n in names}
        with open(self._out("best_parameters.json"), "w") as f:
            json.dump(best_params, f, indent=2)
        result["best_params"] = best_params
        self.log("\n[SUFI-2] Re-running with the best parameter set…")
        self._check_stop()
        self.cb.progress(done, total, "Final run with best parameters")
        self.update_mannings(geom, best_params, backup=False)
        self.run_plan()
        df_best, m_best, best_series = self.evaluate(geom, p0, p1, obs)
        df_best.to_csv(self._out("best_model_vs_obs.csv"))
        result["best_metrics"] = m_best
        self.log(f"[SUFI-2] Best run: RMSE={m_best['RMSE']:.2f}, R²={m_best['R2']:.3f}, PBIAS={m_best['PBIAS']:.1f}%")

        if len(all_behavior) > 1:
            ppu = self.compute_ppu(all_behavior, obs, float(c["PPU_Q_LOW"]), float(c["PPU_Q_HIGH"]))
            result["p_factor"], result["r_factor"] = ppu.p_factor, ppu.r_factor
            self.log(f"[SUFI-2] FINAL P-factor={ppu.p_factor:.3f}, R-factor={ppu.r_factor:.3f}")
            pd.DataFrame({"time": ppu.time, "q_low": ppu.q_low, "q_high": ppu.q_high,
                          "observed": obs.values, "best": best_series.values}).to_csv(
                self._out("sufi_final_95PPU.csv"), index=False)
            self.save_ppu_plot(ppu, obs, best_series, "Final 95PPU", "sufi_final_95PPU.png")
            self.cb.iteration(n_it + 1, ppu, obs, best_series, dict(bounds))
        else:
            self.log("[SUFI-2] Not enough behavioral runs to compute the final 95PPU "
                     "(try relaxing the RMSE/R² thresholds).")
        self.cb.progress(total, total, "Calibration complete")
        return result
