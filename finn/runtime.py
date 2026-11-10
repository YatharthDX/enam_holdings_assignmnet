"""Deployment capabilities; the public presentation never acts as an operator."""
import os


def public_demo():
    return os.environ.get("FINN_PUBLIC_DEMO", "0").strip().lower() in {"1", "true", "yes", "on"}


def interactive():
    return not public_demo() or os.environ.get("FINN_INTERACTIVE_DEMO", "0").strip().lower() in {"1", "true", "yes", "on"}


def capabilities():
    public = public_demo()
    return {"public_demo": public, "read_only": public and not interactive(), "fictional_network": True,
            "scheduled_refresh": not public and os.environ.get("FINN_AUTO_REFRESH", "1").strip().lower() not in {"0", "false", "off"},
            "can_start_workspace": interactive()}
