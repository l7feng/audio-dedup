import hashlib
import json
import subprocess
import tempfile
import threading
import wave

from .paths import io_path


class AudioError(Exception):
    pass


def duration_wav(path: str):
    try:
        with wave.open(io_path(path), "rb") as w:
            rate = w.getframerate()
            if rate <= 0:
                return None
            return w.getnframes() / rate
    except (wave.Error, EOFError, OSError):
        return None


def probe_duration(path: str, ffprobe: str = "ffprobe", timeout: float = 60) -> float:
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "json", io_path(path),
    ]
    try:
        r = subprocess.run(
            cmd, check=False, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise AudioError(f"ffprobe 超时 {timeout}s") from e
    if r.returncode != 0:
        raise AudioError((r.stderr or "").strip()[-500:] or f"ffprobe 退出码 {r.returncode}")
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError) as e:
        raise AudioError("ffprobe 未返回有效 duration") from e


def decode_pcm_hash(path: str, ffmpeg: str = "ffmpeg", timeout: float = 600):
    cmd = [
        ffmpeg, "-v", "error", "-i", io_path(path),
        "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "48000", "pipe:1",
    ]
    h = hashlib.sha256()
    samples = 0
    timed_out = threading.Event()
    # stderr 走临时文件而非 PIPE：损坏文件可能刷大量警告，双管道同读会死锁
    with tempfile.TemporaryFile() as errf:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf) as p:
            def _kill():
                timed_out.set()
                p.kill()

            watchdog = threading.Timer(timeout, _kill)
            watchdog.start()
            try:
                while chunk := p.stdout.read(1 << 20):
                    h.update(chunk)
                    samples += len(chunk) // 2
                rc = p.wait()
            finally:
                watchdog.cancel()
        errf.seek(0)
        err = errf.read().decode("utf-8", errors="replace")
    if timed_out.is_set():
        raise AudioError(f"解码超时 {timeout}s 被终止")
    if rc != 0:
        raise AudioError(err.strip()[-500:] or f"ffmpeg 退出码 {rc}")
    if samples == 0:
        # 空解码产出会让不同坏文件共享同一空哈希，造成 L2 误报
        raise AudioError("解码产出 0 样本")
    return h.hexdigest(), samples