import hashlib

from .paths import io_path

CHUNK = 1 << 20


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(io_path(path), "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()