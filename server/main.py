import sys
import os
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import atexit
import difflib
import time
from typing import Dict, Any, List, Tuple

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from common.broker import RedisBroker
from crdt.rga import RGA, Operation

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
DOCUMENT_CHANNEL = "doc1"

app = Flask(__name__, template_folder='../client/templates', static_folder='../client/static')
app.config['SECRET_KEY'] = 'secret!changethis'

socketio = SocketIO(app, async_mode='threading')

doc_crdt = RGA(site_id="server")

broker = RedisBroker()

snapshots: Dict[str, Dict[str, Any]] = {}

connected_clients = set()

def handle_remote_op_from_broker(operation: Operation):
    origin_site = operation.get('element', {}).get('id', [None, None])[1] if operation.get('type') == 'insert' else operation.get('element_id', [None, None])[1]
    if origin_site == doc_crdt.site_id:
        return

    print(f"Received from Broker: {operation}")
    try:
        doc_crdt.apply_remote_operation(operation)
        with app.app_context():
            socketio.emit('operation', operation, room=DOCUMENT_CHANNEL)
            print(f"Broadcasted op from broker via WebSocket: {operation.get('type')}")
    except Exception as e:
        print(f"Error applying/broadcasting remote op from broker: {e}")

if broker.redis_client:
    broker.subscribe(DOCUMENT_CHANNEL, handle_remote_op_from_broker)
else:
    print("CRITICAL: Could not connect to Redis. Real-time sync disabled.")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state')
def get_state():
    current_value = doc_crdt.get_value()
    return jsonify({"value": current_value})

@app.route('/api/snapshots')
def get_snapshots():
    snapshot_timestamps = sorted(snapshots.keys(), reverse=True)
    return jsonify({"snapshots": snapshot_timestamps})

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    connected_clients.add(sid)
    print(f"Client connected: {sid}")
    join_room(DOCUMENT_CHANNEL)
    print(f"Client {sid} joined room: {DOCUMENT_CHANNEL}")

    try:
        current_value = doc_crdt.get_value()
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
    sid = request.sid
    client_text = data.get('value', '')
    cursor_pos = data.get('cursor', None)

    server_text = doc_crdt.get_value()

    if client_text == server_text:
        return

    s = difflib.SequenceMatcher(None, server_text, client_text, autojunk=False)
    opcodes = s.get_opcodes()

    ops_to_broadcast = []
    error_occurred = False

    try:
        deletes_to_process: List[Tuple[int, int]] = []
        inserts_to_process: List[Tuple[int, str]] = []

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'replace':
                deletes_to_process.append((i1, i2))
                inserts_to_process.append((i1, client_text[j1:j2]))
            elif tag == 'delete':
                deletes_to_process.append((i1, i2))
            elif tag == 'insert':
                inserts_to_process.append((i1, client_text[j1:j2]))

        deletes_to_process.sort(key=lambda x: x[0], reverse=True)
        for start, end in deletes_to_process:
            for idx in range(end - 1, start - 1, -1):
                try:
                    delete_op = doc_crdt.local_delete(idx)
                    if delete_op and delete_op['type'] != 'noop':
                         ops_to_broadcast.append(delete_op)
                except IndexError as ie:
                    print(f"ERROR generating delete op at index {idx}: {ie}")
                    error_occurred = True
                    break
            if error_occurred: break

        if error_occurred:
             raise RuntimeError("Error occurred during delete operation generation.")

        inserts_to_process.sort(key=lambda x: x[0])
        for index, text in inserts_to_process:
            for k, char_to_insert in enumerate(text):
                insertion_idx = index + k
                try:
                    insert_op = doc_crdt.local_insert(insertion_idx, char_to_insert)
                    if insert_op and insert_op['type'] != 'noop':
                         ops_to_broadcast.append(insert_op)
                except IndexError as ie:
                    print(f"ERROR generating insert op at index {insertion_idx}: {ie}")
                    error_occurred = True
                    break
            if error_occurred: break

        if error_occurred:
             raise RuntimeError("Error occurred during insert operation generation.")

        final_server_text = doc_crdt.get_value()
        if final_server_text != client_text:
            print(f"WARNING: Server text after ops ({len(final_server_text)}) doesn't match client text ({len(client_text)})!")
            emit('full_state_update', {'value': final_server_text}, room=DOCUMENT_CHANNEL)

        if not ops_to_broadcast:
             return

        for op in ops_to_broadcast:
            if broker.redis_client:
                broker.publish(DOCUMENT_CHANNEL, op)
            else:
                print("Warning: Redis not connected, cannot publish operation.")

            emit('operation', op, room=DOCUMENT_CHANNEL, skip_sid=sid)

    except IndexError as e:
         print(f"ERROR during op generation (likely index issue): {e}. Client: {sid}")
         emit('error', {'message': 'Server error processing change. Please reload.'}, room=sid)
    except Exception as e:
        print(f"ERROR processing text_change from {sid}: {e}")
        emit('error', {'message': f'Server error: {e}'}, room=sid)

@socketio.on('create_snapshot')
def handle_create_snapshot():
    sid = request.sid
    print(f"Received create_snapshot request from {sid}")
    try:
        snapshot_id = time.strftime("%Y-%m-%d_%H-%M-%S")
        snapshots[snapshot_id] = doc_crdt.serialize_state()
        print(f"Snapshot created: {snapshot_id}")
        snapshot_timestamps = sorted(snapshots.keys(), reverse=True)
        emit('snapshots_updated', {'snapshots': snapshot_timestamps}, room=DOCUMENT_CHANNEL)

    except Exception as e:
        print(f"Error creating snapshot: {e}")
        emit('error', {'message': f'Error creating snapshot: {e}'}, room=sid)

@socketio.on('revert_to_snapshot')
def handle_revert_to_snapshot(data: Dict[str, str]):
    sid = request.sid
    snapshot_id = data.get('id')

    if not snapshot_id:
        print(f"Error: No snapshot ID provided by {sid}")
        emit('error', {'message': 'No snapshot ID provided'}, room=sid)
        return

    if snapshot_id not in snapshots:
        print(f"Error: Snapshot ID '{snapshot_id}' not found (requested by {sid})")
        emit('error', {'message': 'Snapshot  not found'}, room=sid)
        return

    print(f"Reverting document state to snapshot: {snapshot_id} (requested by {sid})")
    try:
        doc_crdt.load_state(snapshots[snapshot_id])
        current_value = doc_crdt.get_value()
        emit('full_state_update', {'value': current_value}, room=DOCUMENT_CHANNEL)
        print(f"Broadcasted full state update after revert to snapshot {snapshot_id}")

    except Exception as e:
        print(f"Error reverting to snapshot {snapshot_id}: {e}")
        emit('error', {'message': f'Error reverting to snapshot: {e}'}, room=sid)

@atexit.register
def shutdown_broker():
    broker.stop()

if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)