# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('F:\\ThinkVault\\thinkvault\\webui', 'thinkvault/webui'), ('F:\\ThinkVault\\pyproject.toml', '.')]
datas += collect_data_files('chromadb')
datas += collect_data_files('sentence_transformers')


a = Analysis(
    ['F:\\ThinkVault\\thinkvault\\api\\server.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['chromadb', 'chromadb.api', 'chromadb.config', 'chromadb.utils.embedding_functions', 'sentence_transformers', 'sentence_transformers.models', 'pymupdf', 'docx', 'openpyxl', 'pptx', 'httpx', 'httpx._models', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'fastapi', 'starlette'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy.tests', 'scipy', 'pandas.tests', 'PIL.ImageQt', 'IPython', 'jupyter', 'notebook', 'sphinx', 'pytest', 'setuptools'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ThinkVault',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ThinkVault',
)
