"""Link an LLM disposition to preserved review history without rewriting it."""

import json
import sys
from pathlib import Path

from review_report import NO_ROUND, history_digest, normalize_report, read_report
from work import _single_line, append, neutralize, stamp


def source_report(root: Path, source: str) -> tuple[str, set[str], str, str]:
    path_text, sep, line_text = source.rpartition(":")
    numbered = bool(sep and line_text.isdigit())
    path = Path(path_text if numbered else source)
    path = (path if path.is_absolute() else root / path).resolve()
    canonical = f"{path}:{int(line_text)}" if numbered else str(path)
    try:
        text = path.read_text()
        data = json.loads(text.splitlines()[int(line_text) - 1] if numbered else text)
        if numbered and int(line_text) < 1:
            raise ValueError("history line must be positive")
        rounds = data["rounds"]
        if not isinstance(rounds, list) or not rounds:
            raise ValueError("source has no review rounds")
        findings = set()
        for raw in rounds:
            parsed, error = normalize_report(raw)
            if error:
                raise ValueError(error)
            findings.update(parsed["blocking"])
            findings.update(parsed.get("legacy_untriaged", []))
    except (OSError, UnicodeError, ValueError, IndexError, KeyError, TypeError) as error:
        return (
            canonical,
            set(),
            "",
            f"unusable source {canonical}: {error} — repair or choose its round",
        )
    return canonical, findings, history_digest(rounds), ""


def judge(root: Path, args) -> int:
    if not _single_line(args.source, "source"):
        return 2
    source, known, digest, error = source_report(root, args.source)
    report, report_error = read_report(args.report)
    error = error or report_error.replace(NO_ROUND, "No judgment was recorded.").replace(
        "the reviewer wrote no report", "no judgment report was written"
    )
    selected = [
        item if isinstance(item, str) else item["finding"]
        for key in ("fixed", "dropped", "debt")
        for item in report.get(key, [])
    ]
    if not error and (not selected or set(selected) - known or report["blocking"]):
        error = "judgment must dispose source findings only; unresolved blockers stay in review"
    if error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(
        append(
            root,
            f"## judgment {stamp()}\nSource: {neutralize(source)}\n"
            f"Digest: {digest}\nJudgment: {json.dumps(report, ensure_ascii=False)}\n\n",
        )
    )
    return 0
