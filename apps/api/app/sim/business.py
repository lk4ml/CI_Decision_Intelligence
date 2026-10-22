"""business stand-in model — thin accessor over app.sim.models (common interface: name, version, engine)."""
from app.sim.models import BY_KEY

MODEL = BY_KEY["business"]
name, version, engine = MODEL.name, MODEL.version, MODEL.engine


def run(cfg: dict, levers: dict, conf: dict, rng=None) -> dict:
    return MODEL.run(cfg, levers, conf, rng)
