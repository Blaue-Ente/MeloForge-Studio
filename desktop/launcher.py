"""Windows desktop entry point: serves the bundled React UI from the local FastAPI process."""

import os
import logging
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


ROOT = _root()
if getattr(sys, "frozen", False):
    user_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MeloForge Studio"
    user_root.mkdir(parents=True, exist_ok=True)
    env_file = user_root / "config.env"
    template = ROOT / ".env.example"
    if not env_file.exists() and template.is_file():
        shutil.copyfile(template, env_file)
    os.environ["MELOFORGE_HOME"] = str(user_root)
    os.environ["MELOFORGE_DATA_DIR"] = str(user_root / "data")
    os.environ["MELOFORGE_ENV_FILE"] = str(env_file)
    os.environ.setdefault("APP_ENV", "desktop")
    log_dir = user_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "app.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
        force=True,
    )
else:
    os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "backend"))

logging.getLogger("meloforge.launcher").info("Loading MeloForge Studio from %s", ROOT)
try:
    from app.main import app  # noqa: E402

    logging.getLogger("meloforge.launcher").info("MeloForge API imported")
except BaseException:
    logging.getLogger("meloforge.launcher").exception("MeloForge startup failed while importing the API")
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "MeloForge Studio could not start. See %LOCALAPPDATA%\\MeloForge Studio\\logs\\app.log.",
            "MeloForge Studio",
            0x10,
        )
    raise


def open_studio() -> None:
    webbrowser.open_new("http://127.0.0.1:8000")


if __name__ == "__main__":
    logging.getLogger("meloforge.launcher").info("Starting local API on 127.0.0.1:8000")
    threading.Timer(1.2, open_studio).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning", log_config=None)
    except BaseException:
        logging.getLogger("meloforge.launcher").exception("MeloForge API server failed")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                "MeloForge Studio could not start its local API. See %LOCALAPPDATA%\\MeloForge Studio\\logs\\app.log.",
                "MeloForge Studio",
                0x10,
            )
        raise
