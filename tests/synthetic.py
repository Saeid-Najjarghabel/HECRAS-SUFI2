# -*- coding: utf-8 -*-
"""Synthetic HEC-RAS-like HDF files + a fake 'run plan' for testing without HEC-RAS.

Channel: a 2D grid of 10 m cells, flow towards the east, centred on a gauge near Kingston.
Model discharge depends on Manning's n so SUFI-2 has something to calibrate.
"""
import os
import numpy as np
import pandas as pd
import h5py
from pyproj import Transformer

GAUGE_LONLAT = (-0.308351, 51.415005)
CLASSES = ["Open Water", "Grassland-Herbaceous", "Deciduous Forest", "Developed - Low Intensity"]
TRUE_N = {"Open Water": 0.030, "Grassland-Herbaceous": 0.042, "Deciduous Forest": 0.075,
          "Developed - Low Intensity": 0.033}
WEIGHTS = {"Open Water": 0.6, "Grassland-Herbaceous": 0.2, "Deciduous Forest": 0.15,
           "Developed - Low Intensity": 0.05}


def _times():
    return pd.date_range("2024-01-01 00:00", periods=240, freq="30min")


def _true_hydrograph(t):
    h = np.arange(len(t)) / 2.0
    return 60 + 220 * np.exp(-((h - 45) / 18) ** 2) + 90 * np.exp(-((h - 85) / 10) ** 2)


def make(folder):
    os.makedirs(folder, exist_ok=True)
    cx, cy = Transformer.from_crs(4326, 27700, always_xy=True).transform(*GAUGE_LONLAT)
    nx, ny, dx = 40, 6, 10.0
    x0, y0 = cx - nx * dx / 2, cy - ny * dx / 2
    pts = np.array([(x0 + i * dx, y0 + j * dx) for j in range(ny + 1) for i in range(nx + 1)])
    pid = lambda i, j: j * (nx + 1) + i
    faces, normals = [], []
    for j in range(ny):              # vertical faces carry eastward flow
        for i in range(nx + 1):
            faces.append((pid(i, j), pid(i, j + 1))); normals.append((1.0, 0.0, dx))
    for j in range(ny + 1):          # horizontal faces, no flow
        for i in range(nx):
            faces.append((pid(i, j), pid(i + 1, j))); normals.append((0.0, 1.0, dx))
    faces, normals = np.array(faces), np.array(normals)
    n_vert = ny * (nx + 1)

    geom = os.path.join(folder, "Synthetic.g01.hdf")
    with h5py.File(geom, "w") as g:
        a = g.create_group("/Geometry/2D Flow Areas/Perimeter 1")
        g["/Geometry/2D Flow Areas"].create_dataset("Attributes", data=np.zeros(1))
        a["FacePoints Coordinate"] = pts
        a["Faces FacePoint Indexes"] = faces
        a["Faces NormalUnitVector and Length"] = normals
        dt = np.dtype([("Land Cover Name", "S64"), ("Base Manning's n Value", "f4")])
        tbl = np.array([(c.encode(), 0.04) for c in ["NoData"] + CLASSES], dtype=dt)
        g.create_dataset("/Geometry/Land Cover (Manning's n)/Calibration Table", data=tbl)

    results = os.path.join(folder, "Synthetic.p01.hdf")
    meta = dict(n_vert=n_vert, nx=nx, ny=ny, n_faces=len(faces))
    simulate(geom, results, meta)

    t = _times()
    rng = np.random.default_rng(1)
    q_obs = _true_hydrograph(t) * (1 + 0.03 * rng.standard_normal(len(t)))
    obs_t = t.tz_localize("UTC").tz_convert("Europe/London").strftime("%d/%m/%Y %H:%M")
    obs = os.path.join(folder, "observed_flow.csv")
    pd.DataFrame({"t": obs_t, "q": q_obs.round(2)}).iloc[::2].to_csv(obs, index=False, header=False)
    prj = os.path.join(folder, "Synthetic.prj")
    open(prj, "w").write("Proj Title=Synthetic\n")
    return dict(geom=geom, results=results, obs=obs, prj=prj, meta=meta)


def simulate(geom, results, meta=None):
    """Fake HEC-RAS: discharge scales with land-cover weighted roughness."""
    with h5py.File(geom, "r") as g:
        tbl = g["/Geometry/Land Cover (Manning's n)/Calibration Table"][:]
        a = g["/Geometry/2D Flow Areas/Perimeter 1"]
        n_faces = a["Faces FacePoint Indexes"].shape[0]
        normals = a["Faces NormalUnitVector and Length"][:]
    nmap = {r[0].decode(): float(r[1]) for r in tbl}
    ratio = sum(WEIGHTS[c] * (TRUE_N[c] / nmap[c]) for c in CLASSES)
    t = _times()
    lag = (sum(WEIGHTS[c] * nmap[c] / TRUE_N[c] for c in CLASSES) - 1) * 6  # rougher -> slower
    h = np.arange(len(t)) / 2.0 - lag
    q = (60 + 220 * ratio ** 0.8 * np.exp(-((h - 45) / 18) ** 2) + 90 * ratio * np.exp(-((h - 85) / 10) ** 2))
    flow_faces = normals[:, 0] > 0.5
    ny = int(round(flow_faces.sum() ** 0.5)) if meta is None else meta["ny"]
    ny = meta["ny"] if meta else 6
    F = np.zeros((len(t), n_faces), np.float32)
    F[:, flow_faces] = (q / ny)[:, None]
    ts = np.array([x.strftime("%d%b%Y %H:%M:%S:000").upper().encode() for x in t])
    with h5py.File(results, "w") as f:
        base = "/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        f[base + "/Time Date Stamp"] = ts
        f[base + "/2D Flow Areas/Perimeter 1/Face Flow"] = F


if __name__ == "__main__":
    import sys
    print(make(sys.argv[1] if len(sys.argv) > 1 else "synthetic_case"))
