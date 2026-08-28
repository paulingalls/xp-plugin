import re
from collections import namedtuple

import lifecycle
import overlap
from close import fail
from work import edit_plan, flip_status, plan_path

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
    heading = block.splitlines()[0]
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
    refusal = []

    def mutate(text):
        found = candidate(text, sprint_id) if done else find(text, sprint_id)
        if not done and found and found.status in ("in-progress", "done"):
            return text
        if not found or (not done and found.status != "planned"):
            refusal.append(f"refused: Sprint {sprint_id}'s milestone changed or has invalid status")
            return text
        before, after = ("in-progress", "done") if done else ("planned", "in-progress")
        return flip_status(text, found.heading, before, after)

    moved = edit_plan(mutate)
    if refusal:
        return refusal[0]
    return f"refused: Sprint {sprint_id}'s milestone did not move" if done and not moved else ""


def cmd_done(sprint_id):
    found = candidate(path.read_text(), sprint_id) if (path := plan_path()).exists() else None
    if not found:
        return fail(
            f"refused: Sprint {sprint_id}'s milestone has open cards or is not [in-progress]"
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
