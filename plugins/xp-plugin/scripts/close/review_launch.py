"""Prepare the review artifacts before a reviewer launch."""

import preflight


def check_preflight(dry_run):
    import close

    raw = close.config_flat("preflight")
    if dry_run:
        _raw, _commands, error = preflight.prepare(raw)
        if raw and not error:
            print(preflight.preview(raw))
        return error
    return preflight.check(raw)
