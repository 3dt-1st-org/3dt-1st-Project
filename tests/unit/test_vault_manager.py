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

    # ✅ 클래스 레벨에서 공유 - 모든 테스트 메서드에서 재사용
    SECRET_MAP: dict[str, str | None] = {
        "db-dsn": "postgres://...",
        "naver-client-id": "abc",
        "azure-openai-key": "xyz",
        "missing-secret": None,   # 실패 케이스
    }

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
        # None 값 제외한 성공 케이스만 필터링
        success_map = {k: v for k, v in self.SECRET_MAP.items() if v is not None}
        manager = self._make_manager(success_map)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            result = manager.get_all_secrets()
            output = mock_out.getvalue()

        for name in success_map:
            self.assertIn(f"[{name}] 로드 성공", output, f"{name} 성공 로그 누락")

        self.assertEqual(set(result.keys()), set(success_map.keys()))

    def test_failed_secrets_all_logged(self):
        """일부 시크릿 로드 실패 시 해당 항목이 모두 ❌ 로그에 포함되어야 한다."""
        manager = self._make_manager(self.SECRET_MAP)  # ✅ 클래스 변수 재사용

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            result = manager.get_all_secrets()
            output = mock_out.getvalue()

        self.assertIn("[missing-secret] 로드 실패", output)
        self.assertIn("[db-dsn] 로드 성공", output)
        self.assertIn("[azure-openai-key] 로드 성공", output)
        self.assertNotIn("missing-secret", result)

    def test_cache_returns_same_object(self):
        """두 번째 호출은 Key Vault에 재요청하지 않고 캐시를 반환해야 한다."""
        success_map = {k: v for k, v in self.SECRET_MAP.items() if v is not None}
        manager = self._make_manager(success_map)  # ✅ 클래스 변수 재사용

        first = manager.get_all_secrets()
        second = manager.get_all_secrets()

        self.assertIs(first, second)
        manager.client.list_properties_of_secrets.assert_called_once()


# ==============================================================================
# load_review_pipeline.py 임포트 테스트
# ==============================================================================
class TestLoadReviewPipelineImport(unittest.TestCase):
    """load_review_pipeline.py가 vault_manager를 통해 시크릿을 가져오는지 검증."""

    def _get_required_secrets(self) -> list[str]:
        """파이프라인 소스코드에서 vault.get_secret(\"...\") 패턴을 자동 추출한다."""
        import re
        pipeline_path = ROOT_DIR / "src" / "collectors" / "load_review_pipeline.py"
        source = pipeline_path.read_text(encoding="utf-8")
        # vault.get_secret("azure-openai-key") 형태에서 키 이름 자동 추출
        return re.findall(r'vault\.get_secret\(["\']([^"\']+)["\']\)', source)

    def _make_fake_secrets(self) -> dict[str, str]:
        return {name: f"fake-value-for-{name}" for name in self._get_required_secrets()}

    def test_import_succeeds_with_mocked_vault(self):
        """vault_manager를 mock하면 파이프라인 모듈이 에러 없이 임포트되어야 한다."""
        fake_secrets = self._make_fake_secrets()

        mock_vault = MagicMock()
        mock_vault.get_secret.side_effect = lambda name: fake_secrets.get(name, f"fake-value-for-{name}")

        # 이미 import된 모듈 캐시 제거
        sys.modules.pop("src.collectors.load_review_pipeline", None)

        with patch("config.vault_manager.vault", mock_vault):
            try:
                import src.collectors.load_review_pipeline as pipeline
                self.assertTrue(hasattr(pipeline, "NAVER_CLIENT_ID"))
                self.assertTrue(hasattr(pipeline, "AZURE_OPENAI_KEY"))
                self.assertEqual(pipeline.NAVER_CLIENT_ID, "fake-value-for-naver-client-id")
            finally:
                sys.modules.pop("src.collectors.load_review_pipeline", None)

    def test_all_required_secrets_are_used(self):
        """REQUIRED_SECRETS의 모든 항목이 파이프라인 소스코드에서 참조되는지 검증."""
        pipeline_path = ROOT_DIR / "src" / "collectors" / "load_review_pipeline.py"
        source = pipeline_path.read_text(encoding="utf-8")
        for name in self._get_required_secrets():
            self.assertIn(name, source, f"파이프라인 소스에서 '{name}' 참조 누락")


# ==============================================================================
# 하드코딩 시크릿 탐지 테스트
# ==============================================================================
class TestNoHardcodedSecrets(unittest.TestCase):
    """vault_manager를 사용하는 스크립트에 시크릿 값이 하드코딩되어 있지 않은지 검증."""

    # ✅ 수동 목록 대신 프로젝트 내 모든 .py 파일 자동 스캔
    SCAN_DIRS = ["src", "scripts", "config"]
    EXCLUDE_FILES = [
        "config/vault_manager.py",  # vault_manager 자체는 제외
    ]

    import re
    FORBIDDEN_PATTERNS = [
        re.compile(r"postgresql://[^:\s]+:[^@\s]+@"),
        re.compile(r"password\s*=\s*['\"][^'\"]{4,}['\"]"),
        re.compile(r"api[_-]?key\s*=\s*['\"][A-Za-z0-9]{8,}['\"]"),
        re.compile(r"SecretClient\("),
        re.compile(r"DefaultAzureCredential\("),
    ]

    def _get_target_files(self) -> list[Path]:
        """SCAN_DIRS 내 모든 .py 파일을 자동으로 수집한다."""
        targets = []
        for scan_dir in self.SCAN_DIRS:
            scan_path = ROOT_DIR / scan_dir
            if scan_path.exists():
                targets.extend(scan_path.rglob("*.py"))

        # 제외 파일 및 경로 필터링 (.venv, __pycache__, .python_packages 등 제외)
        exclude = {ROOT_DIR / f for f in self.EXCLUDE_FILES}
        exclude_dirs = {".venv", "__pycache__", ".python_packages", "node_modules"}
        return [
            f for f in targets
            if f not in exclude
            and not any(part in exclude_dirs for part in f.parts)
        ]

    def test_no_hardcoded_secrets(self):
        findings = []
        for path in self._get_target_files():
            source = path.read_text(encoding="utf-8")
            for pattern in self.FORBIDDEN_PATTERNS:
                if pattern.search(source):
                    findings.append(f"{path.relative_to(ROOT_DIR)}: {pattern.pattern}")

        self.assertEqual(
            findings, [],
            "하드코딩된 시크릿 또는 직접 Key Vault 연결 코드가 발견되었습니다:\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
