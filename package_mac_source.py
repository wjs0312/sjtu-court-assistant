"""从明确白名单创建 Mac 构建工程包，不携带个人状态。"""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
FILES=['app_platform.py','runtime_guard.py','app_ui.py','badminton_bot.py','booking_app.py','booking_preferences.py',
       'campus_session.py','notification_binding.py','notification_dialog.py','notifications.py','watcher.py',
       'venue_catalog.py','venue_catalog.json','config.portable.toml','requirements.txt','build_macos.py',
       '一键生成DMG.command','MACOS_README.md']


def package_source(output=None):
    output=output or ROOT/'releases';output.mkdir(parents=True,exist_ok=True)
    archive=output/'SJTU-Booking-Mac-BuildKit.zip'
    prefix='sjtu场地助手-Mac构建工程/'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for filename in FILES:
            data=(ROOT/filename).read_bytes().replace(b'\r\n',b'\n')
            info=zipfile.ZipInfo(prefix+filename)
            info.create_system=3
            info.external_attr=((0o100755 if filename.endswith('.command') else 0o100644)<<16)
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
        z.writestr(prefix+'config.toml',(ROOT/'config.portable.toml').read_bytes())
    return archive


if __name__=='__main__':print(package_source())
