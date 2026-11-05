"""在 Windows 构建不含账号会话的独立便携包。"""
import os
import argparse
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
NAME = 'SJTU-Booking'


def main():
    parser = argparse.ArgumentParser(description='构建 Windows 便携包')
    parser.add_argument('--tag', default='', help='可选发布标签，仅允许字母、数字和短横线')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9-]*', args.tag): parser.error('发布标签格式不正确')
    existing = ROOT / 'dist' / NAME
    if (existing / '.auth').exists() or (existing / '.user-settings.json').exists():
        raise RuntimeError('dist 中的程序已有个人会话或设置，请移到其他目录保管后再构建。')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--name', NAME, '--collect-all', 'playwright', '--collect-all', 'tzdata',
                    'booking_app.py'], cwd=ROOT, check=True)
    target = ROOT / 'dist' / NAME
    # 只复制公共配置、目录与说明，不复制 .auth、密钥、日志或截图。
    for source, destination in [('config.portable.toml', 'config.toml'), ('venue_catalog.json', 'venue_catalog.json'),
                                ('PORTABLE_README.md', '使用说明.md')]:
        shutil.copy2(ROOT / source, target / destination)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser_dir = Path(p.chromium.executable_path).parents[1]
    if not browser_dir.exists():
        raise RuntimeError('请先运行 python -m playwright install chromium')
    bundle = target / 'browsers'
    bundle.mkdir(exist_ok=True)
    shutil.copytree(browser_dir, bundle / browser_dir.name, dirs_exist_ok=True)
    # 命令行演练 / 自检也可能需要 headless shell 与 ffmpeg。
    for pattern in ['chromium_headless_shell-*', 'ffmpeg-*', 'winldd-*']:
        for folder in browser_dir.parent.glob(pattern):
            shutil.copytree(folder, bundle / folder.name, dirs_exist_ok=True)
    subprocess.run([str(target / f'{NAME}.exe'), '--self-test'], cwd=target, check=True)
    output = ROOT / 'releases'; output.mkdir(exist_ok=True)
    suffix = '-' + args.tag if args.tag else ''
    archive = output / f'{NAME}-Windows-x64{suffix}.zip'
    forbidden = {'.auth', '.user-settings.json', 'logs', 'screenshots'}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in target.rglob('*'):
            if file.is_file():
                relative = file.relative_to(target)
                if forbidden.intersection(relative.parts): continue
                z.write(file, Path(NAME) / relative)
    print(f'便携包：{archive} ({archive.stat().st_size / 1024**2:.1f} MB)')


if __name__ == '__main__':
    main()
