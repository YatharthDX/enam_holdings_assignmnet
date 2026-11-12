"""Small, fixed public-demo budgets; reserve inside the research transaction."""
import hashlib

from . import llm, workspaces

LIMITS = {"workspace_per_hour": 3, "global_per_hour": 5, "global_per_day": 15, "concurrent": 1}


def prepare(db):
    db.execute("""CREATE TABLE IF NOT EXISTS public_ai_attempts (
        workspace_hash TEXT NOT NULL, at REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS public_ai_attempts_at ON public_ai_attempts(at)")


def reserve(db, at):
    """Cache hits never reach here; failed attempts count toward the budget too.

    No foreign key to workspaces: deleting/reopening a workspace must not reset
    global counters. The ledger stores no prompts, credentials or personal data.
    SQLite serializes this with insertion of the research job.
    """
    owner = hashlib.sha256(workspaces.current().encode()).hexdigest()
    db.execute("DELETE FROM public_ai_attempts WHERE at<=?", (at - 86400,))
    hourly, daily, own = db.execute("""SELECT
        COALESCE(SUM(at>?),0), COUNT(*),
        COALESCE(SUM(workspace_hash=? AND at>?),0)
        FROM public_ai_attempts""", (at - 3600, owner, at - 3600)).fetchone()
    if (own >= LIMITS["workspace_per_hour"] or hourly >= LIMITS["global_per_hour"] or
            daily >= LIMITS["global_per_day"]):
        raise llm.ProviderError(
            "The public AI demo limit has been reached. Saved readings and core research remain available. "
            "New readings are limited to 3 per workspace/hour, 5 globally/hour and 15 globally/24 hours; try later.",
            "PUBLIC_AI_LIMIT")
    db.execute("INSERT INTO public_ai_attempts VALUES(?,?)", (owner, at))
