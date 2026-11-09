import os

AUDIO_EXTS = {
    ".wav", ".wave", ".flac", ".mp3", ".aif", ".aiff", ".aifc", ".ogg", ".oga",
    ".opus", ".m4a", ".aac", ".wma", ".ape", ".wv", ".mka", ".ac3", ".dts",
    ".caf", ".au", ".snd", ".mp2", ".amr", ".dsf", ".dff",
}

LOSSLESS_EXTS = {
    ".wav", ".wave", ".flac", ".aif", ".aiff", ".aifc", ".ape", ".wv", ".dsf", ".dff",
}


def io_path(path: str) -> str:
    # 实测库内存在 >260 字符路径（BOOM 库 48 条），所有文件 IO 必须走扩展长度前缀
    if os.name != "nt" or path.startswith("\\\\?\\"):
        return path
    abs_path = os.path.abspath(path)
    if abs_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


def ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_audio(path: str) -> bool:
    return ext_of(path) in AUDIO_EXTS