import sys
import os
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import atexit
import difflib # For comparing text
import time
from typing import Dict, Any, List, Tuple

# Adjust path to import from parent directory common and crdt
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from common.broker import RedisBroker
from crdt.rga import RGA, Operation

# Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
DOCUMENT_CHANNEL = "doc1" # Simple single document channel

app = Flask(__name__, template_folder='../client/templates', static_folder='../client/static')
app.config['SECRET_KEY'] = 'secret!changethis' # Change for production
# Use async_mode='threading' for compatibility with Flask dev server
# Consider 'eventlet' or 'gevent' for production
socketio = SocketIO(app, async_mode='threading')

# --- Global State (Single Document for MVP) ---
doc_crdt = RGA(site_id="server") # Server acts as one site
# Broker now reads host/port from env vars by default
broker = RedisBroker()

# In-memory snapshot storage {timestamp_str: serialized_state}
snapshots: Dict[str, Dict[str, Any]] = {}
# Lock for concurrent access to snapshots (optional for simple cases)
# snapshot_lock = threading.Lock()

# Keep track of connected clients (sids)
connected_clients = set()

# --- Redis Handling ---
def handle_remote_op_from_broker(operation: Operation):
    """Callback function for RedisBroker when a message arrives."""
    origin_site = operation.get('element', {}).get('id', [None, None])[1] if operation.get('type') == 'insert' else operation.get('element_id', [None, None])[1]
    if origin_site == doc_crdt.site_id:
        # print(f"Ignoring own operation from broker: {operation.get('type')}")
        return # Don't apply server's own operations coming back from Redis

    print(f"Received from Broker: {operation}")
    try:
        doc_crdt.apply_remote_operation(operation)
        # Broadcast the operation to all connected WebSocket clients
        # No need to skip anyone here, as this came from the broker (another user)
        with app.app_context():
            socketio.emit('operation', operation, room=DOCUMENT_CHANNEL)
            print(f"Broadcasted op from broker via WebSocket: {operation.get('type')}")
    except Exception as e:
        print(f"Error applying/broadcasting remote op from broker: {e}")

if broker.redis_client:
    broker.subscribe(DOCUMENT_CHANNEL, handle_remote_op_from_broker)
else:
    print("CRITICAL: Could not connect to Redis. Real-time sync disabled.")

# --- Flask Routes ---
@app.route('/')
def index():
    """Serves the main HTML page."""
    # Render index.html from the client/templates directory
    return render_template('index.html')

@app.route('/api/state')
def get_state():
    """Returns the current full state of the document."""
    current_value = doc_crdt.get_value()
    return jsonify({"value": current_value})

@app.route('/api/snapshots')
def get_snapshots():
    """Returns a list of available snapshot timestamps."""
    # Return sorted timestamps (most recent first)
    snapshot_timestamps = sorted(snapshots.keys(), reverse=True)
    return jsonify({"snapshots": snapshot_timestamps})

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    connected_clients.add(sid)
    print(f"Client connected: {sid}")
    # Automatically add client to the document room
    join_room(DOCUMENT_CHANNEL)
    print(f"Client {sid} joined room: {DOCUMENT_CHANNEL}")

    # Send the current state to the newly connected client
    try:
        current_value = doc_crdt.get_value()
        # Send the full RGA structure instead of just value? Might be better.
        # For MVP, just sending value is simpler for client.
        emit('initial_state', {'value': current_value})
        print(f"Sent initial state to {sid}: {current_value[:50]}...")
    except Exception as e:
        print(f"Error sending initial state to {sid}: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    connected_clients.discard(sid)
    leave_room(DOCUMENT_CHANNEL)
    print(f"Client disconnected: {sid}")

@socketio.on('text_change')
def handle_text_change(data: Dict[str, Any]):
    """Handles the full text received from a client."""
    sid = request.sid
    client_text = data.get('value', '')
    cursor_pos = data.get('cursor', None)
    # print(f"Received text_change from {sid}. Len: {len(client_text)}, Cursor: {cursor_pos}")

    server_text = doc_crdt.get_value()
    # generated_ops = [] # Removed, use ops_to_broadcast directly

    # Optimization: If text hasn't changed, do nothing
    if client_text == server_text:
        # print("Client text matches server text. No ops needed.")
        return

    # --- Diffing Logic (Simple version) ---
    # Use SequenceMatcher to find differences
    s = difflib.SequenceMatcher(None, server_text, client_text, autojunk=False)
    opcodes = s.get_opcodes()

    # print(f"Diff Opcodes: {opcodes}")

    # Process opcodes
    ops_to_broadcast = []
    error_occurred = False

    try:
        # IMPORTANT: Must process deletions in REVERSE order of opcodes/indices
        # to ensure indices remain valid after deletions.
        # Insertions can be processed forwards relative to their position *after* deletions.
        # Let's refine the logic: collect deletes, collect inserts, apply deletes (reverse), apply inserts.

        deletes_to_process: List[Tuple[int, int]] = [] # List of (start_index, end_index)
        inserts_to_process: List[Tuple[int, str]] = [] # List of (index, text_to_insert)

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'replace':
                deletes_to_process.append((i1, i2))
                inserts_to_process.append((i1, client_text[j1:j2]))
            elif tag == 'delete':
                deletes_to_process.append((i1, i2))
            elif tag == 'insert':
                inserts_to_process.append((i1, client_text[j1:j2]))

        # Process Deletions (in reverse index order)
        deletes_to_process.sort(key=lambda x: x[0], reverse=True)
        for start, end in deletes_to_process:
            for idx in range(end - 1, start - 1, -1):
                # print(f"    Generating delete at index {idx}")
                try:
                    delete_op = doc_crdt.local_delete(idx)
                    if delete_op and delete_op['type'] != 'noop':
                         ops_to_broadcast.append(delete_op)
                except IndexError as ie:
                    print(f"ERROR generating delete op at index {idx}: {ie}")
                    error_occurred = True
                    break # Stop processing deletes on error
            if error_occurred: break

        if error_occurred:
             raise RuntimeError("Error occurred during delete operation generation.")

        # Process Insertions (in forward index order)
        inserts_to_process.sort(key=lambda x: x[0])
        for index, text in inserts_to_process:
            for k, char_to_insert in enumerate(text):
                insertion_idx = index + k
                # print(f"    Generating insert '{char_to_insert}' at index {insertion_idx}")
                try:
                    insert_op = doc_crdt.local_insert(insertion_idx, char_to_insert)
                    if insert_op and insert_op['type'] != 'noop':
                         ops_to_broadcast.append(insert_op)
                except IndexError as ie:
                    print(f"ERROR generating insert op at index {insertion_idx}: {ie}")
                    error_occurred = True
                    break # Stop processing inserts on error
            if error_occurred: break

        if error_occurred:
             raise RuntimeError("Error occurred during insert operation generation.")

        # Verify final state (optional debug)
        final_server_text = doc_crdt.get_value()
        if final_server_text != client_text:
            print(f"WARNING: Server text after ops ({len(final_server_text)}) doesn't match client text ({len(client_text)})!")
            # print(f" Server: '{final_server_text[:100]}...'")
            # print(f" Client: '{client_text[:100]}...'")
            # Force resync by sending full state?
            emit('full_state_update', {'value': final_server_text}, room=DOCUMENT_CHANNEL) # Use a specific event

        # Publish & Broadcast generated operations
        if not ops_to_broadcast:
             # print("No operations generated from diff.")
             return

        # print(f"Generated {len(ops_to_broadcast)} ops. Publishing and Broadcasting...")
        for op in ops_to_broadcast:
            # Publish to Redis
            if broker.redis_client:
                broker.publish(DOCUMENT_CHANNEL, op)
            else:
                print("Warning: Redis not connected, cannot publish operation.")

            # Broadcast to other clients
            emit('operation', op, room=DOCUMENT_CHANNEL, skip_sid=sid)

    except IndexError as e:
         print(f"ERROR during op generation (likely index issue): {e}. Client: {sid}")
         emit('error', {'message': 'Server error processing change. Please reload.'}, room=sid)
    except Exception as e:
        print(f"ERROR processing text_change from {sid}: {e}")
        emit('error', {'message': f'Server error: {e}'}, room=sid)

@socketio.on('create_snapshot')
def handle_create_snapshot():
    """Creates a snapshot of the current document state."""
    sid = request.sid
    print(f"Received create_snapshot request from {sid}")
    try:
        # with snapshot_lock:
        snapshot_id = time.strftime("%Y-%m-%d_%H-%M-%S")
        snapshots[snapshot_id] = doc_crdt.serialize_state()
        print(f"Snapshot created: {snapshot_id}")
        # Notify all clients that snapshots have been updated
        snapshot_timestamps = sorted(snapshots.keys(), reverse=True)
        emit('snapshots_updated', {'snapshots': snapshot_timestamps}, room=DOCUMENT_CHANNEL)
        # Optionally notify the requester
        # emit('snapshot_created', {'id': snapshot_id}, room=sid)
    except Exception as e:
        print(f"Error creating snapshot: {e}")
        emit('error', {'message': f'Error creating snapshot: {e}'}, room=sid)

@socketio.on('revert_to_snapshot')
def handle_revert_to_snapshot(data: Dict[str, str]):
    """Reverts the document state to a specified snapshot."""
    sid = request.sid
    snapshot_id = data.get('id')
    if not snapshot_id:
        emit('error', {'message': 'Snapshot ID missing.'}, room=sid)
        return

    print(f"Received revert_to_snapshot request from {sid} for ID: {snapshot_id}")

    # with snapshot_lock:
    if snapshot_id not in snapshots:
        print(f"Snapshot ID {snapshot_id} not found.")
        emit('error', {'message': f'Snapshot {snapshot_id} not found.'}, room=sid)
        return

    try:
        serialized_state = snapshots[snapshot_id]
        # Create a new RGA instance from the snapshot state
        new_doc_crdt = RGA.deserialize_state(serialized_state)
        # Replace the global CRDT instance
        global doc_crdt
        doc_crdt = new_doc_crdt # This replaces the server's state
        print(f"Successfully reverted server state to snapshot {snapshot_id}")

        # Get the new full value
        new_value = doc_crdt.get_value()

        # Broadcast the NEW FULL STATE to all clients
        # Use a specific event name to indicate a full reset/revert
        emit('full_state_update', {'value': new_value}, room=DOCUMENT_CHANNEL)
        print(f"Broadcasted full_state_update to all clients. New value: {new_value[:50]}...")

        # Optional: Prune snapshots newer than the one reverted to?
        # snapshots_to_delete = [k for k in snapshots if k > snapshot_id]
        # for k in snapshots_to_delete:
        #     del snapshots[k]
        # if snapshots_to_delete:
        #      snapshot_timestamps = sorted(snapshots.keys(), reverse=True)
        #      emit('snapshots_updated', {'snapshots': snapshot_timestamps}, room=DOCUMENT_CHANNEL)

    except Exception as e:
        print(f"Error reverting to snapshot {snapshot_id}: {e}")
        emit('error', {'message': f'Error reverting to snapshot: {e}'}, room=sid)

# --- Cleanup ---
@atexit.register
def shutdown_broker():
    print("Flask app shutting down. Stopping Redis broker...")
    if broker:
        broker.stop()

# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    # socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    # Use allow_unsafe_werkzeug=True for Werkzeug >= 2.1 with debug mode
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True) 