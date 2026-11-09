"""Tiny undo stack for map theme operations.

Native QGIS keeps no undo history for map themes, so the plugin records an
inverse action for every change it makes.  Only the most recent operation
can be undone, so inverse actions never run against a state they did not
expect.
"""

import itertools


class UndoStack:
    def __init__(self, limit=20):
        self._limit = limit
        self._ops = []  # list of (id, text, undo_fn)
        self._ids = itertools.count(1)

    def push(self, text, undo_fn):
        op_id = next(self._ids)
        self._ops.append((op_id, text, undo_fn))
        del self._ops[:-self._limit]
        return op_id

    def clear(self):
        self._ops.clear()

    def can_undo(self):
        return bool(self._ops)

    def top_text(self):
        return self._ops[-1][1] if self._ops else None

    def is_top(self, op_id):
        return bool(self._ops) and self._ops[-1][0] == op_id

    def undo(self, op_id=None):
        """Undo the newest operation (optionally only if it is ``op_id``).

        Returns its description, or ``None`` if nothing was undone.
        """
        if not self._ops or (op_id is not None and not self.is_top(op_id)):
            return None
        _, text, fn = self._ops.pop()
        fn()
        return text
