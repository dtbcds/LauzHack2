"""Assemble a task DAG into layers with bounded zoom and vertical scrolling."""

from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

import flet as ft
import flet.canvas as canvas
import networkx as nx

import palette as p
from component import Task
from native_motion import GraphGestureSurface, GraphToolbar, GraphViewport
from graph_components import (
    HOTSPOT_SIZE, NODE_HEIGHT, NODE_WIDTH, bottleneck_marker, dependency_link, task_node,
)

COLUMN_GAP = 24
ROW_GAP = 48
MARGIN = 32


def task_dependencies(tasks: tuple[Task, ...]) -> nx.DiGraph:
    """Adapt the UI fixtures. Production edges can come from graph_to_ui_data."""
    graph = nx.DiGraph()
    titles: dict[str, list[str]] = {}

    for task in tasks:
        if task.id in graph:
            raise ValueError(f"Duplicate task ID: {task.id}")

        graph.add_node(task.id)
        titles.setdefault(task.title, []).append(task.id)

    def resolve(reference: str) -> str:
        if reference in graph:
            return reference

        matches = titles.get(reference, [])
        if len(matches) != 1:
            raise ValueError(f"Unknown or ambiguous task reference: {reference}")

        return matches[0]

    for task in tasks:
        for prerequisite in task.prerequisites:
            graph.add_edge(resolve(prerequisite), task.id, type="hard")

        for dependent in task.dependents:
            graph.add_edge(task.id, resolve(dependent), type="hard")

    return graph


class TaskGraph:
    def __init__(self, on_select: Callable[[Task], None]) -> None:
        self._on_select = on_select
        self._tasks: dict[str, Task] = {}
        self._graph = nx.DiGraph()
        self._positions: dict[str, tuple[float, float]] = {}
        self._channel = f"graph-{id(self)}"

        self._scene = ft.Stack(width=1, height=1)
        self._message = ft.Text(size=p.CONTROL_TEXT, color=p.MUTED, visible=False)
        self._scope_summary = ft.Text(
            size=p.NOTE_TEXT, color=p.MUTED,
            tooltip=(
                "Hotspots mark bottlenecks affecting the filtered tasks. "
                "Blue blocks your work; red blocks other people’s work. "
                "Two colors means both."
            ),
        )

        self._viewer = GraphViewport(
            self._scene, channel=self._channel, expand=True,
        )
        self.control = ft.Column(
            [
                ft.Row([
                    ft.Text("Prerequisite ↓ dependent", size=p.NOTE_TEXT, color=p.MUTED),
                    ft.Container(expand=True),
                    GraphToolbar(channel=self._channel, width=110, height=40),
                ], spacing=4),
                self._scope_summary,
                self._message,
                self._viewer,
            ],
            spacing=p.SMALL,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            visible=False,
        )

    def gesture_surface(self, content: ft.Control, **layout: Any) -> GraphGestureSurface:
        return GraphGestureSurface(content, channel=self._channel, **layout)

    def set_tasks(
        self,
        tasks: tuple[Task, ...],
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        """Accept graph_construction.graph_to_ui_data snapshots when available."""
        self._tasks = {task.id: task for task in tasks}
        self._positions = {}
        self._viewer.reset_token += 1

        try:
            layers = None

            if snapshot is None:
                graph = task_dependencies(tasks)
            else:
                graph = nx.DiGraph()
                graph.add_nodes_from(self._tasks)

                for edge in snapshot["edges"]:
                    if edge["source"] not in graph or edge["target"] not in graph:
                        raise ValueError("A graph link references an unknown task")

                    graph.add_edge(edge["source"], edge["target"], **edge)

                layers = {node["id"]: node["layer"] for node in snapshot["nodes"]}

            generations = list(nx.topological_generations(graph))
            self._graph = graph
            max_columns = max((len(layer) for layer in generations), default=1)

            for index, generation in enumerate(generations):
                ordered = sorted(
                    generation, key=lambda key: (-self._tasks[key].score, key)
                )
                offset = (max_columns - len(ordered)) * (NODE_WIDTH + COLUMN_GAP) / 2

                for column, key in enumerate(ordered):
                    layer = layers[key] if layers is not None else index
                    self._positions[key] = (
                        MARGIN + offset + column * (NODE_WIDTH + COLUMN_GAP),
                        MARGIN + layer * (NODE_HEIGHT + ROW_GAP),
                    )

            self._message.value = "No tasks in this organisation." if not tasks else ""

        except (ValueError, KeyError, nx.NetworkXUnfeasible) as error:
            self._graph = nx.DiGraph()
            self._positions = {}
            self._message.value = f"Cannot display dependencies. {error}"

        self._message.visible = bool(self._message.value)
        self._viewer.visible = bool(self._positions)

    def render(
        self,
        selected: Task | None,
        highlighted: set[str],
        in_scope: set[str],
    ) -> None:
        positions = self._positions
        shapes: list[canvas.Shape] = []
        nodes: list[ft.Control] = []
        markers: list[ft.Control] = []
        active_tasks = [
            key for key, task in self._tasks.items()
            if task.status.casefold() not in {"done", "complete", "completed"}
            and key in self._graph
        ]
        active_dependencies = self._graph.subgraph(active_tasks)
        hard_dependencies = nx.DiGraph()
        hard_dependencies.add_nodes_from(active_tasks)

        for source, target, attributes in active_dependencies.edges(data=True):
            if attributes.get("type") != "soft":
                hard_dependencies.add_edge(source, target)

        marked_tasks = {}

        for key in active_tasks:
            if not self._tasks[key].bottleneck:
                continue

            downstream = nx.descendants(hard_dependencies, key)
            matches = downstream.intersection(in_scope)
            if downstream and (key in in_scope or matches):
                marked_tasks[key] = downstream

        blocks_you = {
            key for key, downstream in marked_tasks.items()
            if any(self._tasks[task_id].owner == "You" for task_id in downstream)
        }
        blocks_others = {
            key for key, downstream in marked_tasks.items()
            if any(self._tasks[task_id].owner not in {"You", "", "Unknown"}
                   for task_id in downstream)
        }
        self._scope_summary.spans = [
            ft.TextSpan(f"{len(in_scope)} matching tasks · "),
            ft.TextSpan(
                f"● Blocking you {len(blocks_you)}",
                style=ft.TextStyle(color=p.ACCENT),
            ),
            ft.TextSpan(" · "),
            ft.TextSpan(
                f"● Blocking others {len(blocks_others)}",
                style=ft.TextStyle(color=p.BOTTLENECK),
            ),
        ]

        arrivals: dict[str, list[str]] = {}

        for source, target, attributes in self._graph.edges(data=True):
            start_x, start_y = positions[source]
            end_x, end_y = positions[target]
            source_task = self._tasks[source]
            completed = source_task.status.casefold() in {
                "done",
                "complete",
                "completed",
            }
            if source in marked_tasks and hard_dependencies.has_edge(source, target):
                arrivals.setdefault(target, []).append(source)

            shapes.extend(
                dependency_link(
                    (start_x + NODE_WIDTH / 2, start_y + NODE_HEIGHT),
                    (end_x + NODE_WIDTH / 2, end_y),
                    highlighted=source in highlighted and target in highlighted,
                    blocking=source in marked_tasks and not completed,
                    soft=attributes.get("type") == "soft",
                )
            )

        for key, (left, top) in positions.items():
            task = self._tasks[key]
            blockers = []

            for predecessor in self._graph.predecessors(key):
                prerequisite = self._tasks[predecessor]
                hard_link = self._graph.edges[predecessor, key].get("type") != "soft"

                if hard_link and prerequisite.status.casefold() not in {
                    "done",
                    "complete",
                    "completed",
                }:
                    blockers.append(prerequisite.title)

            node = task_node(
                task,
                partial(self._on_select, task),
                blocked_by=tuple(blockers),
                selected=selected is not None and selected.id == key,
                highlighted=key in highlighted,
                in_scope=key in in_scope,
            )
            node.left, node.top = left, top
            nodes.append(node)

        for target, sources in arrivals.items():
            task = self._tasks[target]
            left, top = positions[target]
            affects_you = any(source in blocks_you for source in sources)
            affects_others = any(source in blocks_others for source in sources)
            prerequisites = tuple(self._tasks[source].title for source in sources)

            marker = bottleneck_marker(
                task, partial(self._on_select, task),
                waiting_on=prerequisites,
                blocks_you=affects_you,
                blocks_others=affects_others,
            )
            marker.left = left + NODE_WIDTH / 2 - HOTSPOT_SIZE / 2
            marker.top = top - HOTSPOT_SIZE / 2
            markers.append(marker)

        width = max((x + NODE_WIDTH + MARGIN for x, y in positions.values()), default=1)
        height = max(
            (y + NODE_HEIGHT + MARGIN for x, y in positions.values()), default=1
        )
        links = canvas.Canvas(shapes=shapes, width=width, height=height)

        self._scene.width = width
        self._scene.height = height
        self._viewer.scene_width = width
        self._viewer.scene_height = height
        self._scene.controls = [links]
        self._scene.controls.extend(nodes)
        self._scene.controls.extend(markers)

