import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import native_motion


@pytest.mark.parametrize(('platform', 'relative'), [
    ('darwin', 'macos/Build/Products/Release/dependency_client.app/Contents/MacOS/dependency_client'),
    ('win32', 'windows/x64/runner/Release/flet.exe'),
])
def test_launcher_selects_platform_bundle(tmp_path, monkeypatch, platform, relative):
    monkeypatch.setattr(native_motion, '__file__', str(tmp_path / 'src/native_motion.py'))
    monkeypatch.setattr(native_motion.sys, 'platform', platform)
    executable = tmp_path / 'build/native_client/build' / relative
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("FLET_VIEW_PATH", "")
    native_motion.configure_desktop_client()
    view = Path(native_motion.os.environ['FLET_VIEW_PATH'])
    assert view == (executable.parents[3] if platform == 'darwin' else executable.parent)


def test_missing_mac_client_explains_build_command(tmp_path, monkeypatch):
    monkeypatch.setattr(native_motion, '__file__', str(tmp_path / 'src/native_motion.py'))
    monkeypatch.setattr(native_motion.sys, 'platform', 'darwin')
    with pytest.raises(RuntimeError, match='build-client-macos.sh'):
        native_motion.configure_desktop_client()
