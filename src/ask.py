"""The shared Queries panel for inspecting an organisation's task dependencies."""

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

import palette as p
from component import Task
from queries import TaskQueries

QUESTIONS = {
    "plan": ("Plan my work", "Find the order that keeps your teammates moving."),
    "slip": ("Check a delay", "See what work is at risk if a task slips."),
    "blocked": ("Trace blockers", "See what’s holding up a task and who to follow up with."),
    "teammate": ("Unblock a teammate", "Find the task that would free up the most work for them."),
}


@dataclass(frozen=True)
class Answer:
    text: str
    rows: tuple[tuple[Task, str], ...] = ()
    related: tuple[Task, ...] = ()


def _answer(
    queries: TaskQueries,
    question: str,
    *,
    owner: str,
    deadline: str,
    task: str,
    teammate: str,
) -> Answer:
    if question == "plan":
        steps = queries.plan_until(owner, deadline)
        if not steps:
            return Answer(f"No unfinished work for {owner} is due or needed by {deadline}.")
        first = steps[0]
        text = f"Start with {first.task.title}. It’s needed by {first.needed_by:%d %b %Y}."
        if first.external_blockers:
            blocker = first.external_blockers[-1].blocker
            text = f"Put {first.task.title} first in your plan. Follow up with {blocker.owner or 'the task owner'} about {blocker.title} before it can move."
        rows = []
        related = []
        for index, step in enumerate(steps, start=1):
            names = sorted({item.owner for item in step.teammate_tasks if item.owner})
            detail = f"{index}. Needed by {step.needed_by:%d %b}"
            if names:
                detail += " · Unblocks " + ", ".join(names)
            if step.external_blockers:
                detail += "\nWaiting on " + ", ".join(
                    dict.fromkeys(path.blocker.title for path in step.external_blockers)
                )
            rows.append((step.task, detail))
            related.extend(step.teammate_tasks)
            related.extend(item for path in step.external_blockers for item in path.chain)
        return Answer(text, tuple(rows), tuple(related))

    if question == "slip":
        impact = queries.slip_impact(task)
        if not (impact.direct or impact.indirect):
            return Answer(f"No unfinished downstream tasks are waiting on {impact.task.title}.", related=(impact.task,))
        direct, indirect = len(impact.direct), len(impact.indirect)
        if direct == 1 and not indirect:
            text = f"A delay to {impact.task.title} could hold up {impact.direct[0].title}."
            if impact.earliest_deadline:
                text += f" It’s due {impact.earliest_deadline:%d %b %Y}."
        else:
            groups = []
            if direct:
                groups.append(f"{direct} {'task' if direct == 1 else 'tasks'} directly")
            if indirect:
                groups.append(f"{indirect} {'more' if direct else 'tasks'} indirectly")
            text = f"A delay to {impact.task.title} could affect {' and '.join(groups)}."
            if impact.earliest_deadline:
                text += f" The earliest downstream deadline is {impact.earliest_deadline:%d %b %Y}."
        rows = tuple(
            (item, f"{kind} · {item.owner or 'Unassigned'}")
            for kind, tasks in (("Direct", impact.direct), ("Indirect", impact.indirect))
            for item in tasks
        )
        return Answer(text, rows, (impact.task,))

    if question == "blocked":
        paths = queries.blockers_for(task)
        if not paths:
            return Answer("There are no unfinished prerequisites in this task’s dependency chain.")
        first = paths[-1].blocker
        count = len(paths)
        return Answer(
            f"{paths[0].chain[-1].title} is waiting on {count} unfinished "
            f"{'task' if count == 1 else 'tasks'}. "
            f"Follow up with {first.owner or 'the task owner'} about {first.title}.",
            tuple(
                (
                    path.blocker,
                    f"{path.blocker.owner or 'Unassigned'} · " + " → ".join(item.title for item in path.chain[1:]),
                )
                for path in paths
            ),
            (paths[0].chain[-1],),
        )

    impact = queries.best_unblock_for(owner, teammate)
    if impact is None:
        return Answer(f"None of {owner}’s unfinished tasks currently unblock work for {teammate}.")
    count = len(impact.affected_tasks)
    return Answer(
        f"Prioritize {impact.task.title}. It unblocks {count} unfinished "
        f"{'task' if count == 1 else 'tasks'} for {teammate}.",
        ((impact.task, f"Your task · {owner}"),)
        + tuple((item, f"Waiting downstream · {teammate}") for item in impact.affected_tasks),
    )


def ask_panel(
    tasks: tuple[Task, ...],
    close: Callable[[], None],
    highlight: Callable[[set[str]], None],
    open_task: Callable[[Task], None],
) -> ft.Column:
    owners = {name: name for name in sorted({task.owner for task in tasks if task.owner})}
    queries = TaskQueries(tasks)
    question = None
    content = ft.ListView(expand=True, spacing=p.MEDIUM, padding=p.LARGE)
    result = ft.Column(spacing=p.MEDIUM)
    message = ft.Text(size=p.NOTE_TEXT, color=p.AMBER, visible=False)

    def heading(label):
        return ft.Text(label, size=p.SECTION_TITLE, color=p.TEXT, weight=ft.FontWeight.W_600)

    def action(label, callback, icon=None):
        return ft.TextButton(
            label, icon=icon, height=p.CONTROL_HEIGHT, style=p.control_button_style(), on_click=callback
        )

    def option_row(title, on_click, *, detail=None, icon=None):
        label = ft.Text(title, size=p.BODY_TEXT, color=p.TEXT, weight=ft.FontWeight.W_600)
        body = ft.Column(
            [label]
            + ([ft.Text(detail, size=p.NOTE_TEXT, color=p.MUTED, weight=ft.FontWeight.W_400)] if detail else []),
            spacing=4,
            expand=True,
        )
        return ft.TextButton(
            content=ft.Row(
                [
                    *([ft.Icon(icon, size=16, color=p.MUTED)] if icon else []),
                    body,
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=p.MUTED),
                ],
                spacing=p.SMALL,
            ),
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=p.SMALL, vertical=p.SMALL),
                shape=ft.RoundedRectangleBorder(radius=5),
            ),
            on_click=on_click,
        )

    def clear_answer():
        result.controls = []
        message.visible = False
        highlight(set())

    def inputs_changed(_=None):
        if question is None:
            return
        clear_answer()
        run_button.disabled = not all(read() for _, _, read in fields[question])

    owner, _ = p.select_menu("Choose owner", owners, inputs_changed, expand=True)
    teammate, _ = p.select_menu("Choose teammate", owners, inputs_changed, expand=True)
    task_choice, _ = p.select_menu("Choose task", {task.id: task.title for task in tasks}, inputs_changed, expand=True)
    deadline = ft.TextField(
        hint_text="YYYY-MM-DD",
        tooltip="Deadline",
        expand=True,
        height=p.CONTROL_HEIGHT,
        dense=True,
        text_size=p.CONTROL_TEXT,
        bgcolor=p.CONTROL,
        border_color=p.DIVIDER,
        focused_border_color=p.ACCENT,
        border_radius=5,
        content_padding=ft.Padding.symmetric(horizontal=12),
        text_vertical_align=ft.VerticalAlignment.CENTER,
        on_change=inputs_changed,
    )
    owner_field = ("Your name", owner, lambda: owner.data)
    task_field = ("Task", task_choice, lambda: task_choice.data)
    fields = {
        "plan": (owner_field, ("Deadline", deadline, lambda: deadline.value.strip())),
        "slip": (task_field,),
        "blocked": (task_field,),
        "teammate": (owner_field, ("Teammate", teammate, lambda: teammate.data)),
    }

    def show_questions(_=None):
        nonlocal question
        question = None
        clear_answer()
        content.controls = [
            ft.Text("Queries", size=p.PANE_TITLE, weight=ft.FontWeight.W_700, color=p.TEXT),
            ft.Column(
                [
                    option_row(
                        QUESTIONS[key][0], lambda _, key=key: show_question(key), detail=QUESTIONS[key][1], icon=icon
                    )
                    for key, icon in (
                        ("plan", ft.Icons.LIST_ALT_OUTLINED),
                        ("slip", ft.Icons.SCHEDULE_OUTLINED),
                        ("blocked", ft.Icons.ACCOUNT_TREE_OUTLINED),
                        ("teammate", ft.Icons.PEOPLE_OUTLINE),
                    )
                ],
                spacing=p.SMALL,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ]

    def show_question(key):
        nonlocal question
        question = key
        inputs_changed()
        query_fields = fields[key]
        input_rows = []
        for index, (label, control, _) in enumerate(query_fields):
            row_controls = [
                ft.Text(label, width=68 if len(query_fields) > 1 else None, size=p.CONTROL_TEXT, color=p.MUTED),
                control,
            ]
            if index == len(query_fields) - 1:
                row_controls.append(run_button)
            input_rows.append(ft.Row(row_controls, spacing=p.SMALL, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        content.controls = [
            ft.Row(
                [
                    ft.TextButton(
                        "All queries",
                        icon=ft.Icons.ARROW_BACK,
                        height=p.CONTROL_HEIGHT,
                        style=ft.ButtonStyle(color=p.MUTED, padding=ft.Padding.only(right=p.SMALL)),
                        on_click=show_questions,
                    )
                ]
            ),
            heading(QUESTIONS[key][0]),
            ft.Text(QUESTIONS[key][1], size=p.CONTROL_TEXT, color=p.MUTED),
            ft.Column(input_rows, spacing=p.SMALL),
            message,
            result,
        ]

    def run(_):
        try:
            answer = _answer(
                queries,
                question,
                owner=owner.data,
                deadline=deadline.value.strip(),
                task=task_choice.data,
                teammate=teammate.data,
            )
        except ValueError:
            message.value = "Enter a valid deadline in YYYY-MM-DD format."
            message.visible = True
            return
        result.controls = [
            ft.Divider(height=p.SMALL, color=p.DIVIDER),
            heading("Answer"),
            ft.Text(answer.text, size=p.BODY_TEXT, color=p.TEXT, selectable=True),
        ]
        if answer.rows:
            result.controls.extend(
                [
                    ft.Divider(height=1, color=p.DIVIDER),
                    ft.Column(
                        [
                            ft.Text("Related tasks", size=p.CONTROL_TEXT, color=p.MUTED, weight=ft.FontWeight.W_600),
                            *[
                                option_row(
                                    item.title,
                                    lambda _, item=item: open_task(item),
                                    detail=detail,
                                )
                                for item, detail in answer.rows
                            ],
                        ],
                        spacing=p.SMALL,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ]
            )
        highlight({item.id for item, _ in answer.rows} | {item.id for item in answer.related})

    run_button = action("Run query", run)
    run_button.style.bgcolor = {ft.ControlState.DISABLED: p.CONTROL, ft.ControlState.DEFAULT: p.ACCENT}
    run_button.style.color = {ft.ControlState.DISABLED: p.MUTED, ft.ControlState.DEFAULT: p.BACKGROUND}
    show_questions()
    return ft.Column(
        [
            ft.Container(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.QUERY_STATS, size=19, color=p.MUTED),
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.Icons.CLOSE,
                            tooltip="Close Queries",
                            icon_size=18,
                            icon_color=p.MUTED,
                            on_click=lambda _: close(),
                        ),
                    ]
                ),
                padding=ft.Padding.only(left=p.LARGE, right=p.MEDIUM, top=p.SMALL),
            ),
            content,
        ],
        spacing=0,
        expand=True,
    )
