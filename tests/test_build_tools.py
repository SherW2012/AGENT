import os
import shutil
import unittest
import uuid
from pathlib import Path

from bnct_tps_agent.audit import AuditLogger
from bnct_tps_agent.build_tools import (
    analyze_build_log,
    configure_build_profile,
    decode_build_output,
    extract_build_errors,
    run_build,
)
from bnct_tps_agent.safety import SafetyPolicy
from bnct_tps_agent.tool_registry import ToolRegistry


SAMPLE_LOG = """\
Microsoft (R) Build Engine
  Dose.cpp
D:\\proj\\src\\Dose.cpp(245): warning C4244: conversion from 'double' to 'float'
D:\\proj\\src\\Dose.cpp(245): error C2065: 'kernelWidth': undeclared identifier
D:\\proj\\src\\Dose.cpp(251): error C2065: 'kernelWidth': undeclared identifier
main.obj : error LNK2019: unresolved external symbol "void __cdecl computeDose(void)"
CMake Error at CMakeLists.txt:12 (message):
src/beam.cpp:88:5: error: 'BeamModel' was not declared in this scope
Build FAILED.
"""


class BuildToolsTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "tests" / "runtime_output"
        self.root = base / f"build-root-{uuid.uuid4().hex}"
        self.data_dir = base / f"build-data-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.data_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def _make_script(self, body: str) -> Path:
        if os.name == "nt":
            script = self.data_dir / "build.bat"
            script.write_text(body, encoding="utf-8")
        else:
            script = self.data_dir / "build.sh"
            script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            script.chmod(0o755)
        return script

    def test_msvc_linker_cmake_and_gcc_errors_are_extracted(self):
        errors = extract_build_errors(SAMPLE_LOG)
        codes = [item["code"] for item in errors]
        self.assertIn("C2065", codes)
        self.assertIn("LNK2019", codes)
        files = [item["file"] for item in errors]
        self.assertIn("D:\\proj\\src\\Dose.cpp", files)
        self.assertIn("src/beam.cpp", files)
        gcc = next(item for item in errors if item["file"] == "src/beam.cpp")
        self.assertEqual(gcc["line"], 88)
        # The warning line must not be captured as an error.
        self.assertFalse(any("C4244" in item["code"] for item in errors))

    def test_gbk_build_output_is_decoded(self):
        text = decode_build_output("错误 C2065: 未声明的标识符".encode("gbk"))
        self.assertIn("未声明的标识符", text)

    def test_configure_rejects_relative_missing_and_bad_suffix(self):
        with self.assertRaises(ValueError):
            configure_build_profile(self.root, self.data_dir, "debug", "relative/build.bat")
        with self.assertRaises(FileNotFoundError):
            configure_build_profile(self.root, self.data_dir, "debug", str(self.data_dir / "missing.bat"))
        bad = self.data_dir / "tool.exe"
        bad.write_bytes(b"MZ")
        with self.assertRaises(ValueError):
            configure_build_profile(self.root, self.data_dir, "debug", str(bad))

    def test_run_build_executes_configured_script_and_extracts_errors(self):
        script = self._make_script(
            'echo compiling...\n'
            'echo "src/dose.cpp:245:5: error: kernelWidth was not declared"\n'
            "exit 1\n"
        )
        configure_build_profile(self.root, self.data_dir, "debug", str(script))
        result = run_build(self.root, self.data_dir, "debug")
        self.assertFalse(result["success"])
        self.assertEqual(result["exitCode"], 1)
        self.assertEqual(result["errors"][0]["file"], "src/dose.cpp")
        self.assertEqual(result["errors"][0]["line"], 245)
        self.assertTrue(Path(result["logPath"]).is_file())

    def test_run_build_requires_configuration_first(self):
        with self.assertRaises(ValueError):
            run_build(self.root, self.data_dir, "release")

    def test_registry_requires_approval_for_run_build(self):
        script = self._make_script("exit 0\n")
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(),  # non-interactive: WRITE/EXECUTE are denied
            AuditLogger(self.data_dir / "audit"),
            data_dir=self.data_dir,
        )
        denied = registry.execute("configure_build_profile", {"profile": "debug", "script_path": str(script)})
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error_type"], "PolicyDenied")

        approving = ToolRegistry(
            self.root,
            SafetyPolicy(lambda *_args: True),
            AuditLogger(self.data_dir / "audit2"),
            data_dir=self.data_dir,
        )
        configured = approving.execute("configure_build_profile", {"profile": "debug", "script_path": str(script)})
        self.assertTrue(configured["ok"], configured)
        ran = approving.execute("run_build", {"profile": "debug"})
        self.assertTrue(ran["ok"], ran)
        self.assertTrue(ran["result"]["success"])
        profiles = approving.execute("get_build_profiles", {})
        self.assertIn("debug", profiles["result"]["profiles"])

    def test_analyze_build_log_reads_existing_file(self):
        log = self.root / "last-build.log"
        log.write_text(SAMPLE_LOG, encoding="utf-8")
        result = analyze_build_log(self.root, "last-build.log")
        self.assertGreaterEqual(result["errorCount"], 3)
        self.assertEqual(result["warningCount"], 1)


if __name__ == "__main__":
    unittest.main()
