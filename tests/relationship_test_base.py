"""
Shared test scaffolding for the relationships/ package tests.

Not a test_*.py module itself (pytest won't collect it) — points MAI_APP_ROOT
at a fresh temp directory per test so state.py/needs.py/crypt.py's real
load/save code paths (via utils.helpers' resolve_existing_path/
resolve_write_path) run against isolated files instead of the real jsons/ tree.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest


class RelationshipTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp(prefix="mai_relationship_test_")
        self._prior_app_root = os.environ.get("MAI_APP_ROOT")
        os.environ["MAI_APP_ROOT"] = self._tmp_dir

    def tearDown(self) -> None:
        if self._prior_app_root is None:
            os.environ.pop("MAI_APP_ROOT", None)
        else:
            os.environ["MAI_APP_ROOT"] = self._prior_app_root
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
