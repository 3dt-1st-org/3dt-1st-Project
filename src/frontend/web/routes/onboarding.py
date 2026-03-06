from flask import Blueprint, render_template

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.route("/")
def splash():
    return render_template("onboarding/splash.html")


@onboarding_bp.route("/privacy")
def privacy():
    return render_template("onboarding/privacy.html")


@onboarding_bp.route("/location-consent")
def location_consent():
    return render_template("onboarding/location_consent.html")


@onboarding_bp.route("/onboarding")
def onboarding_intro():
    return render_template("onboarding/index.html")
