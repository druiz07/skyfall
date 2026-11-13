import json

from skyfall.holdout import LEARN_RULE, VALIDATION_NORAD, is_exam, is_learn
from skyfall.tip_errors import TABLE_PATH


def test_learn_and_exam_never_share_an_object():
    for norad_id in range(40000, 40100):
        assert not (is_learn(norad_id) and is_exam(norad_id))
        assert is_learn(norad_id) or is_exam(norad_id)
    assert not is_learn(VALIDATION_NORAD) and not is_exam(VALIDATION_NORAD)


def test_shipped_timing_table_was_built_from_the_learn_half():
    source = json.loads(TABLE_PATH.read_text(encoding="utf-8"))["source"]
    assert source["learn_split"] == LEARN_RULE
    assert VALIDATION_NORAD in source["excluded_norad"]
