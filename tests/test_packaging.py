#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

"""What the built wheel ships, checked on a wheel built from this tree.

The rest of the suite imports the source tree, which says nothing about the
files the wheel carries. Building with hatchling, the build backend, directly
(it is in the ``dev`` extra) takes a second or two and needs no network.
"""

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestWheel(unittest.TestCase):
    names: list[str]

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as out:
            built = subprocess.run(
                [sys.executable, "-m", "hatchling", "build", "--target", "wheel", "-d", out],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if built.returncode != 0:
                raise AssertionError(
                    f"hatchling build failed ({built.returncode}):\n{built.stderr}"
                )
            wheels = list(Path(out).glob("*.whl"))
            if len(wheels) != 1:
                raise AssertionError(f"expected one wheel, got {wheels}")
            with zipfile.ZipFile(wheels[0]) as wheel:
                cls.names = wheel.namelist()

    def test_the_wheel_ships_py_typed(self):
        self.assertIn("pipecat_mnemoverse/py.typed", self.names)


if __name__ == "__main__":
    unittest.main()
