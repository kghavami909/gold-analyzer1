"""
Path fixer — imported at the top of every module to ensure
site-packages installed via pip --target are on sys.path.
"""
import sys
import os

_CANDIDATE_SITE_PACKAGES = [
    r"C:\Python313\Lib\site-packages",
    os.path.join(os.environ.get("APPDATA", ""),
                 "Python", "Python313", "site-packages"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 "Programs", "Python", "Python313", "Lib", "site-packages"),
]
for _sp in _CANDIDATE_SITE_PACKAGES:
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)
