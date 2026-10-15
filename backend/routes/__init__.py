from flask import Flask

from .analysis import bp as analysis_bp
from .devices import bp as devices_bp
from .links import bp as links_bp
from .scenarios import bp as scenarios_bp
from .simulation import bp as simulation_bp
from .topology import bp as topology_bp


def register_blueprints(app: Flask) -> None:
    for bp in (topology_bp, devices_bp, links_bp, simulation_bp, analysis_bp, scenarios_bp):
        app.register_blueprint(bp, url_prefix="/api")
