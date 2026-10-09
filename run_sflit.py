"""Launch Salesforce LIT locally."""

import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).resolve().parent / "sflit.log", encoding="utf-8"),
    ],
)

from sflit_app.app import launch


if __name__ == "__main__":
    launch()
