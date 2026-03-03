from flask import Blueprint, render_template

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.route("/")
def splash():
    return render_template("onboarding/splash.html")


@onboarding_bp.route("/privacy")
def privacy():
    return render_template("onboarding/privacy.html")
