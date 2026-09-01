"""Cargo is the version authority; no runtime import or Rust toolchain needed."""
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10 build environment
    import tomli as tomllib
from setuptools import setup

with (Path(__file__).parent / "desktop" / "src-tauri" / "Cargo.toml").open("rb") as stream:
    version = tomllib.load(stream)["package"]["version"]

setup(version=version)
