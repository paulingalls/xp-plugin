"""Existing consumer Verify fault fixtures."""

BROKEN_PATCH = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+broken =
"""


def commit(g, repo, path, content):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    g("add", path)
    assert g("commit", "-qm", "lead repair").returncode == 0
