import sys
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv
from config.vault_manager import vault


def _read_version() -> str:
    """pyproject.toml 에서 버전 문자열을 읽음. 설치 없이도 동작."""
    if sys.version_info >= (3, 11):
        import tomllib
        _open = lambda p: open(p, "rb")  # noqa: E731
    else:
        try:
            import tomli as tomllib  # pip install tomli
            _open = lambda p: open(p, "rb")  # noqa: E731
        except ImportError:
            return "0.1.0"
    try:
        toml_path = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
        with _open(toml_path) as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "0.1.0"

load_dotenv()  # KEY_VAULT_URL을 .env에서 읽기 위해 유지

# app.py 기준 절대 경로 — 실행 위치에 관계없이 항상 올바르게 탐색
_BASE = Path(__file__).parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_BASE / "templates"),
        static_folder=str(_BASE / "static"),
    )
    app.secret_key = vault.get_secret("flask-secret-key")

    # 카카오맵 키를 Jinja2 전역 변수로 주입
    app.jinja_env.globals["kakao_js_key"] = vault.get_secret("kakao-js-key")

    # 앱 버전 (모든 템플릿에서 {{ app_version }} 사용 가능)
    app.jinja_env.globals["app_version"] = _read_version()

    # i18n: t() 함수와 current_lang 변수를 모든 템플릿에서 사용 가능하게 주입
    from src.frontend.web.i18n import t, get_lang
    app.jinja_env.globals["t"]            = t
    app.jinja_env.globals["current_lang"] = get_lang  # 호출 가능한 함수로 주입

    # Blueprint 등록
    from src.frontend.web.routes.onboarding import onboarding_bp
    from src.frontend.web.routes.main_map import main_map_bp
    from src.frontend.web.routes.settings import settings_bp

    app.register_blueprint(onboarding_bp)
    app.register_blueprint(main_map_bp)
    app.register_blueprint(settings_bp)

    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5000)
