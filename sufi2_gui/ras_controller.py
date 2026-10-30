# -*- coding: utf-8 -*-
"""Run a HEC-RAS plan through the HEC-RAS COM controller (Windows only)."""
from __future__ import annotations

import os
import sys
import time
from typing import Callable, List, Optional

# Newest first. "auto" tries each until one can be created.
KNOWN_PROGIDS: List[str] = [
    "RAS67.HECRASController", "RAS66.HECRASController", "RAS65.HECRASController",
    "RAS641.HECRASController", "RAS631.HECRASController", "RAS630.HECRASController",
    "RAS610.HECRASController", "RAS60.HECRASController", "RAS507.HECRASController",
    "RAS506.HECRASController", "RAS505.HECRASController",
]


def _dispatch(progid: str):
    import win32com.client  # pywin32
    return win32com.client.Dispatch(progid)


def available_controllers() -> List[str]:
    """Return the HEC-RAS controller ProgIDs registered on this machine."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for pid in KNOWN_PROGIDS:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, pid))
            found.append(pid)
        except OSError:
            pass
    return found


def run_plan(project_path: str, plan_name: str, progid: str = "auto",
             log: Optional[Callable[[str], None]] = None) -> None:
    log = log or print
    if sys.platform != "win32":
        raise RuntimeError("Automated HEC-RAS runs need Windows with HEC-RAS installed. "
                           "Switch to manual mode to run the plan yourself.")
    project_path = os.path.abspath(project_path)

    if progid == "hecrascontroller":  # the package used by the original script
        from hecrascontroller import RasController
        rc = RasController()
        try:
            rc.open_project(project_path)
            rc.run_plan(plan_name)
        finally:
            rc.close()
        return

    import pythoncom
    pythoncom.CoInitialize()  # we are on a worker thread
    try:
        candidates = available_controllers() if progid in ("", "auto", None) else [progid]
        if not candidates:
            raise RuntimeError("No HEC-RAS controller found. Is HEC-RAS installed and registered? "
                               "Pick the version explicitly in Settings, or use manual mode.")
        rc, last_err = None, None
        for pid in candidates:
            try:
                rc = _dispatch(pid)
                used = pid
                break
            except Exception as e:  # try next version
                last_err = e
        if rc is None:
            raise RuntimeError(f"Could not start the HEC-RAS controller: {last_err}")

        log(f"    Running HEC-RAS plan '{plan_name}' ({used})…")
        t0 = time.time()
        try:
            rc.Project_Open(project_path)
            ok = rc.Plan_SetCurrent(plan_name)
            if isinstance(ok, tuple):
                ok = ok[0]
            if ok is False:
                raise RuntimeError(f"Plan '{plan_name}' not found in the project. "
                                   "Use the plan title exactly as shown in HEC-RAS.")
            try:
                rc.Compute_HideComputationWindow()
            except Exception:
                pass
            res = rc.Compute_CurrentPlan(None, None, True)  # blocking
            success = res[0] if isinstance(res, tuple) else bool(res)
            if not success:
                msgs = res[2] if isinstance(res, tuple) and len(res) > 2 and res[2] else []
                raise RuntimeError("HEC-RAS reported a failed computation. " + " | ".join(map(str, msgs or [])))
        finally:
            for call in ("Project_Close", "QuitRas"):
                try:
                    getattr(rc, call)()
                except Exception:
                    pass
            del rc
        log(f"    HEC-RAS finished in {time.time() - t0:.0f} s.")
    finally:
        pythoncom.CoUninitialize()
