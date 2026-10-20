"""Compatibility entry point for LMS deployment."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.deploy_agent import main
if __name__ == "__main__":
    main()
