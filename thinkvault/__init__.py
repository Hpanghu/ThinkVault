"""ThinkVault — 个人 AI 工作台"""

from importlib.metadata import version as _get_version, PackageNotFoundError as _PkgNotFound

try:
    __version__ = _get_version("thinkvault")
except _PkgNotFound:
    __version__ = "0.0.0-dev"
