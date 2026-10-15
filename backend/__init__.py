"""NetCascade Flask backend (Phase 3): JSON API over the Phase 1 graph engine and Phase 2 analysis."""

from flask import Flask

from .errors import register_error_handlers
from .frontend import bp as frontend_bp
from .routes import register_blueprints
from .scenarios import ScenarioStore
from .store import TopologyStore


def create_app(default_topology: str = "basic", config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False
    if config:
        app.config.update(config)
    app.extensions["netcascade_store"] = TopologyStore(default_topology)
    app.extensions["netcascade_scenarios"] = ScenarioStore(
        app.config.get("SCENARIOS_PATH"), seed=app.config.get("SEED_SCENARIOS", True)
    )
    register_error_handlers(app)
    register_blueprints(app)
    app.register_blueprint(frontend_bp)
    return app
