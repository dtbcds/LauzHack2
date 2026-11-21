"""Dependency queries for the tasks in one organisation."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from graphlib import TopologicalSorter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from component import Task


@dataclass(frozen=True)
class TaskPlanStep:
    task: Task
    needed_by: date
    teammate_tasks: tuple[Task, ...]
    earliest_teammate_deadline: date | None
    external_blockers: tuple[DependencyPath, ...]


@dataclass(frozen=True)
class SlipImpact:
    task: Task
    direct: tuple[Task, ...]
    indirect: tuple[Task, ...]
    earliest_deadline: date | None


@dataclass(frozen=True)
class DependencyPath:
    """One shortest chain from an unfinished blocker to the requested task."""

    chain: tuple[Task, ...]

    @property
    def blocker(self) -> Task:
        return self.chain[0]


@dataclass(frozen=True)
class TeammateImpact:
    task: Task
    affected_tasks: tuple[Task, ...]


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _owner(value: str | None) -> str:
    return (value or "").strip().casefold()


class TaskQueries:
    """Use task IDs where available, with unique titles supported for demo links."""

    def __init__(self, tasks: Iterable[Task]):
        self._tasks: dict[str, Task] = {}
        self._titles: dict[str, list[str]] = {}
        for task in tasks:
            if task.id in self._tasks:
                raise ValueError(f"Duplicate task ID: {task.id}")
            self._tasks[task.id] = task
            self._titles.setdefault(task.title, []).append(task.id)

        self._deadlines = {key: _date(task.deadline) for key, task in self._tasks.items()}
        self._upstream: dict[str, set[str]] = {key: set() for key in self._tasks}
        self._downstream: dict[str, set[str]] = {key: set() for key in self._tasks}
        for key, task in self._tasks.items():
            for reference in task.prerequisites:
                self._link(self._resolve(reference), key)
            for reference in task.dependents:
                self._link(key, self._resolve(reference))
        # Reject invalid dependency data before it can produce misleading answers.
        TopologicalSorter(self._upstream).prepare()

    def _resolve(self, reference: str) -> str:
        if reference in self._tasks:
            return reference
        matches = self._titles.get(reference, [])
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f"Ambiguous task title; use its ID: {reference}")
        raise ValueError(f"Unknown task: {reference}")

    def _link(self, prerequisite: str, dependent: str) -> None:
        self._upstream[dependent].add(prerequisite)
        self._downstream[prerequisite].add(dependent)

    def _open(self, key: str) -> bool:
        return self._tasks[key].status.strip().casefold() not in {"done", "complete", "completed"}

    def _reachable(
        self, start: str, edges: dict[str, set[str]],
    ) -> dict[str, tuple[str, ...]]:
        """Return each unfinished reachable task once, stopping at completed work."""
        if not self._open(start):
            return {}
        found = {start: (start,)}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in sorted(edges[current]):
                if neighbor not in found and self._open(neighbor):
                    found[neighbor] = (*found[current], neighbor)
                    queue.append(neighbor)
        del found[start]
        return found

    def _earliest(self, keys: Iterable[str]) -> date | None:
        return min(
            (deadline for key in keys if (deadline := self._deadlines[key]) is not None),
            default=None,
        )

    def _by_deadline(self, keys: Iterable[str]) -> tuple[Task, ...]:
        ordered = sorted(keys, key=lambda key: (self._deadlines[key] or date.max, key))
        return tuple(self._tasks[key] for key in ordered)

    def plan_until(self, owner: str, deadline: date | str) -> tuple[TaskPlanStep, ...]:
        """Order owned work needed by the inclusive deadline, without time estimates."""
        horizon = date.fromisoformat(deadline) if isinstance(deadline, str) else deadline
        person = _owner(owner)
        if not person:
            raise ValueError("An owner is required")
        owned = [
            key for key, task in self._tasks.items()
            if _owner(task.owner) == person and self._open(key)
        ]
        downstream = {key: self._reachable(key, self._downstream) for key in owned}
        needed_by = {
            key: due for key in owned
            if (due := self._earliest((key, *downstream[key]))) is not None and due <= horizon
        }
        planned = set(needed_by)
        upstream = {key: self._reachable(key, self._upstream) for key in planned}
        order = TopologicalSorter({key: planned.intersection(upstream[key]) for key in planned})
        order.prepare()
        ready = set(order.get_ready())
        result = []
        while ready:
            key = min(ready, key=lambda key: (needed_by[key], -len(downstream[key]), key))
            ready.remove(key)
            teammate_keys = [
                downstream_key for downstream_key in downstream[key]
                if (teammate := _owner(self._tasks[downstream_key].owner)) and teammate != person
            ]
            result.append(TaskPlanStep(
                task=self._tasks[key],
                needed_by=needed_by[key],
                teammate_tasks=self._by_deadline(teammate_keys),
                earliest_teammate_deadline=self._earliest(teammate_keys),
                external_blockers=tuple(
                    self._blocker_path(path) for blocker, path in upstream[key].items()
                    if _owner(self._tasks[blocker].owner) != person
                ),
            ))
            order.done(key)
            ready.update(order.get_ready())
        return tuple(result)

    def slip_impact(self, task: str) -> SlipImpact:
        """Show unfinished direct and indirect dependents, ordered by deadline."""
        key = self._resolve(task)
        paths = self._reachable(key, self._downstream)
        return SlipImpact(
            task=self._tasks[key],
            direct=self._by_deadline(link for link, path in paths.items() if len(path) == 2),
            indirect=self._by_deadline(link for link, path in paths.items() if len(path) > 2),
            earliest_deadline=self._earliest(paths),
        )

    def _blocker_path(self, path: tuple[str, ...]) -> DependencyPath:
        return DependencyPath(tuple(self._tasks[key] for key in reversed(path)))

    def blockers_for(self, task: str) -> tuple[DependencyPath, ...]:
        """Explain each unfinished prerequisite with a chain to the selected task."""
        paths = self._reachable(self._resolve(task), self._upstream)
        return tuple(self._blocker_path(path) for path in paths.values())

    def best_unblock_for(self, owner: str, teammate: str) -> TeammateImpact | None:
        """Find the owned task that unblocks the most unfinished work for a teammate."""
        person, target = _owner(owner), _owner(teammate)
        if not person or not target:
            raise ValueError("An owner and teammate are required")
        matches = []
        for key, task in self._tasks.items():
            if _owner(task.owner) != person or not self._open(key):
                continue
            affected = [
                link for link in self._reachable(key, self._downstream)
                if _owner(self._tasks[link].owner) == target
            ]
            if affected:
                matches.append((key, affected))
        if not matches:
            return None
        key, affected = min(
            matches, key=lambda match: (-len(match[1]), self._earliest(match[1]) or date.max, match[0]),
        )
        return TeammateImpact(self._tasks[key], self._by_deadline(affected))
