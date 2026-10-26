"""The Windows deliverables stay wired together.

These checks are cheap but they catch the mistakes that only show up in a
release: a version that was bumped in one place, a spec that forgot the update
engine, or a workflow that stops publishing one of the three downloads.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_three_downloads_are_named_in_the_workflow():
    workflow = read(".github/workflows/build-windows.yml")

    assert "DigitalLibrary-$version-windows-x64.exe" in workflow
    assert "DigitalLibrary-$version-setup.zip" in workflow
    assert "DigitalLibrary-$version-windows-x64-update.zip" in workflow
    assert "installer\\DigitalLibrary.nsi" in workflow
    assert "scripts\\build_update_package.py" in workflow


def test_the_installed_build_is_a_folder_with_the_updater_inside():
    spec = read("DigitalLibraryInstalled.spec")
    assert "COLLECT(" in spec
    assert "exclude_binaries=True" in spec
    assert "build_config" in spec

    portable = read("DigitalLibrary.spec")
    assert "COLLECT(" not in portable
    assert "build_config" in portable


def test_the_setup_program_installs_the_folder_and_writes_the_marker():
    script = read("installer/DigitalLibrary.nsi")

    assert "RequestExecutionLevel admin" in script
    assert 'File /r "${SRCDIR}' in script
    assert "install_info.json" in script
    assert "WriteUninstaller" in script
    assert "Uninstall\\DigitalLibrary" in script
    assert "MUI_PAGE_WELCOME" in script and "MUI_PAGE_FINISH" in script


def test_the_update_engine_is_part_of_the_package():
    package = read("utils/updater.py")
    assert "RELEASES_API" in package
    assert "Expand-Archive" in package
    assert "SHA256" in package.upper()


def test_the_version_matches_everywhere():
    version = re.search(r'APP_VERSION = "([^"]+)"', read("config.py")).group(1)

    assert f"filevers={tuple(int(part) for part in version.split('.')) + (0,)}" in read(
        "version_info.txt"
    )
    assert f'"version": "{version}"' in read("utils/settings.py")
    assert f"version-{version}-e8552d" in read("README.md")
    assert "APP_VERSION" in read(".github/workflows/build-windows.yml")


def test_the_installed_edition_keeps_user_data_out_of_program_files():
    config = read("config.py")
    assert "install_info.json" in config
    assert "if INSTALLED_COPY:" in config
    assert "_user_data_dir()" in config


@pytest.mark.parametrize("name", ["build_config.py", "scripts/build_update_package.py"])
def test_the_build_helpers_are_valid_python(name):
    source = read(name)
    compile(source, name, "exec")
