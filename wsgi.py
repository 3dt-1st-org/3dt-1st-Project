"""
Gunicorn entrypoint for Azure App Service.
wsgi.py references avoid quoting/parsing issues with create_app() callable
in Docker CMD on Azure Linux containers.
"""
from src.frontend.web.app import create_app

application = create_app()
