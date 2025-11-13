"""
Build script to create executable with minimal size.
Analyzes actual imports and excludes unused modules.
"""
import subprocess
import sys
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

# PyQt6 modules actually used (based on grep results):
# - QtCore, QtGui, QtWidgets, QtMultimedia, QtMultimediaWidgets
# Everything else can be excluded

EXCLUDES = [
    # Unused PyQt6 modules
    'PyQt6.QtBluetooth',
    'PyQt6.QtDBus',
    'PyQt6.QtDesigner',
    'PyQt6.QtHelp',
    'PyQt6.QtNfc',
    'PyQt6.QtOpenGL',
    'PyQt6.QtOpenGLWidgets',
    'PyQt6.QtPositioning',
    'PyQt6.QtPrintSupport',
    'PyQt6.QtQml',
    'PyQt6.QtQuick',
    'PyQt6.QtQuick3D',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtSensors',
    'PyQt6.QtSerialPort',
    'PyQt6.QtSql',
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngine',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebSockets',
    'PyQt6.QtXml',
    'PyQt6.Qt3DAnimation',
    'PyQt6.Qt3DCore',
    'PyQt6.Qt3DExtras',
    'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic',
    'PyQt6.Qt3DRender',

    'tkinter',
    'unittest',
    'test',
    'doctest',
    'pdb',
]

def clean_build():
    """Remove old build artifacts."""
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    spec_file = PROJECT_ROOT / 'evtmkr.spec'
    if spec_file.exists():
        spec_file.unlink()
    print("Cleaned build directories")

def build_package():
    """Build the package with PyInstaller."""
    exclude_opts = []
    for module in EXCLUDES:
        exclude_opts.extend(['--exclude-module', module])
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'evtmkr',
        '--onedir',
        '--windowed',
        '--clean',
        '--noconfirm',
        '--upx-dir', r'D:\Users\zix63\GitHub\event-marker\upx-5.0.2-win64',
        '--strip',
        *exclude_opts,
        '--add-data', f'src/evtmkr/evt-config.yaml{os.pathsep}evtmkr',
        'src/evtmkr/__main__.py'
    ]
    
    print("Building package...")
    print(f"Command: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    
    if result.returncode != 0:
        print("Build failed!")
        sys.exit(1)
    
    print("\nBuild completed!")
    
    if DIST_DIR.exists():
        size_mb = sum(f.stat().st_size for f in DIST_DIR.rglob('*') if f.is_file()) / (1024 * 1024)
        print(f"Total size: {size_mb:.2f} MB")
        print(f"Output directory: {DIST_DIR}")

if __name__ == "__main__":
    clean_build()
    build_package()
