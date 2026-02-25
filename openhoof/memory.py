"""
Memory — Persistent recall with semantic search.

The Memory system:
- Loads MEMORY.md (long-term context)
- Appends daily logs (memory/YYYY-MM-DD.md)
- Semantic search before answering
- Lightweight vector DB (deferred: FAISS or SQLite embeddings)

Phase 1: Simple text search (grep-like)
Phase 2: Proper embeddings
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List


class MemorySearchResult:
    """A single search result with context."""
    
    def __init__(self, path: str, line_num: int, line: str, score: float = 1.0):
        self.path = path
        self.line_num = line_num
        self.line = line
        self.score = score
    
    def __repr__(self) -> str:
        return f"MemorySearchResult(path={self.path!r}, line={self.line_num}, score={self.score:.2f})"


class Memory:
    """Agent memory loaded from MEMORY.md + memory/*.md files."""
    
    def __init__(self, base_path: str):
        self.base_path = Path(base_path).resolve()
        self.memory_dir = self.base_path.parent / "memory"
        self.memory_dir.mkdir(exist_ok=True)
        
        self.content = ""
        if self.base_path.exists():
            self.content = self.base_path.read_text()
    
    @classmethod
    def from_file(cls, path: str) -> Memory:
        """Load MEMORY.md from file."""
        return cls(path)
    
    def search(self, query: str, max_results: int = 5) -> List[MemorySearchResult]:
        """
        Search memory for relevant context.
        
        Phase 1: Simple case-insensitive substring match.
        Phase 2: Semantic embeddings (FAISS or SQLite).
        """
        results = []
        query_lower = query.lower()
        
        # Search MEMORY.md
        if self.base_path.exists():
            results.extend(self._search_file(self.base_path, query_lower))
        
        # Search memory/*.md daily logs
        for log_file in sorted(self.memory_dir.glob("*.md"), reverse=True):
            results.extend(self._search_file(log_file, query_lower))
        
        # Sort by score (for now, just line length proximity)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]
    
    def _search_file(self, path: Path, query: str) -> List[MemorySearchResult]:
        """Search a single file for query."""
        if not path.exists():
            return []
        
        results = []
        lines = path.read_text().split("\n")
        
        for i, line in enumerate(lines, start=1):
            if query in line.lower():
                # Simple scoring: more query occurrences = higher score
                score = line.lower().count(query)
                results.append(MemorySearchResult(
                    path=str(path),
                    line_num=i,
                    line=line.strip(),
                    score=float(score)
                ))
        
        return results
    
    def append(self, text: str):
        """Append to MEMORY.md."""
        with open(self.base_path, "a") as f:
            f.write(f"\n{text}\n")
    
    def log_daily(self, text: str):
        """Append to today's daily log (memory/YYYY-MM-DD.md)."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.memory_dir / f"{today}.md"
        
        # Create with header if new
        if not log_file.exists():
            log_file.write_text(f"# Daily Log: {today}\n\n")
        
        with open(log_file, "a") as f:
            timestamp = datetime.now().strftime("%H:%M:%S")
            f.write(f"**{timestamp}** — {text}\n")
    
    def recall(self, context: str) -> str:
        """
        Recall relevant memory given a context string.
        Returns formatted search results.
        """
        results = self.search(context, max_results=3)
        
        if not results:
            return "(No relevant memory found)"
        
        lines = ["# Memory Recall\n"]
        for r in results:
            lines.append(f"**{Path(r.path).name}:{r.line_num}** — {r.line}")
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        return f"Memory(path={self.base_path}, daily_logs={len(list(self.memory_dir.glob('*.md')))})"
