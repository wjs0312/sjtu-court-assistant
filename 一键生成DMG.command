#!/bin/bash
set -euo pipefail
SJTU_PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$SJTU_PROJECT_DIR"
trap 'sjtu_exit=$?; echo; if [ "$sjtu_exit" -ne 0 ]; then echo "构建未完成，请保留上面的报错信息。"; fi; read -r -p "按 Enter 关闭窗口…" sjtu_done' EXIT
if [ "$(uname -s)" != "Darwin" ]; then
  echo "此脚本需要在 Mac 上执行。"
  exit 1
fi
SJTU_PYTHON=""
for sjtu_candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$sjtu_candidate" >/dev/null 2>&1 && "$sjtu_candidate" -c 'import sys, tkinter; assert sys.version_info >= (3,11)' >/dev/null 2>&1; then
    SJTU_PYTHON="$(command -v "$sjtu_candidate")"
    break
  fi
done
if [ -z "$SJTU_PYTHON" ]; then
  echo "请先安装 python.org 的 Python 3.11 或以上版本（包含 Tk 界面组件），推荐 3.12 或 3.13。"
  open 'https://www.python.org/downloads/macos/'
  exit 1
fi
echo "正在准备 Mac 构建环境。首次需要下载依赖和 Chromium，请保持联网。"
"$SJTU_PYTHON" -m venv .venv-mac
SJTU_BUILD_PYTHON="$SJTU_PROJECT_DIR/.venv-mac/bin/python"
"$SJTU_BUILD_PYTHON" -m pip install --upgrade pip
"$SJTU_BUILD_PYTHON" -m pip install -r requirements.txt 'pyinstaller==6.22.3'
"$SJTU_BUILD_PYTHON" build_macos.py
open "$SJTU_PROJECT_DIR/releases"
