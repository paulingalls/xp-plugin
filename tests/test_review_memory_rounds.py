import bookkeep
import pytest


@pytest.mark.parametrize("renderer", [bookkeep.render_prior_rounds, bookkeep.render_sprint_prior])
def test_later_review_prompts_receive_every_earlier_round(renderer):
    rounds = [
        {"fixed": [f"round-{n}-fix"], "blocking": [], "noted": [f"round-{n}-note"]}
        for n in range(1, 4)
    ]
    rendered = renderer(rounds)
    for n in range(1, 4):
        assert rendered.count(f"Review round {n}:") == 1
        assert rendered.count(f"round-{n}-fix") == 1
        assert rendered.count(f"round-{n}-note") == 1
