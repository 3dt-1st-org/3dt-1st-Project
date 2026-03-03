import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

# 1. 로컬의 .env 파일에서 KEY_VAULT_URL을 불러옵니다.
load_dotenv()

_instance = None

def get_vault_manager():
    global _instance
    if _instance is None:
        _instance = KeyVaultManager()
    return _instance

class KeyVaultManager:
    def __init__(self):
        self.vault_url = os.getenv("KEY_VAULT_URL")
        if not self.vault_url:
            raise ValueError("환경 변수에 KEY_VAULT_URL이 설정되지 않았습니다.")

        try:
            # 2. DefaultAzureCredential을 통해 인증을 수행합니다.
            # 로컬에서는 'az login' 정보를 사용하고, 클라우드 배포 시에는 '관리 ID(Managed Identity)'를 자동으로 사용합니다.
            self.credential = DefaultAzureCredential()

            # 3. Key Vault와 통신할 클라이언트 객체를 생성합니다.
            self.client = SecretClient(vault_url=self.vault_url, credential=self.credential)
            print(f"✅ Key Vault 클라이언트가 성공적으로 연결되었습니다: {self.vault_url}")

        except Exception as e:
            print(f"❌ Key Vault 인증 또는 연결에 실패했습니다: {e}")
            raise

    def get_secret(self, secret_name: str) -> str | None:  # ✅ None 반환 가능성 명시
        """Key Vault에서 주어진 이름의 시크릿 값을 가져옵니다."""
        try:
            retrieved_secret = self.client.get_secret(secret_name)
            return retrieved_secret.value

        except ResourceNotFoundError:
            print(f"⚠️ Key Vault에 '{secret_name}' (이)라는 이름의 시크릿이 존재하지 않습니다.")
            return None
        except HttpResponseError as e:
            print(f"⚠️ Key Vault 접근 중 오류 발생 (권한 문제일 수 있습니다): {e}")
            return None

    def list_secret_names(self) -> list[str]:
        """Key Vault에 저장된 모든 시크릿의 이름 목록을 반환합니다."""
        try:
            return [prop.name for prop in self.client.list_properties_of_secrets() if prop.name is not None]  # ✅ None 필터링
        except HttpResponseError as e:
            print(f"⚠️ 시크릿 목록 조회 중 오류 발생: {e}")
            return []

    def get_all_secrets(self) -> dict[str, str]:
        """Key Vault에 저장된 모든 시크릿을 {이름: 값} 딕셔너리로 반환합니다."""
        if hasattr(self, "_cache"):
            return self._cache

        secret_names = self.list_secret_names()
        secrets: dict[str, str] = {}
        failed: list[str] = []

        for name in secret_names:
            value = self.get_secret(name)
            if value is not None:
                print(f"  ✅ [{name}] 로드 성공")
                secrets[name] = value
            else:
                print(f"  ❌ [{name}] 로드 실패")
                failed.append(name)

        print(f"\n📋 시크릿 로드 결과: 성공 {len(secrets)}개 / 실패 {len(failed)}개")
        if failed:
            print(f"   실패 목록: {failed}")

        self._cache = secrets
        return secrets


# 모듈 레벨 싱글톤 인스턴스 - 다른 모듈에서 바로 import해서 사용
vault = get_vault_manager()


def main():
    print("데이터 파이프라인 설정을 초기화합니다...")
    vault.get_all_secrets()

if __name__ == "__main__":
    main()