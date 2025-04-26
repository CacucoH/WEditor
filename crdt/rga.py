import uuid
import time
import json
from typing import Dict, Tuple, Optional, List, Any

# Using Tuple for ID for hashability and comparison
# (timestamp, site_id) - Assuming higher timestamp means later, break ties with site_id
ElementID = Tuple[float, str]

# Helper to convert tuple keys to strings for JSON
def stringify_keys(d: Dict) -> Dict[str, Any]:
    return {json.dumps(k): v for k, v in d.items()}

# Helper to convert string keys back to tuples
def tuplefy_keys(d: Dict[str, Any]) -> Dict[ElementID, Any]:
    res = {}
    for k_str, v in d.items():
        try:
            key_tuple = tuple(json.loads(k_str))
            # Basic validation of tuple structure
            if isinstance(key_tuple, tuple) and len(key_tuple) == 2 and isinstance(key_tuple[1], str):
                 res[key_tuple] = v
            else:
                 print(f"Warning: Skipping invalid key during tuplefy: {k_str}")
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Error converting key {k_str} to tuple: {e}")
    return res

class Element:
    def __init__(self,
                 element_id: ElementID,
                 value: Optional[str], # None for sentinel nodes
                 predecessor_id: Optional[ElementID],
                 is_tombstone: bool = False):
        self.id = element_id
        self.value = value
        self.predecessor_id = predecessor_id # ID of the element this logically follows
        self.is_tombstone = is_tombstone

    def __repr__(self):
        val = f"'{self.value}'" if self.value is not None else 'SENTINEL'
        tomb = ", TOMB" if self.is_tombstone else ""
        return f"Element(id={self.id}, val={val}, pred={self.predecessor_id}{tomb})"

    def to_dict(self) -> Dict[str, Any]:
        """Serializes Element to a dictionary for operations."""
        return {
            'id': self.id,
            'value': self.value,
            'predecessor_id': self.predecessor_id,
            'is_tombstone': self.is_tombstone
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Element':
        """Deserializes Element from a dictionary."""
        return Element(
            element_id=tuple(data['id']), # Ensure tuple
            value=data['value'],
            predecessor_id=tuple(data['predecessor_id']) if data['predecessor_id'] else None,
            is_tombstone=data.get('is_tombstone', False)
        )


# Define Operation Types (can be expanded)
Operation = Dict[str, Any]

class RGA:
    START_SENTINEL_ID: ElementID = (-1.0, "START")

    def __init__(self, site_id: str | None = None):
        self.site_id = site_id or str(uuid.uuid4())
        # Store all elements by ID, including sentinels and tombstones
        self.elements_by_id: Dict[ElementID, Element] = {}
        # Add start sentinel node
        start_element = Element(self.START_SENTINEL_ID, None, None)
        self.elements_by_id[self.START_SENTINEL_ID] = start_element

        # Track local timestamp/counter for generating IDs
        self._local_clock = 0.0 # Simplistic, use time.time() or better clock later

    def get_state(self) -> Dict[ElementID, Element]:
        """ Returns the internal state (all elements). """
        # Return a copy to prevent external modification
        return self.elements_by_id.copy()

    def set_state(self, state: Dict[ElementID, Element]):
        """ Overwrites the internal state. Use with caution. """
        # Basic validation: ensure START_SENTINEL is present
        if self.START_SENTINEL_ID not in state:
            raise ValueError("Invalid state: START_SENTINEL missing.")
        self.elements_by_id = state.copy() # Use a copy
        # Resetting clock might be needed depending on usage, but maybe not for snapshots?
        # self._local_clock = max(ts for ts, _ in state.keys() if isinstance(ts, (float, int))) # Estimate max timestamp

    def serialize_state(self) -> Dict[str, Any]:
        """ Serializes the RGA state to a JSON-compatible dictionary. """
        serialized_elements = {json.dumps(k): v.to_dict() for k, v in self.elements_by_id.items()}
        return {
            "site_id": self.site_id,
            # "_local_clock": self._local_clock, # Maybe persist clock state?
            "elements_by_id": serialized_elements
            # Add other necessary state fields if any
        }

    @classmethod
    def deserialize_state(cls, data: Dict[str, Any]) -> 'RGA':
        """ Creates an RGA instance from serialized state. """
        site_id = data.get("site_id", str(uuid.uuid4()))
        rga = cls(site_id=site_id)

        elements_data = data.get("elements_by_id", {})
        deserialized_elements = {}
        for k_str, elem_dict in elements_data.items():
            try:
                key_tuple = tuple(json.loads(k_str))
                 # Basic validation of tuple structure
                if isinstance(key_tuple, tuple) and len(key_tuple) == 2 and isinstance(key_tuple[1], str):
                     deserialized_elements[key_tuple] = Element.from_dict(elem_dict)
                else:
                     print(f"Warning: Skipping invalid key during state deserialization: {k_str}")
            except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
                print(f"Warning: Error converting key/element {k_str} during state deserialization: {e}")

        # Ensure START_SENTINEL is present after deserialization
        if cls.START_SENTINEL_ID not in deserialized_elements:
             print(f"Warning: START_SENTINEL missing in deserialized state for site {site_id}. Adding default.")
             start_element = Element(cls.START_SENTINEL_ID, None, None)
             deserialized_elements[cls.START_SENTINEL_ID] = start_element

        rga.elements_by_id = deserialized_elements
        # rga._local_clock = data.get("_local_clock", 0.0)
        return rga

    def _generate_id(self) -> ElementID:
        # Replace with a proper logical clock (Lamport or Vector) later
        # For now, use time + site_id for uniqueness and tie-breaking
        ts = time.time()
        # Ensure monotonicity for local operations if time goes backwards slightly
        self._local_clock = max(self._local_clock + 0.000001, ts)
        return (self._local_clock, self.site_id)

    def _get_ordered_visible_elements(self) -> List[Element]:
        """ Traverses the logical sequence based on predecessors and returns visible elements. """
        # Build predecessor -> list[element] map for efficient lookup during traversal
        pred_to_succ_map: Dict[Optional[ElementID], List[Element]] = {}
        for elem in self.elements_by_id.values():
            pred_id = elem.predecessor_id
            if pred_id not in pred_to_succ_map:
                pred_to_succ_map[pred_id] = []
            pred_to_succ_map[pred_id].append(elem)

        # Sort successors for deterministic order (tie-breaking by ID: timestamp, site_id)
        for pred_id in pred_to_succ_map:
            pred_to_succ_map[pred_id].sort(key=lambda x: x.id)

        # Depth-first traversal from START_SENTINEL to reconstruct sequence
        result_sequence = []
        stack = [self.START_SENTINEL_ID]
        visited_during_sort = set() # Prevent infinite loops in case of bad data (shouldn't happen in RGA)

        processed_in_order = [] # Keep track of the full integrated order

        while stack:
            current_id = stack.pop()

            if current_id in visited_during_sort:
                 print(f"Warning: Cycle detected or node revisited during sort: {current_id}")
                 continue # Avoid cycles
            visited_during_sort.add(current_id)

            current_elem = self.elements_by_id.get(current_id)
            if not current_elem:
                print(f"Error: Element {current_id} referenced but not found during traversal.")
                continue

            # Add the element itself to the processed list (maintaining full order)
            processed_in_order.append(current_elem)

            # Add successors to the stack in reverse sorted order
            # So the element with the "lowest" ID (earliest timestamp, tie-broken by site ID)
            # gets processed next when popped.
            successors = sorted(pred_to_succ_map.get(current_id, []), key=lambda x: x.id, reverse=True)
            for succ in successors:
                 if succ.id not in visited_during_sort: # Add optimization check
                    stack.append(succ.id)

        # Filter the fully ordered sequence to get visible elements
        visible_sequence = [
            elem for elem in processed_in_order
            if not elem.is_tombstone and elem.id != self.START_SENTINEL_ID
        ]
        return visible_sequence


    def get_value(self) -> str:
        """ Returns the current visible string value. """
        visible_elements = self._get_ordered_visible_elements()
        return "".join(elem.value for elem in visible_elements if elem.value is not None)

    def local_insert(self, index: int, value: str) -> Operation:
        """ Inserts `value` at `index` in the visible sequence and returns the operation. """
        if not isinstance(value, str) or len(value) != 1:
             raise ValueError("Insertion value must be a single character string.")
        if index < 0:
            raise IndexError("Index cannot be negative")

        visible_elements = self._get_ordered_visible_elements()

        # Find predecessor ID
        if index == 0:
            predecessor_id = self.START_SENTINEL_ID
        elif index <= len(visible_elements):
            # The predecessor is the element currently at index - 1
            predecessor_id = visible_elements[index - 1].id
        else:
            # Allow inserting at the end
            if index == len(visible_elements):
                 predecessor_id = visible_elements[-1].id if visible_elements else self.START_SENTINEL_ID
            else:
                raise IndexError(f"Insertion index {index} out of bounds for length {len(visible_elements)}")


        # Generate new element
        new_id = self._generate_id()
        new_element = Element(new_id, value, predecessor_id)

        # Integrate locally
        if new_id in self.elements_by_id:
            # ID collision - extremely unlikely with good IDs. Could indicate clock issue or reuse.
            print(f"Warning: Element ID collision: {new_id}. Re-generating.")
            # Simple recovery: try generating again (might infinite loop if clock is stuck)
            # A robust solution needs better clock management or error handling.
            time.sleep(0.001) # Small delay
            new_id = self._generate_id()
            if new_id in self.elements_by_id:
                 raise RuntimeError(f"Persistent Element ID collision for site {self.site_id}. Clock issue?")
            new_element = Element(new_id, value, predecessor_id)

        self.elements_by_id[new_id] = new_element

        # Return operation for broadcast
        return {"type": "insert", "element": new_element.to_dict()}

    def local_delete(self, index: int) -> Operation:
        """ Deletes the element at `index` in the visible sequence and returns the operation. """
        if index < 0:
            raise IndexError("Index cannot be negative")

        visible_elements = self._get_ordered_visible_elements()

        if not visible_elements:
            raise IndexError("Cannot delete from empty sequence")
        if index >= len(visible_elements):
            raise IndexError(f"Deletion index {index} out of bounds for length {len(visible_elements)}")

        element_to_delete = visible_elements[index]
        element_id_to_delete = element_to_delete.id

        # Integrate locally (mark as tombstone)
        if element_id_to_delete in self.elements_by_id:
            # Ensure we don't delete the sentinel
            if element_id_to_delete == self.START_SENTINEL_ID:
                 print("Error: Attempted to delete START_SENTINEL.")
                 return {"type": "noop", "reason": "Cannot delete sentinel"}

            self.elements_by_id[element_id_to_delete].is_tombstone = True
            # Optimization: Could potentially prune tombstones under certain conditions,
            # but requires careful coordination and garbage collection logic. Omitted for simplicity.
        else:
            # Should not happen if visible_elements is derived correctly from elements_by_id
            print(f"Error: Element to delete {element_id_to_delete} not found in main store during local_delete.")
            return {"type": "noop", "reason": "Element not found"}


        # Return operation for broadcast
        return {"type": "delete", "element_id": element_id_to_delete}


    def apply_remote_operation(self, operation: Operation):
        """ Applies a remote operation (insert or delete). Assumes operations are dictionaries. """
        op_type = operation.get("type")

        if op_type == "insert":
            elem_data = operation.get("element")
            if not elem_data or not isinstance(elem_data, dict):
                print(f"Warning: Malformed insert operation received: {operation}")
                return

            try:
                element_id = tuple(elem_data['id']) # Ensure tuple for dict key
                predecessor_id = tuple(elem_data['predecessor_id']) if elem_data['predecessor_id'] else None
            except (KeyError, TypeError, ValueError) as e:
                 print(f"Warning: Invalid ID format in insert operation {elem_data}: {e}")
                 return


            # Idempotency: Check if element already exists
            if element_id in self.elements_by_id:
                 # RGA handles duplicate inserts naturally (state-based).
                 # If it exists, make sure tombstone status matches (delete wins).
                 existing_element = self.elements_by_id[element_id]
                 if not existing_element.is_tombstone and elem_data.get('is_tombstone', False):
                     # Remote operation marks it as tombstone, update local state
                     existing_element.is_tombstone = True
                 elif existing_element.is_tombstone and not elem_data.get('is_tombstone', False):
                     # Local state is tombstone, remote state is not. Delete wins. Keep tombstone.
                     pass
                 # If value differs? CRDT assumes value is immutable for a given ID. Ignore.
                 return # Already integrated or handled


            # Check if predecessor exists (causal dependency)
            # In a real system, we might need to buffer operations if the predecessor is missing.
            if predecessor_id is not None and predecessor_id not in self.elements_by_id:
                print(f"Warning: Predecessor {predecessor_id} not found for remote insert {element_id}. Buffering needed for robust system.")
                # TODO: Implement buffering if needed. For now, we might lose the op or apply incorrectly.
                # Let's try adding it anyway, it might get ordered correctly later if predecessor arrives.
                # OR simply ignore it for now. Ignoring is safer if buffering isn't implemented.
                return # Ignore op if predecessor is missing


            try:
                new_element = Element.from_dict(elem_data)
                # Ensure element_id is correctly formed tuple after deserialization
                if not isinstance(new_element.id, tuple) or len(new_element.id) != 2:
                     raise ValueError("Deserialized element ID is not a valid tuple.")
                if new_element.predecessor_id is not None and (not isinstance(new_element.predecessor_id, tuple) or len(new_element.predecessor_id) != 2):
                     raise ValueError("Deserialized predecessor ID is not a valid tuple.")

            except (KeyError, TypeError, ValueError) as e:
                print(f"Warning: Failed to deserialize element from insert operation {elem_data}: {e}")
                return

            self.elements_by_id[new_element.id] = new_element


        elif op_type == "delete":
            element_id_to_delete_raw = operation.get("element_id")
            if not element_id_to_delete_raw:
                print(f"Warning: Malformed delete operation received: {operation}")
                return

            try:
                 element_id_to_delete = tuple(element_id_to_delete_raw)
                 if len(element_id_to_delete) != 2: raise ValueError("Incorrect tuple length")
            except (TypeError, ValueError) as e:
                 print(f"Warning: Invalid ID format in delete operation {element_id_to_delete_raw}: {e}")
                 return

            # Ensure we don't delete the sentinel
            if element_id_to_delete == self.START_SENTINEL_ID:
                 print("Warning: Received remote request to delete START_SENTINEL. Ignoring.")
                 return


            if element_id_to_delete in self.elements_by_id:
                # Mark as tombstone - this is idempotent
                self.elements_by_id[element_id_to_delete].is_tombstone = True
            else:
                # Element not found. It might arrive later. To ensure delete wins (LWW based on tombstone flag),
                # we should create a tombstone placeholder for it. This requires knowing its predecessor,
                # which standard delete ops don't carry.
                # Simple approach: Ignore the delete if element not found. Causal delivery or buffering would handle this better.
                print(f"Info: Remote delete for element {element_id_to_delete} not found locally. Ignoring.")
                pass # If the insert arrives later, it will be added, then potentially deleted by a later delete op.

        else:
            print(f"Warning: Unknown operation type received: {op_type}")

# Example Usage (for testing)
if __name__ == '__main__':
    rga1 = RGA(site_id="site1")
    rga2 = RGA(site_id="site2")

    # Simulate local insertions
    op1_1 = rga1.local_insert(0, 'A')
    print(f"RGA1: {rga1.get_value()}")
    op1_2 = rga1.local_insert(1, 'B')
    print(f"RGA1: {rga1.get_value()}")
    op1_3 = rga1.local_insert(1, 'X') # Insert X between A and B
    print(f"RGA1: {rga1.get_value()}") # Should be AXB

    # Simulate peer receiving operations out of order
    print("Applying ops to RGA2 out of order:")
    rga2.apply_remote_operation(op1_2) # Apply insert B first
    print(f"RGA2: {rga2.get_value()}")
    rga2.apply_remote_operation(op1_1) # Apply insert A
    print(f"RGA2: {rga2.get_value()}") # Should be AB (depends on traversal logic)
    rga2.apply_remote_operation(op1_3) # Apply insert X
    print(f"RGA2: {rga2.get_value()}") # Should be AXB

    # Simulate concurrent insert at the same position
    print("Simulating concurrent insert at index 1:")
    rga_c1 = RGA(site_id="siteC1")
    rga_c2 = RGA(site_id="siteC2")

    op_c_base = rga_c1.local_insert(0, 'A')
    rga_c2.apply_remote_operation(op_c_base)
    print(f"C1: {rga_c1.get_value()}, C2: {rga_c2.get_value()}") # Both "A"

    # Site 1 inserts 'Y' at index 1, Site 2 inserts 'Z' at index 1
    op_c1_y = rga_c1.local_insert(1, 'Y')
    op_c2_z = rga_c2.local_insert(1, 'Z')

    # Apply operations cross-wise
    rga_c1.apply_remote_operation(op_c2_z)
    rga_c2.apply_remote_operation(op_c1_y)

    print(f"C1 final: {rga_c1.get_value()}")
    print(f"C2 final: {rga_c2.get_value()}") # Should both converge to the same string (e.g., "AYZ" or "AZY" depending on ID comparison)

    # Simulate deletion
    print("Simulating deletion:")
    op_c1_del = rga_c1.local_delete(1) # Delete the 'Y' or 'Z' depending on order
    print(f"C1 after delete: {rga_c1.get_value()}")

    rga_c2.apply_remote_operation(op_c1_del)
    print(f"C2 after delete op: {rga_c2.get_value()}") # Should match C1

    # Test edge case: delete last element
    rga_edge = RGA("siteE")
    rga_edge.local_insert(0,'P')
    rga_edge.local_insert(1,'Q')
    print(f"Edge case: {rga_edge.get_value()}")
    op_e_del = rga_edge.local_delete(1) # Delete Q
    print(f"Edge case after delete: {rga_edge.get_value()}")
    rga_edge.apply_remote_operation(op_e_del) # Apply own op (idempotency)
    print(f"Edge case after re-apply delete: {rga_edge.get_value()}")

    # Test delete first element
    op_e_del0 = rga_edge.local_delete(0) # Delete P
    print(f"Edge case after delete 0: {rga_edge.get_value()}") # Should be empty
    print("RGA Elements Store (Site E):")
    # for elem_id, elem in rga_edge.elements_by_id.items():
    #     print(f"  {elem}") # See tombstones


    # Test insert at end
    op_e_ins_end = rga_edge.local_insert(0, 'Z') # Insert into empty list
    print(f"Edge case insert end: {rga_edge.get_value()}")
    rga_edge.apply_remote_operation(op_e_ins_end)
    print(f"Edge case insert end re-apply: {rga_edge.get_value()}") 