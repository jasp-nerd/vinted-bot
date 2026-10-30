"""The polling side: what to check, what counts as new, and whether it is still working.

Modules are imported by name (`from vinted_bot.engine import health`) rather than
re-exported here: the repository uses `engine.validation`, and re-exporting the poller
from this package would make that import circular.
"""
