# HEC-RAS SUFI-2 Calibrator

Desktop interface for the [HECRAS-SUFI2](https://github.com/Saeid-Najjarghabel/HECRAS-SUFI2) model —
automatic calibration of land-cover Manning's n and 95PPU uncertainty analysis for HEC-RAS 2D models.
University of West London.

## Features
- Step-by-step workflow: **Project & data → Gauge & transect → Roughness parameters → SUFI-2 settings → Run & results**
- Reads plans from the `.prj`; choosing a plan fills in the results and geometry HDF files
- Loads land-cover classes straight from the geometry HDF; edit initial n and bounds in a table
- Transect preview on the 2D mesh, with modelled vs observed discharge
- Automatic HEC-RAS runs through the COM controller (HEC-RAS 5.0.5 – 6.7, auto-detected) or manual mode
- Live hydrograph + 95PPU band, RMSE–R² cloud, dotty plots, parameter-range narrowing, run table and log
- Stop at any time; `.bak` backup of the geometry and *File → Restore original geometry*
- Settings saved/loaded as JSON; all outputs of the original script plus `best_parameters.json`

## Install (end users)
Run `HECRAS-SUFI2-Setup-1.0.0.exe` and follow the wizard. HEC-RAS must be installed for automatic runs.

## Build the installer

**Option A — GitHub (no setup needed).** Push this folder to the repository. The workflow in
`.github/workflows/build-windows.yml` builds on a Windows runner; download the installer from
*Actions → latest run → Artifacts*. Pushing a tag like `v1.0.0` also attaches it to a GitHub release.

**Option B — your own Windows PC.** Install Python 3.11+ (tick “Add to PATH”) and
[Inno Setup 6](https://jrsoftware.org/isinfo.php), then double-click `build.bat`.
Output: `dist\installer\HECRAS-SUFI2-Setup-1.0.0.exe` (the app alone is in `dist\HECRAS-SUFI2\`).

## University logo
The official UWL logo (from uwl.ac.uk) is in `sufi2_gui/resources/uwl_logo.svg` / `uwl_logo.png`.
It appears in the window header, the About box and the installer wizard.

## Run from source
```
pip install -r requirements.txt
python main.py
```

## Tests (no HEC-RAS needed)
`python -m tests.test_engine` runs a full calibration on a synthetic 2D case.

## Changes from the original script
- Config-driven engine (`sufi2_gui/engine.py`), callbacks for the UI, clean stop between runs.
- **Auto-transect direction fixed**: the original rotated the face-edge direction by 90°, which gives a line
  *along* the river. The transect is now drawn perpendicular to the mean flow (from face normals).
- HEC-RAS is driven through the standard `RASxx.HECRASController` COM interface (the `hecrascontroller`
  package is still selectable).
- Face geometry is read once and cached; failed runs are logged and skipped instead of aborting.
- Model discharge is interpolated to observation times for the 95PPU; PBIAS is reported as well.
- Iteration plots use the best run of that iteration (previously the last sample).
