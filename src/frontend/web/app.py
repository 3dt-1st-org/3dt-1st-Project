import os
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# app.py 기준 절대 경로 — 실행 위치에 관계없이 항상 올바르게 탐색
_BASE = Path(__file__).parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_BASE / "templates"),
        static_folder=str(_BASE / "static"),
    )
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "lala-dev-secret")

    # 카카오맵 키를 Jinja2 전역 변수로 주입
    app.jinja_env.globals["kakao_js_key"] = os.getenv("KAKAO_JS_KEY", "")

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
