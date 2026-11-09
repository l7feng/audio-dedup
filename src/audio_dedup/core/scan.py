import os

from .paths import io_path, is_audio


def walk_audio(root: str, errors: list):
    def on_error(e):
        errors.append(f"{getattr(e, 'filename', '?')}: {e}")

    for dirpath, _dirnames, filenames in os.walk(root, onerror=on_error):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if not is_audio(path):
                continue
            try:
                st = os.stat(io_path(path))
            except OSError as e:
                errors.append(f"{path}: {e}")
                continue
            yield path, st.st_size, st.st_mtime_ns