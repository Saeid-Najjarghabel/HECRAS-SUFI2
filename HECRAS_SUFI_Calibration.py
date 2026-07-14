# -*- coding: utf-8 -*-
"""
Created on Thu Oct  9 10:48:59 2025

@author: saeid
"""

# HECRAS_SUFI_Calibration.py


import os, json, glob, shutil, warnings, re
import numpy as np
import pandas as pd
import h5py
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import matplotlib.pyplot as plt

# =========================
# CONFIG
# =========================
CONFIG = {
    # --- Required inputs ---
    "RESULTS_HDF": r"E:\Doctoral\PhD Thesis\Input data for HecRas Model\Thames River\Plan 03 new\PostProcessing.hdf",
    "GEOM_HDF":    r"E:\Doctoral\PhD Thesis\Input data for HecRas Model\Thames River\ThamesRiver-2D.g02.hdf",
    "PROJECT_PRJ_FILE": r"E:\Doctoral\PhD Thesis\Thames River\ThamesRiver-2D.prj",
    "PLAN_NAME": "Plan 03 new",

    # Observations CSV or Excel.
    "OBS_PATH":  r"kingston_flow_obs.csv",
    "OBS_TZ":    "Europe/London",

    # CRS 
    "MODEL_EPSG": 27700,

    # ---- Section definition ----
    "AUTO_TRANSECT": True,
    "POINT_LONLAT":  (-0.308351, 51.415005),
    "TRANSECT_LEN_M": 80.0,
    "TRANSECT_LONLAT": [(-0.308528, 51.412500), (-0.308496, 51.413200)],
    "TRANSECT_IS_WGS84": True,

    # ---- SUFI settings ----
    "DO_SUFI": True,
    "AUTOMATE_RUNS": True,
    "N_SAMPLES": 10,
    "N_ITERS": 3,
    "KEEP_TOP_K": 4,
    "SHRINK_Q": 0.75,

    # Behavioral thresholds
    "BEHAVIOR_MAX_RMSE": 40.0,
    "BEHAVIOR_MIN_R2":   0.70,

    # 95PPU quantiles
    "PPU_Q_LOW":  0.025,
    "PPU_Q_HIGH": 0.975,
    "SAVE_BEHAVIOR_TS": True,

    # Initial Manning's n by land-cover name
    "INITIAL_N_BY_NAME": {
        "NoData":                         0.035, "Developed - Low Intensity":      0.030,
        "Developed - Medium Intensity":   0.030, "Barren Land":                    0.020,
        "Open Water":                     0.025, "Unclassified":                   0.035,
        "Developed - Open Space":         0.030, "Palustrine Scrub-Shrub Wetland": 0.050,
        "Developed - High Intensity":     0.025, "Grassland-Herbaceous":           0.035,
        "Evergreen Forest":               0.080, "Palustrine Emergent Wetland":    0.075,
        "Deciduous Forest":               0.070, "Pasture-Hay":                    0.035,
        "Cultivated Crops":               0.040, "Palustrine Forested Wetland":    0.100,
        "Scrub-Shrub":                    0.040,
    },

    # Calibration parameter bounds by NAME.
    "ROUGHNESS_BOUNDS_BY_NAME": {
        "Developed - Low Intensity":      (0.020, 0.050), "Developed - Medium Intensity":   (0.020, 0.050),
        "Developed - High Intensity":     (0.018, 0.045), "Developed - Open Space":         (0.020, 0.050),
        "Grassland-Herbaceous":           (0.025, 0.060), "Pasture-Hay":                    (0.025, 0.060),
        "Cultivated Crops":               (0.025, 0.060), "Evergreen Forest":               (0.050, 0.120),
        "Deciduous Forest":               (0.045, 0.110), "Palustrine Emergent Wetland":    (0.040, 0.120),
        "Palustrine Scrub-Shrub Wetland": (0.030, 0.090), "Scrub-Shrub":                    (0.025, 0.070),
        "Barren Land":                    (0.015, 0.035), "Open Water":                     (0.020, 0.040),
        "Unclassified":                   (0.025, 0.060), "NoData":                         (0.025, 0.060),
    },

    # Output folder
    "OUT_DIR": r".\sufi_outputs",
    "EXPORT_TRANSECT_GPKG": True,
    "TRANSECT_GPKG": "kingston_transect.gpkg",
}
# --- End of Config ---


# Helper to get the absolute path of a file located relative to the script
def get_abs_path(file_path):
    if os.path.isabs(file_path):
        return file_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, file_path)

os.makedirs(CONFIG["OUT_DIR"], exist_ok=True)
@dataclass
class FaceFlowCut:
    time: np.ndarray
    q:    np.ndarray
@dataclass
class UncertaintyResult:
    time: pd.DatetimeIndex
    q_low: np.ndarray
    q_high: np.ndarray
    p_factor: float
    r_factor: float
def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m])**2))) if m.any() else np.nan
def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if m.sum() < 2: return np.nan
    ss_res = np.sum((y_true[m] - y_pred[m])**2)
    ss_tot = np.sum((y_true[m] - np.mean(y_true[m]))**2)
    return float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan
def latin_hypercube(n: int, d: int) -> np.ndarray:
    rng = np.random.default_rng()
    cut = np.linspace(0, 1, n + 1)
    u = rng.random((n, d))
    a, b = cut[:n], cut[1:n+1]
    pts = u * (b - a)[:, None] + a[:, None]
    for j in range(d):
        rng.shuffle(pts[:, j])
    return pts
def sample_params_by_name(bounds: Dict[str, Tuple[float, float]], n_samples: int) -> List[Dict[str, float]]:
    names = list(bounds.keys())
    L = np.array([bounds[name][0] for name in names])
    U = np.array([bounds[name][1] for name in names])
    X = latin_hypercube(n_samples, len(names))
    vals = L + X * (U - L)
    return [{names[j]: float(vals[k, j]) for j in range(len(names))} for k in range(n_samples)]
def sanitize_colname(name: str) -> str:
    return "n_" + re.sub(r'[^A-Za-z0-9_]+', '_', name).lower()
def read_obs_series(path: str, tz: str = "UTC") -> pd.Series:
    abs_path = get_abs_path(path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Observation file not found at: {abs_path}")
    ext = os.path.splitext(abs_path)[1].lower()
    if ext in (".xls", ".xlsx"):
        df = pd.read_excel(abs_path, header=None)
    else:
        df = pd.read_csv(abs_path, header=None)
    t = pd.to_datetime(df.iloc[:, 0].astype(str), dayfirst=True, errors="coerce")
    if tz:
        t = t.dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT").dt.tz_convert("UTC").dt.tz_localize(None)
    q = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s = pd.Series(q.values, index=t, name="obs_cms").dropna()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s
def project_point(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    from pyproj import Transformer
    tf = Transformer.from_crs(4326, epsg, always_xy=True)
    x, y = tf.transform(lon, lat)
    return float(x), float(y)
def project_line(lonlat2: List[Tuple[float, float]], epsg: int) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    p0 = project_point(lonlat2[0][0], lonlat2[0][1], epsg)
    p1 = project_point(lonlat2[1][0], lonlat2[1][1], epsg)
    return p0, p1
def _walk_datasets(h5obj: h5py.Group, path: str = "/") -> Any:
    if hasattr(h5obj, "keys"):
        for k, v in h5obj.items():
            p = f"{path.rstrip('/')}/{k}"
            if hasattr(v, "keys"):
                yield from _walk_datasets(v, p)
            else:
                yield p, v

# =================================================================
# MODIFIED HDF5 FUNCTIONS TO READ FROM SEPARATE GEOM/RESULTS FILES
# =================================================================
def get_geometry_source_path() -> str:
    """Finds the best source file for geometry data."""
    geom_hdf = CONFIG["GEOM_HDF"]
    if os.path.exists(geom_hdf):
        print(f"[INFO] Using specified geometry file: {geom_hdf}")
        return geom_hdf
    
    # Fallback: look for the main plan file (.p file)
    results_hdf = CONFIG["RESULTS_HDF"]
    base_dir = os.path.dirname(results_hdf)
    plan_num = os.path.basename(results_hdf).split('.')[1]
    p_file_pattern = f"*.{plan_num}.hdf"
    p_files = glob.glob(os.path.join(base_dir, "..", p_file_pattern)) # Search in parent dir
    if p_files:
        p_file = p_files[0]
        print(f"[INFO] Found companion plan file for geometry: {p_file}")
        return p_file
        
    raise FileNotFoundError("Could not find a valid geometry source. Please check the 'GEOM_HDF' path in CONFIG.")

def _face_geometry_arrays(geom_source_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Reads face geometry arrays from a specified HDF source. This definitive version
    correctly navigates into the specific 2D Area sub-group (e.g., 'Perimeter 1')
    before dynamically searching for the required geometry datasets.
    """
    try:
        with h5py.File(geom_source_path, 'r') as g_file:
            # 1. Navigate to the parent group of all 2D areas
            areas_parent_group = g_file["/Geometry/2D Flow Areas"]
            
            # 2. Find the correct sub-group (e.g., 'Perimeter 1') inside.
            #    We must find the HDF5 Group, not the 'Attributes' Dataset.
            geom_group = None
            for key, value in areas_parent_group.items():
                if isinstance(value, h5py.Group):
                    geom_group = value
                    print(f"[INFO] Found and using geometry group: '{geom_group.name}'")
                    break # Use the first group found
            
            if geom_group is None:
                raise IOError("Could not find a valid 2D Area sub-group (e.g., 'Perimeter 1') within '/Geometry/2D Flow Areas'.")

            # 3. Now that we are in the correct group, search for datasets by keywords.
            available_datasets_lower = [d.lower() for d in geom_group.keys()]
            original_names = list(geom_group.keys())

            def find_dataset_name(keywords: List[str], required: bool = True) -> str:
                """Searches for a dataset within the geometry group."""
                for i, name_lower in enumerate(available_datasets_lower):
                    if all(keyword.lower() in name_lower.replace(" ", "") for keyword in keywords):
                        original_name = original_names[i]
                        print(f"[INFO] Matched keywords {keywords} to dataset: '{original_name}'")
                        return original_name
                if required:
                    raise IOError(f"Could not find a required dataset with keywords {keywords} in HDF group {geom_group.name}. Available datasets: {original_names}")
                return None
            
            # 4. Find the names of the datasets we need
            coords_name = find_dataset_name(["FacePoints", "Coordinate"], required=True)
            indices_name = find_dataset_name(["Faces", "FacePoint", "Indexes"], required=True)
            normals_name = find_dataset_name(["Faces", "NormalUnitVector", "Length"], required=False)

            # 5. Extract the data from the datasets
            face_xy = np.array(geom_group[coords_name])
            faces_fp_idx = np.array(geom_group[indices_name], dtype=int)
            
            faces_normlen = None
            if normals_name:
                faces_normlen = np.array(geom_group[normals_name])
            
            return face_xy, faces_fp_idx, faces_normlen
            
    except Exception as e:
        raise IOError(f"Failed to read geometry arrays from '{geom_source_path}'. The HDF5 structure may be unexpected. Error: {e}") from e

def _face_flows(results_hdf_path: str) -> Tuple[str, np.ndarray]:
    """Reads face flow results from the results HDF file."""
    with h5py.File(results_hdf_path, "r") as f:
        candidates = []
        for p, ds in _walk_datasets(f, "/"):
            tail = p.split("/")[-1].lower()
            if tail in ("face flows", "face flow") and ds.ndim == 2:
                candidates.append((p, np.array(ds)))
        if not candidates:
            raise RuntimeError("CRITICAL: 'Face Flows' dataset not found in results file.")
        chosen_path, chosen_arr = candidates[0]
        print(f"[INFO] Using face flows at: {chosen_path}")
        return chosen_path, chosen_arr

def _time_strings(results_hdf_path: str, hint_path: str = None) -> pd.DatetimeIndex:
    """Robustly reads timestamps from the results HDF file, using a hint if available."""
    with h5py.File(results_hdf_path, "r") as f:
        print("[INFO] Searching for timestamp data...")
        candidates = []
        for path, ds in _walk_datasets(f, "/"):
            dataset_name = path.split("/")[-1].lower()
            if ("time" in dataset_name and "stamp" in dataset_name) or "time strings" in dataset_name:
                if ds.ndim == 1 and ds.shape[0] > 0:
                    candidates.append(path)
        if not candidates:
            raise RuntimeError("Could not find any potential timestamp datasets in the results file.")

        if hint_path and len(candidates) > 1:
            def get_score(candidate_path, hint):
                return len(os.path.commonpath([os.path.dirname(candidate_path), os.path.dirname(hint)]))
            candidates.sort(key=lambda p: get_score(p, hint_path), reverse=True)

        chosen_path = candidates[0]
        print(f"[INFO] Found and using timestamp data at: {chosen_path}")
        try:
            ts_raw = f[chosen_path][:]
            if hasattr(ts_raw.dtype, 'kind') and ts_raw.dtype.kind == 'S':
                timestamps = [t.decode("utf-8").strip() for t in ts_raw]
                timestamps = [ts.rpartition(':')[0] + '.' + ts.rpartition(':')[2] if ':' in ts[-4:] else ts for ts in timestamps]
                return pd.to_datetime(timestamps)
            else:
                return pd.to_datetime(ts_raw)
        except Exception as e:
            raise RuntimeError(f"Failed to parse timestamps from dataset '{chosen_path}'. Error: {e}") from e

def read_faceflows_across_line(results_hdf_path: str, geom_source_path: str, p0: Tuple[float, float], p1: Tuple[float, float]) -> FaceFlowCut:
    import shapely.geometry as sg
    import shapely.strtree as sindex

    face_xy, faces_fp_idx, faces_normlen = _face_geometry_arrays(geom_source_path)
    data_path, face_flows = _face_flows(results_hdf_path)
    times = _time_strings(results_hdf_path, hint_path=data_path)

    line = sg.LineString([p0, p1])
    segs = [sg.LineString([tuple(face_xy[s]), tuple(face_xy[e])]) for s, e in faces_fp_idx[:, :2]]

    tree = sindex.STRtree(segs)
    cand_idx = tree.query(line)
    idxs = [i for i in set(cand_idx) if segs[i].intersects(line)]
    if not idxs:
        raise RuntimeError("Transect does not intersect any 2D faces—nudge the line across the channel.")
    
    idxs = np.array(sorted(idxs), dtype=int)
    v = np.array([p1[0] - p0[0], p1[1] - p0[1]], float)
    n_tr = np.array([-v[1], v[0]], float); n_tr /= (np.linalg.norm(n_tr) + 1e-12)

    if faces_normlen is not None:
        ns = faces_normlen[idxs, :2]
        signs = np.sign(np.einsum("ij,j->i", ns, n_tr)); signs[signs == 0] = 1.0
    else:
        warnings.warn("Face normals not found; flow direction assumed. Results may be incorrect.")
        signs = np.ones(len(idxs), float)

    q = (face_flows[:, idxs] * signs).sum(axis=1)
    
    if len(q) != len(times):
        raise ValueError(f"CRITICAL MISMATCH: Flow length ({len(q)}) != Time length ({len(times)}). Check HDF5 output options.")

    return FaceFlowCut(time=times.values, q=q)

def build_auto_transect_from_point(results_hdf_path: str, geom_source_path: str, p_xy: Tuple[float, float], length_m: float, search_radius_m: float = 150.0) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    import shapely.geometry as sg
    import shapely.strtree as sindex
    
    face_xy, faces_fp_idx, _ = _face_geometry_arrays(geom_source_path)
    _, face_flows = _face_flows(results_hdf_path)
    q_mean = np.nanmean(face_flows, axis=0)

    segs = [sg.LineString([tuple(face_xy[s]), tuple(face_xy[e])]) for s, e in faces_fp_idx[:, :2]]
    vecs = np.array([(face_xy[e] - face_xy[s]) for s, e in faces_fp_idx[:, :2]])
    vecs = vecs / (np.linalg.norm(vecs, axis=1)[:, None] + 1e-12)

    tree = sindex.STRtree(segs)
    cand_indices = tree.query(sg.Point(p_xy).buffer(search_radius_m))
    if not cand_indices.any():
        raise RuntimeError("No nearby faces to infer flow direction—enlarge search_radius_m.")
    
    w = q_mean[cand_indices]
    V = (vecs[cand_indices] * w[:, None]).sum(axis=0)
    V /= (np.linalg.norm(V) + 1e-12)
    
    N = np.array([-V[1], V[0]], float)
    half = 0.5 * length_m
    p0 = (p_xy[0] - half * N[0], p_xy[1] - half * N[1])
    p1 = (p_xy[0] + half * N[0], p_xy[1] + half * N[1])
    return p0, p1

# --- Other functions (update_landcover, execute_ras, plotting, etc.) are mostly unchanged ---
def update_landcover_mannings_in_geometry(geom_hdf_path: str, mapping_by_name: Dict[str, float], backup: bool = True) -> None:
    if backup:
        bkp = geom_hdf_path + ".bak"
        if not os.path.exists(bkp):
            shutil.copy2(geom_hdf_path, bkp)
            print(f"[BACKUP] Original geometry saved to: {bkp}")
    with h5py.File(geom_hdf_path, "r+") as g:
        ds = g["/Geometry/Land Cover (Manning's n)/Calibration Table"]
        data = ds[:]
        names = np.array([n.decode("utf-8", "ignore") for n in data['Land Cover Name']])
        values = data["Base Manning's n Value"].astype(float)
        changes = []
        for nm, nval in mapping_by_name.items():
            idx = np.where(names == nm)[0]
            if idx.size:
                i = int(idx[0])
                if abs(float(values[i]) - nval) > 1e-6:
                    values[i] = float(nval)
                    changes.append((i, names[i], float(data['Base Manning\'s n Value'][i]), values[i]))
        if changes:
            data["Base Manning's n Value"] = values
            ds[...] = data
            print("[UPDATED] Land Cover Manning's n:")
            for i, nm, old, new in changes:
                print(f"  - [{i:02d}] {nm}: {old:.4f} -> {new:.4f}")
        else:
            print("[INFO] No Manning's n values required changing for this sample.")

def execute_ras_plan(project_path: str, plan_name: str) -> None:
    from hecrascontroller import RasController
    rc = RasController()
    try:
        print(f"  >> Running HEC-RAS plan '{plan_name}'...")
        rc.open_project(project_path)
        rc.run_plan(plan_name)
    finally:
        rc.close()
    print("  >> Simulation complete.")

def compute_95ppu_and_PR(ensemble: List[pd.Series], obs: pd.Series, q_low: float, q_high: float) -> UncertaintyResult:
    if not ensemble: raise ValueError("Cannot compute PPU on an empty ensemble.")
    M = np.column_stack([s.reindex(obs.index).values for s in ensemble])
    qL, qU = np.nanquantile(M, [q_low, q_high], axis=1)
    y = obs.values; valid_obs = np.isfinite(y)
    inside = (y >= qL) & (y <= qU) & valid_obs
    p_fac = inside.sum() / valid_obs.sum() if valid_obs.any() else 0.0
    r_fac = np.nanmean(qU - qL) / np.nanstd(y[valid_obs])
    return UncertaintyResult(time=obs.index, q_low=qL, q_high=qU, p_factor=float(p_fac), r_factor=float(r_fac))

def plot_ppu_time_series(ppu: UncertaintyResult, obs: pd.Series, best: pd.Series, title: str, out_png: str) -> None:
    plt.figure(figsize=(12, 5))
    plt.fill_between(ppu.time, ppu.q_low, ppu.q_high, color='gray', alpha=0.3, label="95% PPU")
    plt.plot(obs.index, obs.values, 'b-', lw=1.8, label="Observed")
    plt.plot(best.index, best.values, 'r--', lw=1.5, label="Best model")
    plt.grid(True, which='major', linestyle='--', linewidth=0.5)
    plt.ylabel("Discharge (m³/s)"); plt.title(f"{title}  |  P-factor={ppu.p_factor:.3f}, R-factor={ppu.r_factor:.3f}")
    plt.legend(); plt.tight_layout()
    plt.savefig(os.path.join(CONFIG["OUT_DIR"], out_png), dpi=300); plt.close()
    print("[PLOT]", out_png)

def plot_rmse_r2_cloud(history_df: pd.DataFrame, out_png: str) -> None:
    plt.figure(figsize=(6.2, 5.2))
    c = np.where(history_df["behavior"] == 1, "tab:green", "tab:gray")
    plt.scatter(history_df["RMSE"], history_df["R2"], s=20, c=c, alpha=0.85)
    if CONFIG["BEHAVIOR_MAX_RMSE"] is not None: plt.axvline(CONFIG["BEHAVIOR_MAX_RMSE"], ls="--", color='k', lw=0.8)
    if CONFIG["BEHAVIOR_MIN_R2"] is not None:   plt.axhline(CONFIG["BEHAVIOR_MIN_R2"], ls="--", color='k', lw=0.8)
    plt.xlabel("RMSE (m³/s)"); plt.ylabel("R²")
    plt.grid(True, which='major', linestyle='--', linewidth=0.5); plt.title("RMSE–R² cloud (green = behavioral)")
    plt.tight_layout(); plt.savefig(os.path.join(CONFIG["OUT_DIR"], out_png), dpi=300); plt.close()
    print("[PLOT]", out_png)

def evaluate_once(results_hdf_path: str, geom_source_path: str, transect_p0: Tuple[float, float], transect_p1: Tuple[float, float], obs_path: str, obs_tz: str) -> Tuple[pd.DataFrame, Dict[str, float]]:
    cut = read_faceflows_across_line(results_hdf_path, geom_source_path, transect_p0, transect_p1)
    q_mod = pd.Series(cut.q, index=cut.time, name="model")
    q_obs = read_obs_series(obs_path, tz=obs_tz)
    df = pd.concat([q_mod, q_obs], axis=1).dropna()
    metrics = {"RMSE": rmse(df["obs_cms"], df["model"]), "R2": r2(df["obs_cms"], df["model"])}
    return df, metrics

def sufi_loop(geom_source_path: str) -> None:
    bounds = CONFIG["ROUGHNESS_BOUNDS_BY_NAME"]
    param_names = list(bounds.keys())
    history, final_behavior_series = [], []
    obs_all = read_obs_series(CONFIG["OBS_PATH"], tz=CONFIG["OBS_TZ"])
    
    if CONFIG["AUTO_TRANSECT"]:
        x, y = project_point(CONFIG["POINT_LONLAT"][0], CONFIG["POINT_LONLAT"][1], CONFIG["MODEL_EPSG"])
        p0, p1 = build_auto_transect_from_point(CONFIG["RESULTS_HDF"], geom_source_path, (x, y), CONFIG["TRANSECT_LEN_M"])
    else:
        p0, p1 = project_line(CONFIG["TRANSECT_LONLAT"], CONFIG["MODEL_EPSG"]) if CONFIG["TRANSECT_IS_WGS84"] else CONFIG["TRANSECT_LONLAT"]
    
    for it in range(CONFIG["N_ITERS"]):
        print(f"\n[SUFI] Iteration {it+1}/{CONFIG['N_ITERS']}")
        samples = sample_params_by_name(bounds, CONFIG["N_SAMPLES"])
        iter_rows, iter_behavior = [], []
        for k, paramset in enumerate(samples, start=1):
            print(f"  - Sample {k:02d}/{CONFIG['N_SAMPLES']}: Updating Manning's n...")
            update_landcover_mannings_in_geometry(geom_source_path, mapping_by_name=paramset, backup=(it == 0 and k == 1))
            
            if CONFIG["AUTOMATE_RUNS"]:
                execute_ras_plan(CONFIG["PROJECT_PRJ_FILE"], CONFIG["PLAN_NAME"])
            else:
                input("  >> Run plan with this roughness set, then press Enter to continue… ")

            df, met = evaluate_once(CONFIG["RESULTS_HDF"], geom_source_path, p0, p1, CONFIG["OBS_PATH"], CONFIG["OBS_TZ"])
            rmse_v, r2_v = met["RMSE"], met["R2"]
            is_behavior = not( (CONFIG["BEHAVIOR_MAX_RMSE"] is not None and (np.isnan(rmse_v) or rmse_v > CONFIG["BEHAVIOR_MAX_RMSE"])) or \
                               (CONFIG["BEHAVIOR_MIN_R2"] is not None and (np.isnan(r2_v) or r2_v < CONFIG["BEHAVIOR_MIN_R2"])) )
            
            row_data = {"iter": it + 1, "sample": k, "RMSE": rmse_v, "R2": r2_v, "behavior": int(is_behavior)}
            row_data.update({sanitize_colname(name): val for name, val in paramset.items()})
            iter_rows.append(row_data)
            print(f"    >> RMSE={rmse_v:.2f}, R²={r2_v:.3f}, Behavioral={is_behavior}")

            if is_behavior and CONFIG["SAVE_BEHAVIOR_TS"]:
                iter_behavior.append(df["model"].reindex(obs_all.index).astype(float))

        it_df = pd.DataFrame(iter_rows)
        it_df.to_csv(os.path.join(CONFIG["OUT_DIR"], f"sufi_iter_{it+1:02d}_summary.csv"), index=False)
        history.extend(iter_rows)
        
        if iter_behavior:
            ppu_it = compute_95ppu_and_PR(iter_behavior, obs_all, CONFIG["PPU_Q_LOW"], CONFIG["PPU_Q_HIGH"])
            best_run_in_iter = it_df.sort_values(["RMSE", "R2"], ascending=[True, False]).iloc[0]
            print(f"  >> Iter {it+1} P-factor={ppu_it.p_factor:.3f}, R-factor={ppu_it.r_factor:.3f}. Best RMSE={best_run_in_iter.RMSE:.2f}")
            plot_ppu_time_series(ppu_it, obs_all, df['model'].reindex(obs_all.index), f"Iteration {it+1}", f"sufi_iter_{it+1:02d}_95PPU.png")
            final_behavior_series.extend(iter_behavior)
        else:
            print("  >> No behavioral runs this iteration.")

        top = it_df.sort_values(["RMSE", "R2"], ascending=[True, False]).head(CONFIG["KEEP_TOP_K"])
        if not top.empty:
            new_bounds = {}
            for name in param_names:
                col = sanitize_colname(name); arr = top[col].values
                c, half_range = np.median(arr), (arr.max() - arr.min()) / 2.0
                lb_prev, ub_prev = bounds[name]
                new_lb = max(lb_prev, c - CONFIG["SHRINK_Q"] * half_range)
                new_ub = min(ub_prev, c + CONFIG["SHRINK_Q"] * half_range)
                if new_lb >= new_ub: new_lb, new_ub = (lb_prev + ub_prev) / 2 * 0.95, (lb_prev + ub_prev) / 2 * 1.05
                new_bounds[name] = (float(new_lb), float(new_ub))
            bounds = new_bounds
            print("  >> Updated bounds for next iteration:", json.dumps(bounds, indent=2))

    hist_df = pd.DataFrame(history)
    hist_df.to_csv(os.path.join(CONFIG["OUT_DIR"], "sufi_history_all.csv"), index=False)
    print("\n[SUFI] Saved sufi_history_all.csv")
    plot_rmse_r2_cloud(hist_df, "sufi_rmse_r2_cloud.png")

    if len(final_behavior_series) > 1:
        best_run = hist_df.sort_values(["RMSE", "R2"], ascending=[True, False]).iloc[0]
        best_params_by_name = {name: best_run[sanitize_colname(name)] for name in param_names}
        print("\n[SUFI] Re-running with best overall parameter set for final results...")
        print(json.dumps(best_params_by_name, indent=2))
        update_landcover_mannings_in_geometry(geom_source_path, mapping_by_name=best_params_by_name, backup=False)
        
        if CONFIG["AUTOMATE_RUNS"]: execute_ras_plan(CONFIG["PROJECT_PRJ_FILE"], CONFIG["PLAN_NAME"])
        else: input("  >> Run plan with FINAL BEST parameters, then press Enter… ")

        df_best_final, m_best = evaluate_once(CONFIG["RESULTS_HDF"], geom_source_path, p0, p1, CONFIG["OBS_PATH"], CONFIG["OBS_TZ"])
        best_series_final = df_best_final["model"].reindex(obs_all.index)
        print(f"[SUFI] Best overall run metrics: RMSE={m_best['RMSE']:.2f}, R²={m_best['R2']:.3f}")
        
        ppu_final = compute_95ppu_and_PR(final_behavior_series, obs_all, CONFIG["PPU_Q_LOW"], CONFIG["PPU_Q_HIGH"])
        print(f"[SUFI] FINAL P-factor={ppu_final.p_factor:.3f}, R-factor={ppu_final.r_factor:.3f}")
        pd.DataFrame({"time": ppu_final.time, "q_low": ppu_final.q_low, "q_high": ppu_final.q_high}).to_csv(
            os.path.join(CONFIG["OUT_DIR"], "sufi_final_95PPU.csv"), index=False)
        plot_ppu_time_series(ppu_final, obs_all, best_series_final, "Final 95% PPU", "sufi_final_95PPU.png")
    else:
        print("[SUFI] Not enough behavioral runs to compute final 95PPU.")

if __name__ == "__main__":
    try:
        geom_source_path = get_geometry_source_path()
        
        if CONFIG.get("INITIAL_N_BY_NAME"):
            update_landcover_mannings_in_geometry(geom_source_path, mapping_by_name=CONFIG["INITIAL_N_BY_NAME"], backup=True)
        
        p0_main, p1_main = (None, None)
        if CONFIG["AUTO_TRANSECT"]:
            x, y = project_point(CONFIG["POINT_LONLAT"][0], CONFIG["POINT_LONLAT"][1], CONFIG["MODEL_EPSG"])
            p0_main, p1_main = build_auto_transect_from_point(CONFIG["RESULTS_HDF"], geom_source_path, (x, y), CONFIG["TRANSECT_LEN_M"])
        else:
            p0_main, p1_main = project_line(CONFIG["TRANSECT_LONLAT"], CONFIG["MODEL_EPSG"])
        
        if CONFIG["EXPORT_TRANSECT_GPKG"]:
            import geopandas as gpd; from shapely.geometry import LineString
            gdf = gpd.GeoDataFrame([{"name": "Kingston_transect"}], geometry=[LineString([p0_main, p1_main])], crs=f"EPSG:{CONFIG['MODEL_EPSG']}")
            gpkg_path = os.path.join(CONFIG["OUT_DIR"], CONFIG["TRANSECT_GPKG"])
            gdf.to_file(gpkg_path, layer="transect", driver="GPKG")
            print("[OUT] Transect exported:", gpkg_path)

        df_single, m = evaluate_once(CONFIG["RESULTS_HDF"], geom_source_path, p0_main, p1_main, CONFIG["OBS_PATH"], CONFIG["OBS_TZ"])
        print("\n[METRICS] Baseline (current HDF):")
        print(f"  RMSE={m['RMSE']:.2f} m³/s, R²={m['R2']:.3f}")
        df_single.to_csv(os.path.join(CONFIG["OUT_DIR"], "kingston_baseline_model_vs_obs.csv"))
        print("[OUT] Aligned baseline series saved.")
        
        if CONFIG["DO_SUFI"]:
            sufi_loop(geom_source_path)

    except Exception as e:
        print("\n" + "="*30 + " SCRIPT FAILED " + "="*30)
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        print("="*75)