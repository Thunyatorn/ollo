"""Download pose weights once into models/. The API never downloads at runtime."""
import os

from .vision import MODELS_DIR, POSE_MODEL


def main():
    target = MODELS_DIR / POSE_MODEL
    if target.is_file():
        print(f'Present: {target}')
        return
    from ultralytics import YOLO
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(MODELS_DIR)  # Ultralytics saves bare model names into the working directory.
    try:
        YOLO(POSE_MODEL)
    finally:
        os.chdir(cwd)
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
