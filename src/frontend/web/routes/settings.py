from flask import Blueprint, render_template, session, redirect, request

settings_bp = Blueprint("settings", __name__)

SUPPORTED_LANGS = ("ko", "en")


@settings_bp.route("/settings")
def settings_view():
    return render_template("settings/index.html")


@settings_bp.route("/settings/lang/<code>", methods=["POST"])
def set_lang(code: str):
    """언어 전환 엔드포인트. POST /settings/lang/en 형식으로 호출."""
    if code in SUPPORTED_LANGS:
        session["lang"] = code
    # 이전 페이지로 돌아가거나, 없으면 설정 페이지로
    return redirect(request.referrer or "/settings")
