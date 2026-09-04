from spawn_helpers import CARD, make_repo


def prompt_section(prompt, title):
    return prompt.split(f"## {title}\n\n", 1)[1].split("\n## ", 1)[0].strip()


class TestRoleBriefs:
    def run_planner(self, tmp_path, monkeypatch, mutate_repo=False):
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
            if mutate_repo:
                (tree / "planner-change.txt").write_text("planner changed the repository\n")
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

    def test_repository_writing_planner_is_refused(self, tmp_path, monkeypatch):
        repo, _prompt, result = self.run_planner(tmp_path, monkeypatch, mutate_repo=True)
        assert (repo / "planner-change.txt").read_text() == "planner changed the repository\n"
        assert result == (
            2,
            "the planner changed the repository; it owns only the external plan",
        )
