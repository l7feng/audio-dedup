import math
import struct
import subprocess
import wave


def write_wav(path, freq=440.0, seconds=1.0, rate=44100, amp=0.4):
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        v = int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def ffmpeg_meta_copy(src, dst):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "copy",
         "-metadata", "title=variant", str(dst)],
        check=True, capture_output=True,
    )


def ffmpeg_to_flac(src, dst):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "flac", str(dst)],
        check=True, capture_output=True,
    )