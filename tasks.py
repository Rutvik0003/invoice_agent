"""Cross-platform task runner (Windows has no `make`). Usage: python tasks.py dev|test|build|install."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def install() -> None:
    """Install backend (incl. test) and frontend dependencies."""
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt"], cwd=BACKEND, check=True)
    subprocess.run([NPM, "install"], cwd=FRONTEND, check=True)


def dev() -> None:
    """Run the backend (port 8000, auto-reload) and the Vite dev server (port 5173) together."""
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], cwd=BACKEND
    )
    frontend = subprocess.Popen([NPM, "run", "dev"], cwd=FRONTEND)
    print("\n  Frontend: http://localhost:5173   Backend: http://localhost:8000/api/health\n")
    try:
        backend.wait()
        frontend.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (backend, frontend):
            proc.terminate()


def test() -> None:
    """Run the backend test suite."""
    sys.exit(subprocess.run([sys.executable, "-m", "pytest"], cwd=BACKEND).returncode)


def build() -> None:
    """Build the frontend into frontend/dist (served by FastAPI in production)."""
    subprocess.run([NPM, "run", "build"], cwd=FRONTEND, check=True)


TASKS = {"install": install, "dev": dev, "test": test, "build": build}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        sys.exit(f"Usage: python tasks.py {{{'|'.join(TASKS)}}}")
    TASKS[sys.argv[1]]()
