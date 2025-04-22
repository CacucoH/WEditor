import uuid
import time
import json
from typing import Dict, Tuple, Optional, List, Any

ElementID = Tuple[float, str]

def stringify_keys(d: Dict) -> Dict[str, Any]:
    return {json.dumps(k): v for k, v in d.items()}

def tuplefy_keys(d: Dict[str, Any]) -> Dict[ElementID, Any]:
    res = {}
    for k_str, v in d.items():
        try:
            key_tuple = tuple(json.loads(k_str))
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
                 value: Optional[str],
                 predecessor_id: Optional[ElementID],
                 is_tombstone: bool = False):
        self.id = element_id
        self.value = value
        self.predecessor_id = predecessor_id
        self.is_tombstone = is_tombstone

    def __repr__(self):
        val = f"'{self.value}'" if self.value is not None else 'SENTINEL'
        tomb = ", TOMB" if self.is_tombstone else ""
        return f"Element(id={self.id}, val={val}, pred={self.predecessor_id}{tomb})"

    def to_dict(self) -> Dict[str, Any]:
        
        return {
            'id': self.id,
            'value': self.value,
            'predecessor_id': self.predecessor_id,
            'is_tombstone': self.is_tombstone
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Element':
        
        return Element(
            element_id=tuple(data['id']),
            value=data['value'],
            predecessor_id=tuple(data['predecessor_id']) if data['predecessor_id'] else None,
            is_tombstone=data.get('is_tombstone', False)
        )

Operation = Dict[str, Any]

class RGA:
    START_SENTINEL_ID: ElementID = (-1.0, "START")

    def __init__(self, site_id: str | None = None):
        self.site_id = site_id or str(uuid.uuid4())
        self.elements_by_id: Dict[ElementID, Element] = {}
        start_element = Element(self.START_SENTINEL_ID, None, None)
        self.elements_by_id[self.START_SENTINEL_ID] = start_element
        self._local_clock = 0.0

    def get_state(self) -> Dict[ElementID, Element]:
        
        return self.elements_by_id.copy()

    def set_state(self, state: Dict[ElementID, Element]):
        
        if self.START_SENTINEL_ID not in state:
            raise ValueError("Invalid state: START_SENTINEL missing.")
        self.elements_by_id = state.copy()

    def serialize_state(self) -> Dict[str, Any]:
        
        serialized_elements = {json.dumps(k): v.to_dict() for k, v in self.elements_by_id.items()}
        return {
            "site_id": self.site_id,
            "elements_by_id": serialized_elements
        }

    @classmethod
    def deserialize_state(cls, data: Dict[str, Any]) -> 'RGA':
        
        site_id = data.get("site_id", str(uuid.uuid4()))
        rga = cls(site_id=site_id)

        elements_data = data.get("elements_by_id", {})
        deserialized_elements = {}
        for k_str, elem_dict in elements_data.items():
            try:
                key_tuple = tuple(json.loads(k_str))
                if isinstance(key_tuple, tuple) and len(key_tuple) == 2 and isinstance(key_tuple[1], str):
                     deserialized_elements[key_tuple] = Element.from_dict(elem_dict)
                else:
                     print(f"Warning: Skipping invalid key during state deserialization: {k_str}")
            except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
                print(f"Warning: Error converting key/element {k_str} during state deserialization: {e}")

        if cls.START_SENTINEL_ID not in deserialized_elements:
             print(f"Warning: START_SENTINEL missing in deserialized state for site {site_id}. Adding default.")
             start_element = Element(cls.START_SENTINEL_ID, None, None)
             deserialized_elements[cls.START_SENTINEL_ID] = start_element

        rga.elements_by_id = deserialized_elements
        return rga

    def _generate_id(self) -> ElementID:
        ts = time.time()
        self._local_clock = max(self._local_clock + 0.000001, ts)
        return (self._local_clock, self.site_id)

    def _get_ordered_visible_elements(self) -> List[Element]:
        
        pred_to_succ_map: Dict[Optional[ElementID], List[Element]] = {}
        for elem in self.elements_by_id.values():
            pred_id = elem.predecessor_id
            if pred_id not in pred_to_succ_map:
                pred_to_succ_map[pred_id] = []
            pred_to_succ_map[pred_id].append(elem)

        for pred_id in pred_to_succ_map:
            pred_to_succ_map[pred_id].sort(key=lambda x: x.id)

        result_sequence = []
        stack = [self.START_SENTINEL_ID]
        visited_during_sort = set()
        processed_in_order = []

        while stack:
            current_id = stack.pop()

            if current_id in visited_during_sort:
                 print(f"Warning: Cycle detected or node revisited during sort: {current_id}")
                 continue
            visited_during_sort.add(current_id)

            current_elem = self.elements_by_id.get(current_id)
            if not current_elem:
                print(f"Error: Element {current_id} referenced but not found during traversal.")
                continue

            processed_in_order.append(current_elem)
            successors = sorted(pred_to_succ_map.get(current_id, []), key=lambda x: x.id, reverse=True)
            for succ in successors:
                 if succ.id not in visited_during_sort:
                    stack.append(succ.id)

        visible_sequence = [
            elem for elem in processed_in_order
            if not elem.is_tombstone and elem.id != self.START_SENTINEL_ID
        ]
        return visible_sequence

    def get_value(self) -> str:
        
        visible_elements = self._get_ordered_visible_elements()
        return "".join(elem.value for elem in visible_elements if elem.value is not None)

    def local_insert(self, index: int, value: str) -> Operation:
        
        if not isinstance(value, str) or len(value) != 1:
             raise ValueError("Insertion value must be a single character string.")
        if index < 0:
            raise IndexError("Index cannot be negative")

        visible_elements = self._get_ordered_visible_elements()

        if index == 0:
            predecessor_id = self.START_SENTINEL_ID
        elif index <= len(visible_elements):
            predecessor_id = visible_elements[index - 1].id
        else:
            if index == len(visible_elements):
                 predecessor_id = visible_elements[-1].id if visible_elements else self.START_SENTINEL_ID
            else:
                raise IndexError(f"Insertion index {index} out of bounds for length {len(visible_elements)}")

        new_id = self._generate_id()
        new_element = Element(new_id, value, predecessor_id)

        if new_id in self.elements_by_id:
            print(f"Warning: Element ID collision: {new_id}. Re-generating.")
            time.sleep(0.001)
            new_id = self._generate_id()
            if new_id in self.elements_by_id:
                 raise RuntimeError(f"Persistent Element ID collision for site {self.site_id}. Clock issue?")
            new_element = Element(new_id, value, predecessor_id)

        self.elements_by_id[new_id] = new_element
        return {"type": "insert", "element": new_element.to_dict()}

    def local_delete(self, index: int) -> Operation:
        
        if index < 0:
            raise IndexError("Index cannot be negative")

        visible_elements = self._get_ordered_visible_elements()

        if index >= len(visible_elements):
            return {"type": "noop", "reason": "delete index out of bounds"}

        element_to_delete = visible_elements[index]

        if element_to_delete.is_tombstone:
            return {"type": "noop", "reason": "element already deleted"}

        if element_to_delete.id == self.START_SENTINEL_ID:
             raise ValueError("Cannot delete the START sentinel.")

        element_to_delete.is_tombstone = True
        return {"type": "delete", "element_id": element_to_delete.id}

    def apply_remote_operation(self, operation: Operation):
        
        op_type = operation.get("type")

        if op_type == "insert":
            element_data = operation.get("element")
            if not element_data:
                print("Warning: Received insert operation with missing element data.")
                return

            try:
                new_element = Element.from_dict(element_data)
            except (KeyError, ValueError, TypeError) as e:
                 print(f"Warning: Failed to deserialize element from remote insert op: {e}, data: {element_data}")
                 return

            if new_element.id in self.elements_by_id:
                existing_element = self.elements_by_id[new_element.id]
                if existing_element.is_tombstone:
                    print(f"Remote insert: Re-activating existing tombstoned element {new_element.id}")
                    existing_element.is_tombstone = False
                else:
                    pass
                return

            if new_element.predecessor_id not in self.elements_by_id:
                print(f"Warning: Remote insert: Predecessor {new_element.predecessor_id} for element {new_element.id} not found. Op might be applied out of order or lost.")

            self.elements_by_id[new_element.id] = new_element

        elif op_type == "delete":
            element_id_tuple: Optional[ElementID] = None
            element_id_raw = operation.get("element_id")
            if isinstance(element_id_raw, (list, tuple)) and len(element_id_raw) == 2:
                 try:
                     ts = float(element_id_raw[0])
                     sid = str(element_id_raw[1])
                     element_id_tuple = (ts, sid)
                 except (ValueError, TypeError) as e:
                      print(f"Warning: Error converting element_id {element_id_raw} to tuple: {e}")
            elif element_id_raw is not None:
                 print(f"Warning: Received delete operation with malformed element_id: {element_id_raw}")

            if not element_id_tuple:
                print("Warning: Received delete operation with missing or invalid element_id.")
                return

            if element_id_tuple in self.elements_by_id:
                element_to_delete = self.elements_by_id[element_id_tuple]
                if not element_to_delete.is_tombstone:
                    element_to_delete.is_tombstone = True
            

        elif op_type == "noop":
            pass
        else:
            print(f"Warning: Received unknown operation type: {op_type}")

    def load_state(self, serialized_state: Dict[str, Any]):
        
        if "site_id" not in serialized_state or "elements_by_id" not in serialized_state:
            raise ValueError("Invalid serialized state format.")

        new_rga = RGA.deserialize_state(serialized_state)
        self.site_id = new_rga.site_id
        self.elements_by_id = new_rga.elements_by_id
        max_ts = 0.0
        for ts, _ in self.elements_by_id.keys():
             if isinstance(ts, (float, int)) and ts > max_ts:
                 max_ts = ts
        self._local_clock = max_ts

if __name__ == "__main__":
    site1 = RGA(site_id="site1")
    site2 = RGA(site_id="site2")

    op1 = site1.local_insert(0, 'H')
    print(f"Site1 inserts H: {op1}")
    print(f"Site1 value: {site1.get_value()}")

    site2.apply_remote_operation(op1)
    print(f"Site2 applies op1. Site2 value: {site2.get_value()}")

    op2 = site1.local_insert(1, 'i')
    print(f"Site1 inserts i: {op2}")
    print(f"Site1 value: {site1.get_value()}")

    op3 = site2.local_insert(0, 'X')
    print(f"Site2 inserts X: {op3}")
    print(f"Site2 value: {site2.get_value()}")

    print("Broadcasting ops...")
    site2.apply_remote_operation(op2)
    site1.apply_remote_operation(op3)

    print(f"Site1 value after sync: {site1.get_value()}")
    print(f"Site2 value after sync: {site2.get_value()}")

    assert site1.get_value() == site2.get_value(), "Convergence failed after inserts!"
    print("Convergence OK after inserts.")

    op4 = site1.local_delete(0)
    print(f"Site1 deletes at index 0: {op4}")
    print(f"Site1 value: {site1.get_value()}")

    op5 = site2.local_delete(1)
    print(f"Site2 deletes at index 1: {op5}")
    print(f"Site2 value: {site2.get_value()}")

    print("Broadcasting delete ops...")
    site2.apply_remote_operation(op4)
    site1.apply_remote_operation(op5)

    print(f"Site1 value after delete sync: {site1.get_value()}")
    print(f"Site2 value after delete sync: {site2.get_value()}")

    assert site1.get_value() == site2.get_value(), "Convergence failed after deletes!"
    print("Convergence OK after deletes.")

    print("Testing serialization...")
    serialized_state = site1.serialize_state()

    site3 = RGA.deserialize_state(serialized_state)
    print(f"Site3 deserialized value: {site3.get_value()}")
    assert site3.get_value() == site1.get_value(), "Deserialization failed!"
    print("Serialization/Deserialization OK.")