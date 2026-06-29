from __future__ import annotations

from pathlib import Path

from PIL import Image


def save_image_as_png(source_path: str, destination_path: str) -> None:
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        image.save(destination, format="PNG")
