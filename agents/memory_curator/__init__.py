from agents.memory_curator.output import MemoryCuratorOutput, MemoryMotif
from agents.memory_curator.tools import retrieve_memory_motifs, store_memory_motif

__all__ = [
    "memory_curator_agent",
    "MemoryCuratorOutput",
    "MemoryMotif",
    "retrieve_memory_motifs",
    "store_memory_motif",
]


def __getattr__(name: str):
    if name != "memory_curator_agent":
        raise AttributeError(name)
    from agents.memory_curator.agent import memory_curator_agent

    globals()[name] = memory_curator_agent
    return memory_curator_agent
