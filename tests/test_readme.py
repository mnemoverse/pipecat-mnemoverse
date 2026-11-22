#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "voice-agent-memory.py"

# The pipecat-ai extra that brings in the third-party module each import needs.
EXTRA_FOR_MODULE = {
    "pipecat.audio.vad.silero": "silero",
    "pipecat.runner.run": "runner",
    "pipecat.services.deepgram": "deepgram",
    "pipecat.services.elevenlabs": "elevenlabs",
    "pipecat.services.openai": "openai",
    "pipecat.transports.daily": "daily",
}


def _imported_modules(path: Path) -> set[str]:
    """Every module the file imports, at module level or inside a block."""
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


class TestReadme(unittest.TestCase):
    def test_the_example_install_command_brings_every_extra_the_example_imports(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        match = re.search(r'pip install "pipecat-ai\[([a-z0-9,-]+)\]"', readme)
        self.assertIsNotNone(match, "README has no pip install line for the example")
        assert match is not None
        listed = set(match.group(1).split(","))
        needed = {
            extra
            for module in _imported_modules(EXAMPLE)
            for prefix, extra in EXTRA_FOR_MODULE.items()
            if module == prefix or module.startswith(prefix + ".")
        }
        self.assertEqual(needed - listed, set())


if __name__ == "__main__":
    unittest.main()
