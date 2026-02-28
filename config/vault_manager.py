import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

# 1. 로컬의 .env 파일에서 KEY_VAULT_URL을 불러옵니다.
load_dotenv()


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

    def get_secret(self, secret_name: str) -> str:
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


def main():
    print("데이터 파이프라인 설정을 초기화합니다...")

    vault = KeyVaultManager()

    # Key Vault에 저장된 이름(하이픈 방식)으로 요청하여 실제 값을 변수에 할당합니다.
    db_dsn = vault.get_secret("db-dsn")
    weather_api_key = vault.get_secret("weather-api-key")
    naver_client_id = vault.get_secret("naver-client-id")
    azure_openai_key = vault.get_secret("azure-openai-key")
    azure_openai_endpoint = vault.get_secret("azure-openai-endpoint")

    if db_dsn:
        print("✅ DB DSN을 성공적으로 가져왔습니다.")
        # engine = create_engine(db_dsn)

    if azure_openai_key:
        print("✅ Azure OpenAI API Key를 성공적으로 가져왔습니다.")

    if not naver_client_id:
        print("❌ 네이버 클라이언트 ID를 가져오지 못했습니다. Key Vault 설정과 시크릿 이름을 확인하세요.")


if __name__ == "__main__":
    main()