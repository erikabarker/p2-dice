import sys

from setuptools import Extension, setup

extensions = []
if sys.platform == "darwin":
    extensions.append(
        Extension(
            "p2_dice._iokit",
            sources=["src/p2_dice/_iokit.c"],
            extra_link_args=["-framework", "IOKit", "-framework", "CoreFoundation"],
        )
    )

setup(ext_modules=extensions)
