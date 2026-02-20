"""Application constants."""

from typing import Literal

# The maximum depth to which reference duplicates are propagated. A depth
# of 2, means only direct duplicates are allowed. Any increases to this
# constant will cause significant increases in performance cost and
# data model complexity.
MAX_REFERENCE_DUPLICATE_DEPTH: Literal[2] = 2
