"""past dev for CrewAI: Ingest and Recall as crew memory and as agent tools."""

from crewai_pastdotdev._version import __version__
from crewai_pastdotdev.client import DEFAULT_API_HOST, PastDevClient, PastDevError
from crewai_pastdotdev.memory import PastDevMemory
from crewai_pastdotdev.tools import (
    PastDevIngestInput,
    PastDevIngestTool,
    PastDevRecallInput,
    PastDevRecallTool,
)

__all__ = [
    "DEFAULT_API_HOST",
    "PastDevClient",
    "PastDevError",
    "PastDevIngestInput",
    "PastDevIngestTool",
    "PastDevMemory",
    "PastDevRecallInput",
    "PastDevRecallTool",
    "__version__",
]
