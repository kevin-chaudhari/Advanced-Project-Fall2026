"""
Retriever — thin convenience wrapper around FAISSStore.search().
Formats results into context strings for LLM prompts.
"""

from typing import Dict, List

from rag.faiss_store import FAISSStore


class Retriever:
    """Retrieves and formats documents from FAISS for LLM context injection."""

    def __init__(self, store: FAISSStore):
        self.store = store

    def retrieve(self, index_name: str, query: str, top_k: int = 5) -> List[Dict]:
        return self.store.search(index_name, query, top_k)

    @staticmethod
    def format_context(docs: List[Dict]) -> str:
        """Format retrieved docs as numbered context block."""
        if not docs:
            return "No relevant documents found in the knowledge base."
        lines = []
        for i, doc in enumerate(docs, 1):
            score = doc.get("score", 0.0)
            content = doc.get("content", "")
            lines.append(f"[Doc {i}] (relevance: {score:.2f})\n{content}")
        return "\n\n".join(lines)
