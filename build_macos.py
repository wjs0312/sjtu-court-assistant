"""必须在 Mac 原生执行，生成带 Chromium 的 .app 和 DMG。"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
APP_NAME='sjtu场地助手'


def build_command(project, browser_cache, arch):
    if arch not in ('arm64','x86_64'):raise ValueError('仅支持 arm64 或 x86_64')
    output=project/'build-macos'/arch
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
             '--name',APP_NAME,'--osx-bundle-identifier','cn.sjtu.courtassistant.personal',
             '--target-arch',arch,'--distpath',str(output/'dist'),'--workpath',str(output/'work'),
             '--specpath',str(output),'--collect-all','playwright','--collect-all','tzdata']
    for source,target in [(project/'config.portable.toml','.'),(project/'venue_catalog.json','.'),(browser_cache,'browsers')]:
        command+=['--add-data',str(source)+':'+target]
    return command+[str(project/'booking_app.py')]


def main():
    parser=argparse.ArgumentParser(description='在 Mac 上构建场地助手 DMG')
    parser.add_argument('--plan',action='store_true',help='只输出构建计划，不执行')
    parser.add_argument('--arch',choices=['arm64','x86_64'])
    args=parser.parse_args()
    arch=args.arch or ('arm64' if platform.machine()=='arm64' else 'x86_64')
    cache=ROOT/'build-macos'/arch/'browsers'
    command=build_command(ROOT,cache,arch)
    if args.plan:
        print(json.dumps({'architecture':arch,'command':command},ensure_ascii=False,indent=2));return 0
    if sys.platform!='darwin':
        raise SystemExit('无法在 Windows/Linux 生成原生 Mac DMG。请在 Mac 上运行“一键生成DMG.command”。')
    if arch!=platform.machine():
        raise SystemExit('Python 与目标架构必须一致。请使用该芯片原生的 Python 构建。')
    env=os.environ.copy();env['PLAYWRIGHT_BROWSERS_PATH']=str(cache)
    cache.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','playwright','install','chromium'],env=env,check=True,cwd=ROOT)
    identity=os.environ.get('SJTU_CODESIGN_IDENTITY')
    if identity:command[-1:-1]=['--codesign-identity',identity]
    subprocess.run(command,check=True,env=env,cwd=ROOT)
    app=ROOT/'build-macos'/arch/'dist'/(APP_NAME+'.app')
    executable=app/'Contents'/'MacOS'/APP_NAME
    if not executable.is_file():raise RuntimeError('未生成 .app，不能继续打包 DMG。')
    # 构建自检使用临时个人目录，不读取构建者的校园会话或通知凭证。
    with tempfile.TemporaryDirectory(prefix='sjtu-mac-selftest-') as check_dir:
        check_env=env.copy();check_env['SJTU_APP_DATA_DIR']=check_dir
        subprocess.run([str(executable),'--self-test'],env=check_env,check=True,cwd=ROOT)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    output=ROOT/'releases';output.mkdir(exist_ok=True)
    dmg=output/f'SJTU-Booking-macOS-{arch}.dmg'
    with tempfile.TemporaryDirectory(prefix='sjtu-dmg-stage-') as stage:
        destination=Path(stage)
        shutil.copytree(app,destination/app.name,symlinks=True)
        (destination/'Applications').symlink_to('/Applications',target_is_directory=True)
        shutil.copy2(ROOT/'MACOS_README.md',destination/'使用说明.md')
        subprocess.run(['hdiutil','create','-volname',APP_NAME,'-srcfolder',stage,'-format','UDZO','-ov',str(dmg)],check=True)
    subprocess.run(['hdiutil','verify',str(dmg)],check=True)
    print(f'生成完成：{dmg}')
    return 0


if __name__=='__main__':raise SystemExit(main())
