# SPDX-License-Identifier: Apache-2.0
"""Limits for tests that wait on a child process.

These limits only keep a stuck child from hanging the suite; they are not
speed checks. Process start-up and imports scale with host load: on a Mac at
load average 90-160, ``import omlx.engine_core`` alone took 31 s and 30 s
limits failed on the import before the behaviour under test began
(2026-10-03). A test that checks speed measures the time it cares about and
asserts on that, instead of folding start-up into a wait limit.
"""

SUBPROCESS_HANG_GUARD_SEC = 600
