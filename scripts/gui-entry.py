"""PyInstaller 入口：默认开 GUI；带 --cli 时由同一 exe 分发 CLI 子命令。"""
import sys


def main():
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from audio_dedup.cli import main as cli_main
        return cli_main()
    from audio_dedup.gui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
