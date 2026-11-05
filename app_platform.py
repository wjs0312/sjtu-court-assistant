"""平台差异集中在此处；Mac 的应用资源和个人数据分开保存。"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def runtime_paths(platform, frozen, executable, bundle, source, user_home):
    if frozen and platform == 'darwin':
        return user_home/'Library'/'Application Support'/'SJTU-Booking', bundle
    root=executable.parent if frozen else source
    return root,root


def current_paths():
    data, resources=runtime_paths(sys.platform, getattr(sys,'frozen',False),Path(sys.executable).resolve(),
                                  Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent)),
                                  Path(__file__).resolve().parent,Path.home())
    override=os.environ.get('SJTU_APP_DATA_DIR')
    return (Path(override).expanduser().resolve() if override else data), resources


def prepare_data(data,resources):
    data.mkdir(parents=True,exist_ok=True)
    for filename,target in [('config.portable.toml','config.toml'),('venue_catalog.json','venue_catalog.json')]:
        destination=data/target
        if not destination.exists() and (resources/filename).exists():
            shutil.copy2(resources/filename,destination)


def font_family(platform=None):
    return 'PingFang SC' if (platform or sys.platform)=='darwin' else 'Microsoft YaHei UI'


def terminal_command(command, platform=None):
    platform=platform or sys.platform
    if platform=='win32':
        return command,{'creationflags':subprocess.CREATE_NEW_CONSOLE}
    if platform=='darwin':
        shell=shlex.join(command)+"; printf '\\nPress Enter to close…'; read -r sjtu_done"
        script='tell application "Terminal"\nactivate\ndo script '+json.dumps(shell,ensure_ascii=False)+'\nend tell'
        return ['osascript','-e',script],{}
    return command,{}
