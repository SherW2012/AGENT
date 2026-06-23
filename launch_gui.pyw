"""Double-click launcher for the BNCT TPS Agent desktop application."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
if len(sys.argv) == 1:
    sys.argv.extend(["--root", str(ROOT)])

from bnct_tps_agent.gui import main  # noqa: E402


if __name__ == "__main__":
    main()
