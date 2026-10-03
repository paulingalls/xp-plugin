import pytest
from spawn_helpers import CARD, make_repo


def prompt_section(prompt, title):
    return prompt.split(f"## {title}\n\n", 1)[1].split("\n## ", 1)[0].strip()


class TestRoleBriefs:
    @pytest.mark.parametrize(
        "files,multifile", [("src/thing.py", False), ("src/a.py, src/b.py", True)]
    )
    def test_executor_brief_directs_story_tier_for_both_card_shapes(
        self, tmp_path, monkeypatch, files, multifile
    ):
        from spawn import PLUGIN_ROOT, build_prompt, teammate_sections

        repo, env, _git = make_repo(tmp_path, files=files)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        card = CARD.format(status="ready", files=files, executor="(default)")
        prompt = build_prompt(
            teammate_sections(card, "story-042", "", PLUGIN_ROOT, multifile=multifile)
        )
        work = prompt_section(prompt, "How you work")
        assert "tests.story" in work and ".xp/config.yml" in work
        assert "before handing back" in work
        assert ("reviewed plan" if multifile else "card is the authority") in work

    def run_planner(self, tmp_path, monkeypatch, mutate_repo=None):
        import review
        from story_stages import run_planner

        repo, env, _g = make_repo(tmp_path)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        captured = {}
        plan = tmp_path / "data" / "plans" / "story-042.plan.md"

        def write_plan(prompt, tree, **_kwargs):
            captured["prompt"] = prompt
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("# execution plan\n")
            if mutate_repo == "untracked":
                (tree / "planner-change.txt").write_text("planner changed the repository\n")
            elif mutate_repo:
                import subprocess

                (tree / ".xp/system.md").write_text("changed tracked source\n")
                if mutate_repo in {"index", "head"}:
                    subprocess.run(["git", "add", ".xp/system.md"], cwd=tree, check=True)
                if mutate_repo == "head":
                    subprocess.run(["git", "commit", "-qm", "planner motion"], cwd=tree, check=True)

            return None, ""

        monkeypatch.setattr(review, "run", write_plan)
        result = run_planner("story-042", CARD, repo, "")
        return repo, captured["prompt"], result

    def test_planner_receives_its_own_resolved_brief(self, tmp_path, monkeypatch):
        import review
        from spawn import PLUGIN_ROOT

        _repo, prompt, result = self.run_planner(tmp_path, monkeypatch)
        assert result == (0, ""), result
        planner = review.charter("planner")
        path = str(tmp_path / "data" / "plans" / "story-042.plan.md")
        executor = (
            (PLUGIN_ROOT / "EXECUTOR.md")
            .read_text()
            .replace("{PLAN_PATH}", path)
            .replace("{PLUGIN_ROOT}", str(PLUGIN_ROOT))
            .strip()
        )
        assert prompt_section(prompt, "How you work") != executor
        assert prompt_section(prompt, "How you work") == planner.replace("{PLAN_PATH}", path)

    @pytest.mark.parametrize("motion", ["untracked", "tracked", "index", "head"])
    def test_repository_writing_planner_is_refused(self, tmp_path, monkeypatch, motion):
        _repo, _prompt, result = self.run_planner(tmp_path, monkeypatch, mutate_repo=motion)
        assert result == (
            2,
            "the planner changed the repository; it owns only the external plan",
        )
