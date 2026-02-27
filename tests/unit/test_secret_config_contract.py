import importlib.util
import os
import re
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_run_once_module():
    module_path = ROOT_DIR / "scripts" / "ingest" / "run_daangn_crawl_once.py"
    spec = importlib.util.spec_from_file_location("run_daangn_crawl_once", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load run_daangn_crawl_once module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSecretConfigContract(unittest.TestCase):
    def test_run_once_requires_db_dsn(self):
        module = _load_run_once_module()
        previous = os.environ.pop("DB_DSN", None)
        try:
            with self.assertRaises(RuntimeError):
                module.main()
        finally:
            if previous is not None:
                os.environ["DB_DSN"] = previous

    def test_no_hardcoded_secret_literals_in_repo_files(self):
        # These files are part of runtime and local execution paths.
        target_files = [
            ROOT_DIR / "infra" / "docker" / "docker-compose.yml",
            ROOT_DIR / "scripts" / "ingest" / "bootstrap_and_run_daangn_once.sh",
            ROOT_DIR / "scripts" / "ingest" / "bootstrap_and_run_daangn_once.ps1",
            ROOT_DIR / "src" / "collectors" / "load_review_pipeline.py",
            ROOT_DIR / "src" / "functions" / "daangn_weekly_crawler" / "local.settings.sample.json",
        ]
        forbidden_patterns = [
            re.compile(r"postgresql://[^:\s]+:[^@\s]+@"),
            re.compile(r"POSTGRES_PASSWORD:\s+[\"']?[A-Za-z0-9._-]+"),
            re.compile(r"[\"']password[\"']\s*:\s*[\"'][^\"']+[\"']"),
            re.compile(r"1111"),
        ]

        findings = []
        for file_path in target_files:
            text = file_path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                if pattern.search(text):
                    findings.append(f"{file_path}: {pattern.pattern}")

        self.assertEqual(
            findings,
            [],
            "Hardcoded secret-like literals found:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
