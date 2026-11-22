"""Turn dependency query results into the text and task links shown in the panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from component import Task
    from queries import TaskQueries


@dataclass(frozen=True)
class Answer:
    text: str
    rows: tuple[tuple[Task, str], ...] = ()
    related: tuple[Task, ...] = ()


def build_answer(
    queries: TaskQueries,
    question: str,
    *,
    owner: str,
    deadline: str,
    task: str,
    teammate: str,
) -> Answer:
    if question == "plan":
        return _plan_answer(queries, owner, deadline)

    if question == "slip":
        return _delay_answer(queries, task)

    if question == "blocked":
        return _blockers_answer(queries, task)

    return _teammate_answer(queries, owner, teammate)


def _plan_answer(queries: TaskQueries, owner: str, deadline: str) -> Answer:
    steps = queries.plan_until(owner, deadline)
    if not steps:
        return Answer(f"No unfinished work for {owner} is due or needed by {deadline}.")

    first = steps[0]
    text = f"Start {owner}’s plan with {first.task.title}. It’s needed by {first.needed_by:%d %b %Y}."

    if first.external_blockers:
        text = f"Put {first.task.title} first in {owner}’s plan."
        blocker = queries.next_blocker(first.external_blockers)

        if blocker is None:
            text += " It’s still waiting on prerequisites."
        elif blocker.owner:
            text += (
                f" Follow up with {blocker.owner} about {blocker.title} "
                "before it can move."
            )
        else:
            text += f" {blocker.title} can start now, but it has no assigned owner."

    rows = []
    related: list[Task] = []

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

        for path in step.external_blockers:
            related.extend(path.chain)

    return Answer(text, tuple(rows), tuple(related))


def _delay_answer(queries: TaskQueries, task: str) -> Answer:
    impact = queries.slip_impact(task)
    if not (impact.direct or impact.indirect):
        return Answer(
            f"No unfinished downstream tasks are waiting on {impact.task.title}.",
            related=(impact.task,),
        )

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

    rows = []

    for kind, tasks in (("Direct", impact.direct), ("Indirect", impact.indirect)):
        for item in tasks:
            rows.append((item, f"{kind} · {item.owner or 'Unassigned'}"))

    return Answer(text, tuple(rows), (impact.task,))


def _blockers_answer(queries: TaskQueries, task: str) -> Answer:
    paths = queries.blockers_for(task)
    if not paths:
        return Answer(
            "There are no unfinished prerequisites in this task’s dependency chain."
        )

    first = queries.next_blocker(paths)
    count = len(paths)
    blocked_task = paths[0].chain[-1]
    text = (
        f"{blocked_task.title} is waiting on {count} unfinished "
        f"{'task' if count == 1 else 'tasks'}."
    )

    if first is not None:
        if first.owner:
            text += f" Follow up with {first.owner} about {first.title}. That task can start now."
        else:
            text += f" {first.title} can start now, but it has no assigned owner."

    rows = []

    for path in paths:
        owner = path.blocker.owner or "Unassigned"
        chain = " → ".join(item.title for item in path.chain[1:])
        rows.append((path.blocker, f"{owner} · {chain}"))

    return Answer(text, tuple(rows), (blocked_task,))


def _teammate_answer(queries: TaskQueries, owner: str, teammate: str) -> Answer:
    impact = queries.best_unblock_for(owner, teammate)

    if impact is None:
        return Answer(
            f"None of {owner}’s unfinished tasks currently unblock work for {teammate}."
        )

    rows = [(impact.task, f"Prerequisite · {owner}")]
    related = []
    ready = []
    waiting = []

    for task in impact.affected_tasks:
        blockers = impact.remaining_blockers[task.id]
        if blockers:
            waiting.append(task)
            titles = ", ".join(blocker.title for blocker in blockers)
            rows.append((task, f"{teammate} · Still waiting on {titles}"))
            related.extend(blockers)
        else:
            ready.append(task)
            rows.append((task, f"{teammate} · Can start once this prerequisite is done"))

    text = f"Prioritize {impact.task.title} for {owner}."
    if len(ready) == 1:
        text += f" Once it’s done, {teammate} can start {ready[0].title}."
    elif ready:
        text += f" Once it’s done, {teammate} can start {len(ready)} tasks."

    if len(waiting) == 1:
        other_tasks = ", ".join(
            blocker.title for blocker in impact.remaining_blockers[waiting[0].id]
        )
        text += f" {waiting[0].title} will still be waiting on {other_tasks}."
    elif waiting:
        text += f" {len(waiting)} of {teammate}’s tasks will still have other prerequisites."

    return Answer(text, tuple(rows), tuple(related))
