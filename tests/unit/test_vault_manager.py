"""
vault_manager.py 및 vault_manager를 사용하는 스크립트에 대한 유닛 테스트.

[테스트 방침]
1. 실제 Key Vault에 연결하지 않고 Mock으로 대체한다.
2. 모든 시크릿에 대한 성공/실패 로깅 여부를 검증한다.
3. vault_manager를 사용하는 스크립트가 하드코딩 없이 동작하는지 검증한다.
"""

import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[2]


# ==============================================================================
# vault_manager 자체 테스트
# ==============================================================================
class TestGetAllSecretsLogging(unittest.TestCase):
    """get_all_secrets()가 모든 시크릿의 성공/실패를 빠짐없이 로깅하는지 검증."""

    def _make_manager(self, secret_map: dict[str, str | None]):
        """mock SecretClient를 주입한 KeyVaultManager를 반환한다."""
        from config.vault_manager import KeyVaultManager

        manager = KeyVaultManager.__new__(KeyVaultManager)

        # list_properties_of_secrets mock
        props = []
        for name in secret_map:
            prop = MagicMock()
            prop.name = name
            props.append(prop)

        mock_client = MagicMock()
        mock_client.list_properties_of_secrets.return_value = props

        def fake_get_secret(name):
            value = secret_map[name]
            if value is None:
                from azure.core.exceptions import ResourceNotFoundError
                raise ResourceNotFoundError(message=f"{name} not found")
            result = MagicMock()
            result.value = value
            return result

        mock_client.get_secret.side_effect = fake_get_secret
        manager.client = mock_client
        return manager

    def test_all_secrets_logged_on_success(self):
        """모든 시크릿이 성공하면 각각 ✅ 로그가 출력되어야 한다."""
        secret_map = {
            "db-dsn": "postgres://...",
            "naver-client-id": "abc",
            "azure-openai-key": "xyz",
        }
        manager = self._make_manager(secret_map)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            result = manager.get_all_secrets()
            output = mock_out.getvalue()

        for name in secret_map:
            self.assertIn(f"[{name}] 로드 성공", output, f"{name} 성공 로그 누락")

        self.assertEqual(set(result.keys()), set(secret_map.keys()))

    def test_failed_secrets_all_logged(self):
        """일부 시크릿 로드 실패 시 해당 항목이 모두 ❌ 로그에 포함되어야 한다."""
        secret_map = {
            "db-dsn": "postgres://...",
            "missing-secret": None,   # 실패 케이스
            "azure-openai-key": "xyz",
        }
        manager = self._make_manager(secret_map)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            result = manager.get_all_secrets()
            output = mock_out.getvalue()

        self.assertIn("[missing-secret] 로드 실패", output)
        self.assertIn("[db-dsn] 로드 성공", output)
        self.assertIn("[azure-openai-key] 로드 성공", output)
        self.assertNotIn("missing-secret", result)

    def test_cache_returns_same_object(self):
        """두 번째 호출은 Key Vault에 재요청하지 않고 캐시를 반환해야 한다."""
        secret_map = {"db-dsn": "postgres://..."}
        manager = self._make_manager(secret_map)

        first = manager.get_all_secrets()
        second = manager.get_all_secrets()

        self.assertIs(first, second)
        # 두 번째 호출에서 list_properties_of_secrets가 다시 호출되지 않아야 함
        manager.client.list_properties_of_secrets.assert_called_once()


# ==============================================================================
# load_review_pipeline.py 임포트 테스트
# ==============================================================================
class TestLoadReviewPipelineImport(unittest.TestCase):
    """load_review_pipeline.py가 vault_manager를 통해 시크릿을 가져오는지 검증."""

    REQUIRED_SECRETS = [
        "naver-client-id",
        "naver-client-secret",
        "azure-openai-endpoint",
        "azure-openai-key",
        "azure-openai-deployment-name",
        "azure-openai-version",
        "azure-openai-embedding-deployment-name",
        "azure-openai-embedding-api-version",
        "db-password",
    ]

    def _make_fake_secrets(self) -> dict[str, str]:
        return {name: f"fake-value-for-{name}" for name in self.REQUIRED_SECRETS}

    def test_import_succeeds_with_mocked_vault(self):
        """vault_manager를 mock하면 파이프라인 모듈이 에러 없이 임포트되어야 한다."""
        fake_secrets = self._make_fake_secrets()

        mock_manager = MagicMock()
        mock_manager.get_all_secrets.return_value = fake_secrets

        # 이미 import된 모듈 캐시 제거
        sys.modules.pop("src.collectors.load_review_pipeline", None)

        with patch("config.vault_manager.get_vault_manager", return_value=mock_manager):
            try:
                import src.collectors.load_review_pipeline as pipeline
                self.assertTrue(hasattr(pipeline, "NAVER_CLIENT_ID"))
                self.assertTrue(hasattr(pipeline, "AZURE_OPENAI_KEY"))
                self.assertEqual(pipeline.NAVER_CLIENT_ID, f"fake-value-for-naver-client-id")
            finally:
                sys.modules.pop("src.collectors.load_review_pipeline", None)

    def test_all_required_secrets_are_used(self):
        """REQUIRED_SECRETS의 모든 항목이 파이프라인 소스코드에서 참조되는지 검증."""
        pipeline_path = ROOT_DIR / "src" / "collectors" / "load_review_pipeline.py"
        source = pipeline_path.read_text(encoding="utf-8")
        for name in self.REQUIRED_SECRETS:
            self.assertIn(name, source, f"파이프라인 소스에서 '{name}' 참조 누락")


# ==============================================================================
# 하드코딩 시크릿 탐지 테스트
# ==============================================================================
class TestNoHardcodedSecrets(unittest.TestCase):
    """vault_manager를 사용하는 스크립트에 시크릿 값이 하드코딩되어 있지 않은지 검증."""

    TARGET_FILES = [
        "src/collectors/load_review_pipeline.py",
        "scripts/ingest/run_daangn_crawl_once.py",
        "scripts/ingest/bootstrap_and_run_daangn_once.py",
    ]

    # 하드코딩 시크릿 패턴
    import re
    FORBIDDEN_PATTERNS = [
        re.compile(r"postgresql://[^:\s]+:[^@\s]+@"),
        re.compile(r"password\s*=\s*['\"][^'\"]{4,}['\"]"),
        re.compile(r"api[_-]?key\s*=\s*['\"][A-Za-z0-9]{8,}['\"]"),
        re.compile(r"SecretClient\("),          # vault_manager 밖에서 직접 사용 금지
        re.compile(r"DefaultAzureCredential\("),# vault_manager 밖에서 직접 사용 금지
    ]

    def test_no_hardcoded_secrets(self):
        findings = []
        for rel_path in self.TARGET_FILES:
            path = ROOT_DIR / rel_path
            if not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            for pattern in self.FORBIDDEN_PATTERNS:
                if pattern.search(source):
                    findings.append(f"{rel_path}: {pattern.pattern}")

        self.assertEqual(
            findings, [],
            "하드코딩된 시크릿 또는 직접 Key Vault 연결 코드가 발견되었습니다:\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
