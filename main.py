"""Entry point for the HEC-RAS SUFI-2 Calibrator (also used by PyInstaller)."""
import multiprocessing

from sufi2_gui.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
