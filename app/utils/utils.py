from pathlib import Path


def is_valid_video_file(source: str) -> bool:
    video_extensions = {".mp4", ".mov", ".mkv", ".nut", ".ts", ".flv", ".mp3", ".m4a", ".wav", ".aac", ".wma"}
    return Path(source).suffix.lower() in video_extensions
