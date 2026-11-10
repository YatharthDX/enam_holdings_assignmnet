"""Deployment capabilities; the public presentation never acts as an operator."""
import os


def public_demo():
    return os.environ.get("FINN_PUBLIC_DEMO", "0").strip().lower() in {"1", "true", "yes", "on"}


def capabilities():
    public = public_demo()
    return {"public_demo": public, "read_only": public, "fictional_network": True}
