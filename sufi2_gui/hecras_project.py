# -*- coding: utf-8 -*-
"""Read plan / geometry information from a HEC-RAS project (.prj) file."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlanInfo:
    code: str          # e.g. "p03"
    title: str         # e.g. "Plan 03 new"
    geom_code: str     # e.g. "g02"
    plan_file: str
    results_hdf: str   # <project>.p03.hdf
    geom_hdf: str      # <project>.g02.hdf


def _read_kv(path: str) -> List[tuple]:
    out = []
    try:
        with open(path, "r", encoding="latin-1", errors="ignore") as f:
            for line in f:
                if "=" in line:
                    k, v = line.split("=", 1)
                    out.append((k.strip(), v.strip()))
    except OSError:
        pass
    return out


def list_plans(prj_path: str) -> List[PlanInfo]:
    if not prj_path or not os.path.isfile(prj_path):
        return []
    folder = os.path.dirname(prj_path)
    stem = os.path.splitext(os.path.basename(prj_path))[0]
    codes = [v for k, v in _read_kv(prj_path) if k == "Plan File"]
    if not codes:  # fall back to files on disk
        codes = sorted({m.group(1) for f in os.listdir(folder)
                        if (m := re.fullmatch(re.escape(stem) + r"\.(p\d\d)", f, re.I))})
    plans = []
    for code in codes:
        pf = os.path.join(folder, f"{stem}.{code}")
        kv = dict(_read_kv(pf))
        g = kv.get("Geom File", "")
        plans.append(PlanInfo(code=code, title=kv.get("Plan Title", code), geom_code=g, plan_file=pf,
                              results_hdf=os.path.join(folder, f"{stem}.{code}.hdf"),
                              geom_hdf=os.path.join(folder, f"{stem}.{g}.hdf") if g else ""))
    return plans


def find_plan(prj_path: str, title: str) -> Optional[PlanInfo]:
    for p in list_plans(prj_path):
        if p.title == title or p.code == title:
            return p
    return None
