"""反対側主シグナルによる利益保護の近傍と執行遅延を再生する。"""
from pathlib import Path
import runpy

ORIGINAL = runpy.run_path(str(Path(__file__).with_name("出口条件.py")))
prepare_signals,decide = ORIGINAL["prepare_signals"],ORIGINAL["decide"]
POLICIES = [f"R{i}" for i in range(10,17)]+["R02L3","R02L5"]
