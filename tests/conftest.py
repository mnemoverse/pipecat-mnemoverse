#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

"""Test setup.

``pipecat.processors.aggregators.llm_context`` imports ``pipecat.audio.utils``,
which imports the native ``loudness`` extension. Where that extension cannot be
loaded (a Windows application control policy blocks its DLL, for example), the
tests use an empty stand-in module: this package never measures loudness.
Everywhere the real extension loads, it is used as is.
"""

import sys
import types

try:
    import loudness  # noqa: F401
except ImportError:
    sys.modules["loudness"] = types.ModuleType("loudness")
