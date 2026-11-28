import hashlib
import json
import socket

import xp
from test_land import git
from test_retro_filing import wiki_read, wiki_seed

pytest_plugins = ["test_retro_filing"]


def answer(monkeypatch, sightings):
    monkeypatch.setenv("RETRO_RESULT", json.dumps({"sightings": sightings, "proposals": []}))


def test_same_clone_and_sprint_on_two_machines(publishing, monkeypatch, tmp_path):
    root, data, _, _, home = publishing
    keys = [f"repo@{hashlib.sha256(host.encode()).hexdigest()[:6]}:1" for host in ("A", "B")]
    monkeypatch.setattr(socket, "gethostname", lambda: "A")
    answer(
        monkeypatch, [{"lesson": "new:1", "text": "Common"}, {"lesson": "new:2", "text": "Only A"}]
    )
    assert xp.main(["retro", "1"]) == 0
    assert "Common (seen:" in wiki_read(publishing)
    second = tmp_path / "machine-b/repo"
    git(tmp_path, "clone", "-q", str(root.parent / "origin.git"), str(second))
    (second / ".xp/config.yml").open("a").write("\ngithub_issues: on\n")
    second_data = tmp_path / "second-data"
    (second_data / "sprints/1").mkdir(parents=True)
    (second_data / "sprints/1/release.json").write_text("{}")
    (second_data / "plan.md").write_text("## Sprint 1 — retro\n")
    second_home = tmp_path / "second-home"
    second_home.mkdir()
    monkeypatch.chdir(second)
    monkeypatch.setenv("HOME", str(second_home))
    monkeypatch.setenv("XP_DATA", str(second_data))
    monkeypatch.setattr(socket, "gethostname", lambda: "B")
    answer(monkeypatch, [{"lesson": "L1"}, {"lesson": "new:1", "text": "Only B"}])
    assert xp.main(["retro", "1"]) == 0
    text = wiki_read(publishing)
    assert text.count("Common (seen:") == 1
    assert f"Common (seen: {keys[0]}, {keys[1]})" in text
    assert f"Only A (seen: {keys[0]})" in text
    assert f"Only B (seen: {keys[1]})" in text
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XP_DATA", str(data))
    monkeypatch.setattr(socket, "gethostname", lambda: "A")
    answer(monkeypatch, [])
    assert xp.main(["retro", "1"]) == 0
    text = wiki_read(publishing)
    assert f"Common (seen: {keys[1]})" in text
    assert f"Only B (seen: {keys[1]})" in text
    assert "Only A" not in text and keys[0] not in text


def test_legacy_sighting_survives_rerun(publishing, monkeypatch):
    legacy = f"{publishing[0].name}:1"
    key = f"{publishing[0].name}@{hashlib.sha256(socket.gethostname().encode()).hexdigest()[:6]}:1"
    seed = f"- L1 [sighting] Original lesson (seen: {legacy}) -> not proposed\n"
    wiki_seed(publishing, seed)
    answer(monkeypatch, [{"lesson": "L1"}])
    assert xp.main(["retro", "1"]) == 0
    assert wiki_read(publishing) == seed.replace(f"{legacy})", f"{legacy}, {key})")
    answer(monkeypatch, [])
    assert xp.main(["retro", "1"]) == 0
    assert wiki_read(publishing) == seed
