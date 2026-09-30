"""
Alita Knowledge Graph — Multi-hop Relational Reasoning Engine
==============================================================
Stores entity-relationship triples and traverses them for multi-hop
question answering.  Enables reasoning chains like:

  "Remember my sister is Priya"  → (sarwan, sister, priya)
  "Priya works at Google"        → (priya, works_at, google)
  "Where does my sister work?"   → sarwan→sister→priya→works_at→google → "Google"

Features:
  - File-backed JSON persistence (data/knowledge_graph.json)
  - Multi-hop traversal (up to 4 hops)
  - Fuzzy entity matching (case-insensitive, alias resolution)
  - Automatic triple extraction from natural language
  - Per-user graph isolation
  - Context injection into system prompt via get_relevant_context()
  - Thread-safe read/write with locking

Zero VRAM — pure data structure, no ML models.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

log = logging.getLogger("alita.knowledge_graph")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_GRAPH_PATH = os.path.join(_DATA_DIR, "knowledge_graph.json")


# ── Relation extraction patterns ────────────────────────────────────────────
# Maps natural language patterns to structured relation types.
# Each pattern captures (subject, relation, object) from user input.
RELATION_PATTERNS: list[Tuple[re.Pattern, str, int, int]] = [
    # English patterns
    (re.compile(r"(?:my|the)\s+(\w+(?:\s+\w+)?)\s+(?:is|are)\s+(.+)", re.I), "is", 1, 2),
    (re.compile(r"(\w+)\s+is\s+my\s+(\w+)", re.I), "is_relation_of_user", 1, 2),
    (re.compile(r"(\w+)\s+works?\s+(?:at|for|in)\s+(.+)", re.I), "works_at", 1, 2),
    (re.compile(r"(\w+)\s+lives?\s+(?:in|at)\s+(.+)", re.I), "lives_in", 1, 2),
    (re.compile(r"(\w+)\s+studies?\s+(?:at|in)\s+(.+)", re.I), "studies_at", 1, 2),
    (re.compile(r"(\w+)\s+(?:is married to|married)\s+(.+)", re.I), "married_to", 1, 2),
    (re.compile(r"(\w+)(?:'s|s)\s+(?:phone|number|email|address)\s+is\s+(.+)", re.I), "contact_info", 1, 2),
    (re.compile(r"(\w+)\s+(?:loves?|likes?|enjoys?)\s+(.+)", re.I), "likes", 1, 2),
    (re.compile(r"(\w+)\s+(?:hates?|dislikes?)\s+(.+)", re.I), "dislikes", 1, 2),
    (re.compile(r"(\w+)\s+(?:is\s+(?:a|the)\s+)?(?:friend|buddy|pal)\s+of\s+(.+)", re.I), "friend_of", 1, 2),
    (re.compile(r"(\w+)\s+(?:knows?|met)\s+(.+)", re.I), "knows", 1, 2),
    (re.compile(r"(\w+)(?:'s|s)\s+(birthday|age|nickname)\s+is\s+(.+)", re.I), "attribute", 1, 3),
    # Hindi/Hinglish patterns
    (re.compile(r"(?:meri|mera|mere)\s+(\w+)\s+(?:ka naam|hai)\s+(.+)", re.I), "is", 1, 2),
    (re.compile(r"(\w+)\s+(?:kaam karta|kaam karti)\s+(?:hai\s+)?(.+)\s+(?:mein|pe|par)", re.I), "works_at", 1, 2),
    (re.compile(r"(\w+)\s+(?:rehta|rehti)\s+(?:hai\s+)?(.+)\s+(?:mein|pe|par)", re.I), "lives_in", 1, 2),
]

# Relation families for inverse traversal
INVERSE_RELATIONS: dict[str, str] = {
    "sister": "sibling_of",
    "brother": "sibling_of",
    "mother": "child_of",
    "father": "child_of",
    "wife": "married_to",
    "husband": "married_to",
    "friend": "friend_of",
    "boss": "reports_to",
    "colleague": "works_with",
}

# "My X is Y" → relation type is X (sister, brother, friend, etc.)
FAMILY_RELATIONS = {
    "sister", "brother", "mother", "father", "mom", "dad", "wife", "husband",
    "son", "daughter", "uncle", "aunt", "cousin", "grandmother", "grandfather",
    "grandma", "grandpa", "nephew", "niece", "boyfriend", "girlfriend",
    "bhai", "behen", "maa", "papa", "didi", "bhaiya",
}


class Triple:
    """A single subject-relation-object triple with metadata."""

    __slots__ = ("subject", "relation", "object", "user_id", "timestamp", "source")

    def __init__(
        self,
        subject: str,
        relation: str,
        obj: str,
        user_id: str = "default",
        timestamp: float = 0.0,
        source: str = "user",
    ):
        self.subject = subject.strip().lower()
        self.relation = relation.strip().lower()
        self.object = obj.strip().lower()
        self.user_id = user_id
        self.timestamp = timestamp or time.time()
        self.source = source

    def to_dict(self) -> dict:
        return {
            "s": self.subject,
            "r": self.relation,
            "o": self.object,
            "uid": self.user_id,
            "ts": self.timestamp,
            "src": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Triple":
        return cls(
            subject=d["s"],
            relation=d["r"],
            obj=d["o"],
            user_id=d.get("uid", "default"),
            timestamp=d.get("ts", 0.0),
            source=d.get("src", "user"),
        )

    def __repr__(self) -> str:
        return f"({self.subject} --[{self.relation}]--> {self.object})"


class KnowledgeGraph:
    """
    Thread-safe multi-hop relational knowledge graph.

    Storage: adjacency lists indexed by subject AND object for bidirectional
    traversal. Persisted as JSON on every write.
    """

    def __init__(self, graph_path: str = _GRAPH_PATH, storage_path: Optional[str] = None):
        self._path = storage_path or graph_path
        self._lock = threading.RLock()
        # subject → list[Triple]
        self._forward: dict[str, list[Triple]] = defaultdict(list)
        # object → list[Triple]
        self._reverse: dict[str, list[Triple]] = defaultdict(list)
        # entity aliases → canonical name
        self._aliases: dict[str, str] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load graph from disk."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            triples = [Triple.from_dict(t) for t in data.get("triples", [])]
            self._aliases = data.get("aliases", {})
            for t in triples:
                self._forward[t.subject].append(t)
                self._reverse[t.object].append(t)
            log.info("Knowledge graph loaded: %d triples, %d entities.",
                     len(triples), len(self._forward))
        except Exception as exc:
            log.warning("Failed to load knowledge graph: %s", exc)

    def _save(self) -> None:
        """Persist graph to disk."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            all_triples = []
            seen = set()
            for triples in self._forward.values():
                for t in triples:
                    key = (t.subject, t.relation, t.object, t.user_id)
                    if key not in seen:
                        seen.add(key)
                        all_triples.append(t.to_dict())
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"triples": all_triples, "aliases": self._aliases}, f,
                          ensure_ascii=False, indent=2)
        except Exception as exc:
            log.error("Failed to save knowledge graph: %s", exc)

    # ── Entity resolution ────────────────────────────────────────────────────

    def _resolve(self, name: str) -> str:
        """Resolve entity name through aliases to canonical form."""
        name = name.strip().lower()
        return self._aliases.get(name, name)

    def add_alias(self, alias: str, canonical: str) -> None:
        """Register an alias for an entity."""
        with self._lock:
            self._aliases[alias.strip().lower()] = canonical.strip().lower()
            self._save()

    # ── Add / Remove ─────────────────────────────────────────────────────────

    def add_triple(
        self,
        subject: str,
        relation: str,
        obj: str,
        user_id: str = "default",
        source: str = "user",
    ) -> Triple:
        """Add a relationship triple to the graph."""
        with self._lock:
            subject = self._resolve(subject)
            obj_resolved = self._resolve(obj)
            # Dedup: don't add if same (s, r, o, uid) already exists
            for existing in self._forward.get(subject, []):
                if (existing.relation == relation.strip().lower()
                        and existing.object == obj_resolved
                        and existing.user_id == user_id):
                    existing.timestamp = time.time()  # refresh timestamp
                    self._save()
                    return existing

            t = Triple(subject, relation, obj_resolved, user_id, source=source)
            self._forward[t.subject].append(t)
            self._reverse[t.object].append(t)
            self._save()
            log.info("KG+ %s (user=%s)", t, user_id)
            return t

    def remove_triple(self, subject: str, relation: str, obj: str, user_id: str = "default") -> bool:
        """Remove a specific triple."""
        with self._lock:
            subject = self._resolve(subject)
            obj = self._resolve(obj)
            relation = relation.strip().lower()
            removed = False
            if subject in self._forward:
                before = len(self._forward[subject])
                self._forward[subject] = [
                    t for t in self._forward[subject]
                    if not (t.relation == relation and t.object == obj and t.user_id == user_id)
                ]
                removed = len(self._forward[subject]) < before
            if obj in self._reverse:
                self._reverse[obj] = [
                    t for t in self._reverse[obj]
                    if not (t.relation == relation and t.subject == subject and t.user_id == user_id)
                ]
            if removed:
                self._save()
            return removed

    # ── Query ────────────────────────────────────────────────────────────────

    def get_relations(self, entity: str, user_id: Optional[str] = None) -> list[Triple]:
        """Get all triples where entity is subject OR object."""
        entity = self._resolve(entity)
        results: list[Triple] = []
        for t in self._forward.get(entity, []):
            if user_id is None or t.user_id == user_id:
                results.append(t)
        for t in self._reverse.get(entity, []):
            if user_id is None or t.user_id == user_id:
                results.append(t)
        return results

    def get_objects(self, subject: str, relation: Optional[str] = None,
                    user_id: Optional[str] = None) -> list[str]:
        """Get all objects for a given subject (optionally filtered by relation)."""
        subject = self._resolve(subject)
        results = []
        for t in self._forward.get(subject, []):
            if (relation is None or t.relation == relation.strip().lower()):
                if user_id is None or t.user_id == user_id:
                    results.append(t.object)
        return results

    def get_subjects(self, obj: str, relation: Optional[str] = None,
                     user_id: Optional[str] = None) -> list[str]:
        """Get all subjects pointing to a given object."""
        obj = self._resolve(obj)
        results = []
        for t in self._reverse.get(obj, []):
            if (relation is None or t.relation == relation.strip().lower()):
                if user_id is None or t.user_id == user_id:
                    results.append(t.subject)
        return results

    # ── Multi-hop traversal ──────────────────────────────────────────────────

    def traverse(
        self,
        start: str,
        max_hops: int = 4,
        user_id: Optional[str] = None,
    ) -> list[list[Triple]]:
        """
        BFS traversal from a starting entity, returning all reachable paths.
        Returns list of paths, where each path is a list of triples.
        """
        start = self._resolve(start)
        visited: Set[str] = {start}
        # Each queue item: (current_entity, path_so_far)
        queue: list[Tuple[str, list[Triple]]] = [(start, [])]
        all_paths: list[list[Triple]] = []

        for _hop in range(max_hops):
            next_queue: list[Tuple[str, list[Triple]]] = []
            for entity, path in queue:
                for t in self._forward.get(entity, []):
                    if user_id and t.user_id != user_id:
                        continue
                    new_path = path + [t]
                    all_paths.append(new_path)
                    if t.object not in visited:
                        visited.add(t.object)
                        next_queue.append((t.object, new_path))
            queue = next_queue
            if not queue:
                break

        return all_paths

    def find_path(
        self,
        start: str,
        end: str,
        max_hops: int = 4,
        user_id: Optional[str] = None,
    ) -> Optional[list[Triple]]:
        """Find shortest path between two entities (BFS)."""
        start = self._resolve(start)
        end = self._resolve(end)
        if start == end:
            return []

        visited: Set[str] = {start}
        queue: list[Tuple[str, list[Triple]]] = [(start, [])]

        for _hop in range(max_hops):
            next_queue: list[Tuple[str, list[Triple]]] = []
            for entity, path in queue:
                for t in self._forward.get(entity, []):
                    if user_id and t.user_id != user_id:
                        continue
                    new_path = path + [t]
                    if t.object == end:
                        return new_path
                    if t.object not in visited:
                        visited.add(t.object)
                        next_queue.append((t.object, new_path))
                # Also check reverse direction
                for t in self._reverse.get(entity, []):
                    if user_id and t.user_id != user_id:
                        continue
                    new_path = path + [t]
                    if t.subject == end:
                        return new_path
                    if t.subject not in visited:
                        visited.add(t.subject)
                        next_queue.append((t.subject, new_path))
            queue = next_queue
            if not queue:
                break

        return None

    # ── Natural language extraction ──────────────────────────────────────────

    async def extract_with_llm(
        self,
        text: str,
        user_id: str = "default",
        llm_fn: Optional[Callable] = None,
        timeout: float = 4.0,
    ) -> list[Triple]:
        """
        Extract personal facts using an LLM.
        Falls back to deterministic regex extraction if LLM fails, times out, or returns invalid format.
        """
        if not llm_fn:
            return self.extract_and_store(text, user_id=user_id)

        prompt = (
            "Extract all personal facts and relationships about the user from this text.\n"
            "Return ONLY a JSON array of objects with keys 's' (subject, or 'user'), 'r' (relation, e.g. 'sister', 'works_at', 'lives_in'), 'o' (object).\n"
            "Example: [{\"s\": \"user\", \"r\": \"sister\", \"o\": \"priya\"}]\n"
            "If there are no personal facts, return: []\n\n"
            f"Text: \"{text}\""
        )

        try:
            llm_result = llm_fn(prompt)
            if inspect.iscoroutine(llm_result):
                response_str = await asyncio.wait_for(llm_result, timeout=timeout)
            else:
                response_str = await asyncio.to_thread(llm_fn, prompt)

            cleaned = str(response_str).strip()
            if "```" in cleaned:
                m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", cleaned, re.DOTALL)
                if m:
                    cleaned = m.group(1).strip()

            start_idx = cleaned.find("[")
            end_idx = cleaned.rfind("]")
            if start_idx != -1 and end_idx != -1:
                cleaned = cleaned[start_idx : end_idx + 1]

            facts = json.loads(cleaned)
            triples: list[Triple] = []
            if isinstance(facts, list):
                for fact in facts:
                    if isinstance(fact, dict):
                        s = fact.get("s") or fact.get("subject", "user")
                        r = fact.get("r") or fact.get("relation", "")
                        o = fact.get("o") or fact.get("object", "")
                        if s and r and o:
                            t = self.add_triple(str(s), str(r), str(o), user_id=user_id)
                            triples.append(t)
            return triples
        except Exception as exc:
            log.debug("LLM extraction failed (%s), falling back to regex", exc)
            return self.extract_and_store(text, user_id=user_id)

    def extract_and_store(self, text: str, user_id: str = "default") -> list[Triple]:
        """
        Extract entity-relation-object triples from natural language text
        and store them in the graph.
        """
        stored: list[Triple] = []
        text_clean = text.strip()

        # Check for "my X is Y" family relation pattern first
        m_family = re.match(
            r"(?:my|meri|mera|mere)\s+(\w+(?:\s+\w+)?)\s+(?:is|hai|ka naam hai|ka naam)\s+(.+)",
            text_clean, re.I
        )
        if m_family:
            relation_word = m_family.group(1).strip().lower()
            obj_name = m_family.group(2).strip().rstrip(".")
            if relation_word in FAMILY_RELATIONS:
                # "My sister is Priya" → (user, sister, priya)
                t = self.add_triple("user", relation_word, obj_name, user_id)
                stored.append(t)
                return stored
            else:
                # "My name is Sarwan" → (user, name, sarwan)
                t = self.add_triple("user", relation_word, obj_name, user_id)
                stored.append(t)
                return stored

        # Try all other relation patterns
        for pattern, relation, subj_group, obj_group in RELATION_PATTERNS:
            m = pattern.search(text_clean)
            if m:
                try:
                    subj = m.group(subj_group).strip().rstrip(".")
                    obj = m.group(obj_group).strip().rstrip(".")
                    if len(subj) > 1 and len(obj) > 1:
                        t = self.add_triple(subj, relation, obj, user_id)
                        stored.append(t)
                except (IndexError, AttributeError):
                    continue

        return stored

    # ── Context retrieval for LLM prompt injection ───────────────────────────

    def get_relevant_context(
        self,
        query: str,
        user_id: str = "default",
        max_facts: int = 8,
    ) -> str:
        """
        Given a user query, find relevant knowledge graph facts and format
        them as a context string for injection into the LLM system prompt.

        Strategy:
          1. Extract entity mentions from the query
          2. Look up all triples involving those entities
          3. Multi-hop traverse to find connected facts
          4. Format as natural language bullet points
        """
        if not self._forward and not self._reverse:
            return ""

        query_lower = query.lower()
        query_words = set(re.findall(r'\b\w{2,}\b', query_lower))

        # Collect all entities in user's graph
        user_entities: Set[str] = set()
        for subj, triples in self._forward.items():
            for t in triples:
                if t.user_id == user_id:
                    user_entities.add(subj)
                    user_entities.add(t.object)

        if not user_entities:
            return ""

        # Find which entities are mentioned in the query
        mentioned: Set[str] = set()
        for entity in user_entities:
            entity_words = set(entity.split())
            if entity_words & query_words:
                mentioned.add(entity)

        # Also check if "my" / "mera" → resolve "user" entity
        if any(w in query_lower for w in ("my", "meri", "mera", "mere", "i", "main")):
            mentioned.add("user")

        if not mentioned:
            # No direct entity mention — check relation words
            for word in query_words:
                if word in FAMILY_RELATIONS or word in INVERSE_RELATIONS:
                    mentioned.add("user")
                    break

        if not mentioned:
            return ""

        # Gather relevant triples via traversal
        relevant_triples: list[Triple] = []
        seen_keys: Set[Tuple[str, str, str]] = set()

        for entity in mentioned:
            paths = self.traverse(entity, max_hops=3, user_id=user_id)
            for path in paths:
                for t in path:
                    key = (t.subject, t.relation, t.object)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        relevant_triples.append(t)

        if not relevant_triples:
            return ""

        # Sort by recency, limit
        relevant_triples.sort(key=lambda t: t.timestamp, reverse=True)
        relevant_triples = relevant_triples[:max_facts]

        # Format as natural language
        facts: list[str] = []
        for t in relevant_triples:
            subj = t.subject if t.subject != "user" else "The user"
            rel = t.relation.replace("_", " ")
            facts.append(f"• {subj.title()} {rel} {t.object.title()}")

        if not facts:
            return ""

        return (
            "[KNOWLEDGE GRAPH — Verified Personal Facts]\n"
            + "\n".join(facts)
            + "\nUse these facts naturally when relevant. "
            "Never reveal you have a 'knowledge graph' — just recall these as things you remember."
        )

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self, user_id: Optional[str] = None) -> dict:
        """Return graph statistics."""
        with self._lock:
            all_triples = []
            for triples in self._forward.values():
                for t in triples:
                    if user_id is None or t.user_id == user_id:
                        all_triples.append(t)
            entities: Set[str] = set()
            relations: Set[str] = set()
            for t in all_triples:
                entities.add(t.subject)
                entities.add(t.object)
                relations.add(t.relation)
            return {
                "total_triples": len(all_triples),
                "total_entities": len(entities),
                "total_relation_types": len(relations),
                "entities": sorted(entities),
                "relation_types": sorted(relations),
            }


# ── Singleton ────────────────────────────────────────────────────────────────
knowledge_graph = KnowledgeGraph()
