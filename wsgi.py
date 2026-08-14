"""Точка запуска веб-интерфейса через Gunicorn за доверенным Nginx."""

from werkzeug.middleware.proxy_fix import ProxyFix

from web_app import app


app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)
application = app
