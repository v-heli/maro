# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from enum import Enum
from typing import Callable, Dict, List, Tuple, Union

import numpy as np

from maro.utils import clone
from maro.utils.exception.rl_toolkit_exception import StoreMisalignment

from .abs_store import AbsStore


class SimpleStore(AbsStore):
    """
    An implementation of ``AbsStore`` for experience storage in RL.

    This implementation uses a dictionary of lists as the internal data structure. The objects for each key
    are stored in a list. To be useful for experience storage in RL, uniformity checks are performed during
    put operations to ensure that the list lengths stay the same for all keys at all times. Both unlimited
    and limited storage are supported.

    Args:
        keys (list): Keys to identify the stored lists of objects.
        capacity (int): If negative, the store is of unlimited capacity. Defaults to -1.
        overwrite_type (str): If storage capacity is bounded, this specifies how existing entries
            are overwritten when the capacity is exceeded. Two types of overwrite behavior are supported:
            - "rolling", where overwrite occurs sequentially with wrap-around.
            - "random", where overwrite occurs randomly among filled positions.
            Alternatively, the user may also specify overwrite positions (see ``put``).
    """
    def __init__(self, keys: list, capacity: int = -1, overwrite_type: str = None):
        super().__init__()
        if overwrite_type not in {"rolling", "random"}:
            raise ValueError(f"overwrite_type must be 'rolling' or 'random', got {overwrite_type}")
        self.keys = keys
        self._capacity = capacity
        self._overwrite_type = overwrite_type
        self.data = {key: [] if self._capacity == -1 else [None] * self._capacity for key in self.keys}
        self._size = 0

    def __len__(self):
        return self._size

    def __getitem__(self, index: int):
        return {k: lst[index] for k, lst in self.data.items()}

    @property
    def capacity(self):
        """Store capacity.

        If negative, the store grows without bound. Otherwise, the number of items in the store will not exceed
        this capacity.
        """
        return self._capacity

    @property
    def overwrite_type(self):
        """An string indicating the overwrite behavior when the store capacity is exceeded."""
        return self._overwrite_type

    def get(self, indexes: [int] = None) -> dict:
        if indexes is None:
            return self.data
        return {k: [self.data[k][i] for i in indexes] for k in self.data}

    def put(self, contents: Dict[str, List], overwrite_indexes: list = None) -> List[int]:
        """Put new contents in the store.

        Args:
            contents (dict): Dictionary of items to add to the store. If the store is not empty, this must have the
                same keys as the store itself. Otherwise an ``StoreMisalignment`` will be raised.
            overwrite_indexes (list, optional): Indexes where the contents are to be overwritten. This is only
                used when the store has a fixed capacity and putting ``contents`` in the store would exceed this
                capacity. If this is None and overwriting is necessary, rolling or random overwriting will be done
                according to the ``overwrite`` property. Defaults to None.
        Returns:
            The indexes where the newly added entries reside in the store.
        """
        if len(self.data) > 0:
            expected_keys, actual_keys = set(self.data.keys()), set(contents.keys())
            if expected_keys != actual_keys:
                raise StoreMisalignment(f"expected keys {expected_keys}, got {actual_keys}")
        self.validate(contents)
        added = contents[next(iter(contents))]
        added_size = len(added) if isinstance(added, list) else 1
        if self._capacity == -1:
            for key, val in contents.items():
                self.data[key].extend(val)
            self._size += added_size
            return list(range(self._size - added_size, self._size))
        else:
            write_indexes = self._get_update_indexes(added_size, overwrite_indexes=overwrite_indexes)
            self.update(write_indexes, contents)
            self._size = min(self._capacity, self._size + added_size)
            return write_indexes

    def update(self, indexes: list, contents: Dict[str, List]):
        """
        Update contents at given positions.

        Args:
            indexes (list): Positions where updates are to be made.
            contents (dict): Contents to write to the internal store at given positions. It is subject to
                uniformity checks to ensure that all values have the same length.

        Returns:
            The indexes where store contents are updated.
        """
        self.validate(contents)
        for key, val in contents.items():
            for index, value in zip(indexes, val):
                self.data[key][index] = value

        return indexes

    def clear(self):
        """Empty the store."""
        self.data = {key: [] if self._capacity == -1 else [None] * self._capacity for key in self.keys}
        self._size = 0

    def dumps(self):
        """Return a deep copy of store contents."""
        return clone(dict(self.data))

    def get_by_key(self, key):
        """Get the contents of the store corresponding to ``key``."""
        return self.data[key]

    def _get_update_indexes(self, added_size: int, overwrite_indexes=None):
        if added_size > self._capacity:
            raise ValueError("size of added items should not exceed the store capacity.")

        num_overwrites = self._size + added_size - self._capacity
        if num_overwrites < 0:
            return list(range(self._size, self._size + added_size))

        if overwrite_indexes is not None:
            write_indexes = list(range(self._size, self._capacity)) + list(overwrite_indexes)
        else:
            # follow the overwrite rule set at init
            if self._overwrite_type == "rolling":
                # using the negative index convention for convenience
                start_index = self._size - self._capacity
                write_indexes = list(range(start_index, start_index + added_size))
            else:
                random_indexes = np.random.choice(self._size, size=num_overwrites, replace=False)
                write_indexes = list(range(self._size, self._capacity)) + list(random_indexes)

        return write_indexes

    @staticmethod
    def validate(contents: Dict[str, List]):
        # Ensure that all values are lists of the same length.
        if any(not isinstance(val, list) for val in contents.values()):
            raise TypeError("All values must be of type 'list'")

        reference_val = contents[list(contents.keys())[0]]
        if any(len(val) != len(reference_val) for val in contents.values()):
            raise StoreMisalignment("values of contents should consist of lists of the same length")
