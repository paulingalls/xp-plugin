import re
from collections import namedtuple

import lifecycle
import overlap
from close import fail
from work import edit_plan, flip_status, missing_plan_refusal, plan_path

TERMINAL = ("[done]", "[retired]")
Milestone = namedtuple("Milestone", "heading status block members")


def _section(sprint_id):
    return rf"^### Sprint {re.escape(sprint_id)}(?!\d)[^\n]*\n(.*?)(?=^### |^## |\Z)"


def sprint_stories(plan, sprint_id):
    bodies = re.findall(_section(sprint_id), plan, re.M | re.S)
    return [card for body in bodies for card in re.findall(r"^#### .+$", body, re.M)]


def find(plan, sprint_id):
    target = re.search(_section(sprint_id), plan, re.M | re.S)
    owners = list(re.finditer(r"^## (?!#).+$", plan[: target.start()] if target else "", re.M))
    if not owners:
        return None
    start = owners[-1].start()
    following = re.search(r"^## (?!#).+$", plan[target.end() :], re.M)
    end = target.end() + following.start() if following else len(plan)
    block = plan[start:end]
    heading = block.splitlines()[0].rstrip()
    prefix, bracket, status = heading.rpartition("[")
    bodies = re.findall(r"^### Sprint [^\n]*\n(.*?)(?=^### |^## |\Z)", block, re.M | re.S)
    members = [card for body in bodies for card in re.findall(r"^#### .+$", body, re.M)]
    valid = bracket and status.endswith("]")
    return Milestone(prefix if valid else heading, status[:-1] if valid else "", block, members)


def candidate(plan, sprint_id):
    found = find(plan, sprint_id)
    terminal = found and found.members and all(m.endswith(TERMINAL) for m in found.members)
    return found if terminal and found.status == "in-progress" else None


def move(sprint_id, done=False):
    """Flip under the plan lock. Only the `done` arm refuses: a bracket the start
    arm cannot read is the lead's to write, never a reason to hold the sprint shut."""

    def mutate(text):
        found = candidate(text, sprint_id) if done else find(text, sprint_id)
        before, after = ("in-progress", "done") if done else ("planned", "in-progress")
        return flip_status(text, found.heading, before, after) if found else text

    if not edit_plan(mutate) and done:
        return (
            f"refused: Sprint {sprint_id}'s cards changed while `Done when:` ran — one is no"
            f" longer [done] or [retired]. Run `close.py sprint {sprint_id} start` again"
        )
    return ""


def cmd_done(sprint_id):
    if not (path := plan_path()).exists():
        return fail(f"refused: {missing_plan_refusal()}")
    if not (found := candidate(path.read_text(), sprint_id)):
        return fail(
            f"refused: no [in-progress] milestone owns `### Sprint {sprint_id}` with every"
            f" scheduled card [done] or [retired] — `close.py sprint {sprint_id} start`"
            " names the milestone when there is one to close"
        )
    try:
        commands = lifecycle.declared_commands(
            found.heading.strip(), found.block, label="Done when"
        )[1]
    except ValueError as error:
        return fail(str(error))
    for command in commands:
        if red := overlap.run_one("Done when:", command):
            return fail(red)
    if red := move(sprint_id, done=True):
        return fail(red)
    print(f"milestone done: {found.heading.strip()}")
    return 0
