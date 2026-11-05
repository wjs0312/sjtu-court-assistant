"""VS Code 调试入口：运行主程序，但不向调试器抛出 SystemExit。"""

from badminton_bot import main


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        print(f"程序已结束（退出码 {exit_code}）。请根据终端错误和日志排查。")
