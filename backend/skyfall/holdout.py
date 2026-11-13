"""Which re-entries SKYFALL may learn from and which are kept for the exam.

One fixed rule for every table built from past re-entries: objects with an
even NORAD id are the learn half, odd ids are the held-out exam half, and the
validation case (STARLINK-1797) belongs to neither. Keeping the rule here
stops the tables and the exam from drifting apart.
"""

# One year of TIP notices, cached in data_local/ (never in the repo).
BULK_PATH = (
    "class/tip/DECAY_EPOCH/2025-10-01--2026-10-03"
    "/orderby/NORAD_CAT_ID%20asc,MSG_EPOCH%20asc"
)
# Validation case (STARLINK-1797, re-entry 4 Oct 2026): never learned, never examined.
VALIDATION_NORAD = 46698
LEARN_RULE = "NORAD_CAT_ID even (odd ids held out for the exam)"


def is_learn(norad_id: int) -> bool:
    return norad_id % 2 == 0 and norad_id != VALIDATION_NORAD


def is_exam(norad_id: int) -> bool:
    return norad_id % 2 == 1 and norad_id != VALIDATION_NORAD
