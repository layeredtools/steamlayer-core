from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("steamlayer-core")
except PackageNotFoundError:
    __version__ = "dev"
