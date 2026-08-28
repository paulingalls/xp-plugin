"""The YAML comment rule, shared by every config reader.

Verify: pytest -q tests/test_config_comment.py

Split out of test_work.py at the 500-line cap (constraint 8): work.py owns
the rule, but the property is that its readers AGREE, so nothing here is
about the work.md record CLI the rest of that file drives.
"""


class TestConfigCommentRule:
    """The v0.6.1 wall fix taught hook-lib.sh that `p#ss` is one YAML scalar and
    left its two Python twins reading the SAME keys the old way, so the wall and
    the pipeline disagreed about `tests.story` — the tier close.py:311 runs at
    land. Truncated, it is a bare assignment: exits 0, runs no test.
    """

    TIER = 'DB=postgres://u:p#ss@h/db pytest -q -m "not slow"'

    def config(self, tmp_path, body):
        (tmp_path / ".xp").mkdir()
        (tmp_path / ".xp" / "config.yml").write_text(body)
        return tmp_path

    def test_both_python_readers_agree_with_the_wall_on_a_hash_inside_a_word(
        self, tmp_path, monkeypatch
    ):
        from close import config_flat
        from work import config_block_value

        monkeypatch.chdir(
            self.config(tmp_path, f"trunk: dev#1\ntests:\n  story: {self.TIER}   # ours\n")
        )
        assert config_block_value("tests", "story") == self.TIER
        assert config_flat("trunk") == "dev#1"

    def test_a_whitespace_preceded_comment_still_strips_everywhere(self, tmp_path, monkeypatch):
        from close import config_flat
        from work import config_block_value

        body = "release: sprint   # a trailing note\ntests:\n  full: pytest  # x\n"
        monkeypatch.chdir(self.config(tmp_path, body))
        assert config_block_value("tests", "full") == "pytest"
        assert config_flat("release") == "sprint"

    def test_lifecycle_prefix_keeps_fixed_quoted_argv_before_its_comment(
        self, tmp_path, monkeypatch
    ):
        from close import config_flat

        body = 'lifecycle_command: python3 sync.py "fixed value"  # project hook\n'
        monkeypatch.chdir(self.config(tmp_path, body))
        assert config_flat("lifecycle_command") == 'python3 sync.py "fixed value"'

    def test_a_fully_commented_line_never_opens_or_closes_a_block(self, tmp_path, monkeypatch):
        """`# review:` must not read as the review block, and a commented-out tier
        inside `tests:` must not end it before the live tiers below."""
        from work import config_block_value

        monkeypatch.chdir(
            self.config(
                tmp_path,
                "# review:\n#   verify_batches: 9\ntests:\n#  fast: retired\n  full: pytest\n",
            )
        )
        assert config_block_value("review", "verify_batches") == ""
        assert config_block_value("tests", "full") == "pytest"

    def test_a_missing_sentinel_distinguishes_absent_from_empty(self, tmp_path, monkeypatch):
        from work import config_block_value

        monkeypatch.chdir(self.config(tmp_path, "roles:\n  reviewer:\n"))
        assert config_block_value("roles", "plan-reviewer", missing="ABSENT") == "ABSENT"
        assert config_block_value("roles", "reviewer", missing="ABSENT") == ""
