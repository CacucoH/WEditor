// Establish WebSocket connection
// Use io() which defaults to connecting to the host that serves the page
const socket = io();

const textArea = document.getElementById('text-area');
const statusDisplay = document.getElementById('connection-status');
const saveSnapshotBtn = document.getElementById('save-snapshot-btn');
const snapshotList = document.getElementById('snapshot-list');
const revertSnapshotBtn = document.getElementById('revert-snapshot-btn');

let localCRDT = null; // Placeholder for client-side CRDT state if needed
let applyingRemoteOp = false; // Flag to prevent feedback loops

// --- SocketIO Event Handlers ---
socket.on('connect', () => {
    console.log('Connected to server with SID:', socket.id);
    statusDisplay.textContent = 'Connected';
    statusDisplay.className = 'connected';
    // Request initial state (handled by server on connection now)
    // socket.emit('request_initial_state');
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
    statusDisplay.textContent = 'Disconnected';
    statusDisplay.className = 'disconnected';
});

socket.on('connect_error', (error) => {
    console.error('Connection Error:', error);
    statusDisplay.textContent = 'Connection Failed';
    statusDisplay.className = 'disconnected';
});

socket.on('initial_state', (data) => {
    console.log('Received initial state:', data.value);
    applyingRemoteOp = true; // Prevent input handler from firing
    textArea.value = data.value;
    // Initialize local CRDT representation if we were using one
    // localCRDT = new RGA_JS(socket.id, data.crdt_state); // Example
    applyingRemoteOp = false;
});

socket.on('operation', (op) => {
    console.log('Received operation:', op);
    applyOperation(op);
});

socket.on('operation_error', (data) => {
    console.error('Server reported operation error:', data.error, 'for op:', data.original_op);
    // Optionally provide feedback to the user
    alert(`Error processing your change: ${data.error}`);
    // Potentially request full state resync here
});

socket.on('snapshots_updated', (data) => {
    console.log('Snapshots updated:', data.snapshots);
    updateSnapshotList(data.snapshots || []);
});

socket.on('full_state_update', (data) => {
    console.log('Received full state update:', data.value);
    applyingRemoteOp = true; // Prevent input handler from firing
    const currentCursorPos = textArea.selectionStart;
    const currentScrollTop = textArea.scrollTop;
    textArea.value = data.value;
    try {
        // Ensure cursor position is within new bounds
        const newPos = Math.min(currentCursorPos, textArea.value.length);
        textArea.setSelectionRange(newPos, newPos);
        textArea.scrollTop = currentScrollTop; // Restore scroll position
    } catch (e) { console.error("Error restoring cursor/scroll:", e); }
    applyingRemoteOp = false;
    alert("Document state reverted/updated.");
});

// --- CRDT Operation Application (Client-side) ---
function applyOperation(op) {
    // For MVP: Server broadcasts ops, client just needs to update its view.
    // The most robust way without JS CRDT is to GET the latest state.
    // We keep the inefficient full state request on receiving ANY op.
    console.warn('Applying received operation by requesting full state (MVP inefficiency)');
    applyingRemoteOp = true;
    const currentCursorPos = textArea.selectionStart;
    const currentScrollTop = textArea.scrollTop;

    // Fetch the latest state from the server after an operation
    // Use a small delay to allow server/broker processing, maybe not needed
    // setTimeout(() => {
        fetch('/api/state')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log("Updating text area from /api/state");
                textArea.value = data.value;
                // Try to preserve cursor
                try {
                    // Ensure cursor position is within new bounds
                    const newPos = Math.min(currentCursorPos, textArea.value.length);
                    textArea.setSelectionRange(newPos, newPos);
                    textArea.scrollTop = currentScrollTop; // Restore scroll position
                } catch (e) { console.error("Error restoring cursor/scroll:", e); }
                applyingRemoteOp = false;
            })
            .catch(error => {
                console.error('Error fetching state after operation:', error);
                applyingRemoteOp = false;
                // Maybe revert or show error?
            });
    // }, 50); // Small delay removed, fetch immediately

}

// --- Text Area Event Listener ---
let debounceTimer = null;
const DEBOUNCE_DELAY = 500; // ms - Adjust as needed

textArea.addEventListener('input', (event) => {
    if (applyingRemoteOp) {
        return; // Ignore changes caused by applying remote operations
    }

    // Debounce the input to avoid sending too many events
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        const currentText = textArea.value;
        const cursorPos = textArea.selectionStart;
        console.log(`Input debounced. Sending text_change. Length: ${currentText.length}, Cursor: ${cursorPos}`);

        // Send the full text and cursor position to the server
        socket.emit('text_change', {
            value: currentText,
            cursor: cursorPos // Send cursor info if server needs it for diffing context
        });
    }, DEBOUNCE_DELAY);

});

console.log("Collaborative editor script loaded.");
// Initial fetch of state (alternative to server push on connect)
/*
fetch('/api/state')
    .then(response => response.json())
    .then(data => {
        console.log('Fetched initial state via REST:', data.value);
        applyingRemoteOp = true;
        textArea.value = data.value;
        applyingRemoteOp = false;
    });
*/ 

// --- Snapshot Functions ---

function fetchSnapshots() {
    fetch('/api/snapshots')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log("Fetched snapshots:", data.snapshots);
            updateSnapshotList(data.snapshots || []);
        })
        .catch(error => {
            console.error('Error fetching snapshots:', error);
            snapshotList.innerHTML = '<option value="">Error loading</option>';
        });
}

function updateSnapshotList(snapshots) {
    snapshotList.innerHTML = ''; // Clear existing options
    if (snapshots.length === 0) {
        snapshotList.innerHTML = '<option value="">No snapshots yet</option>';
        revertSnapshotBtn.disabled = true;
    } else {
        snapshots.forEach(snapId => {
            const option = document.createElement('option');
            option.value = snapId;
            option.textContent = snapId;
            snapshotList.appendChild(option);
        });
        revertSnapshotBtn.disabled = false;
        snapshotList.selectedIndex = 0; // Select the first (most recent) one
    }
}

snapshotList.addEventListener('change', () => {
    revertSnapshotBtn.disabled = !snapshotList.value;
});

saveSnapshotBtn.addEventListener('click', () => {
    console.log("Requesting snapshot creation...");
    socket.emit('create_snapshot');
});

revertSnapshotBtn.addEventListener('click', () => {
    const selectedSnapshotId = snapshotList.value;
    if (!selectedSnapshotId) {
        alert("Please select a snapshot to revert to.");
        return;
    }
    if (confirm(`Are you sure you want to revert the document to snapshot ${selectedSnapshotId}? This cannot be undone easily.`)) {
        console.log(`Requesting revert to snapshot: ${selectedSnapshotId}`);
        socket.emit('revert_to_snapshot', { id: selectedSnapshotId });
    }
});

// Fetch initial snapshot list on load
fetchSnapshots();

// Initial fetch of state (alternative to server push on connect)
/*
fetch('/api/state')
    .then(response => response.json())
    .then(data => {
        console.log('Fetched initial state via REST:', data.value);
        applyingRemoteOp = true;
        textArea.value = data.value;
        applyingRemoteOp = false;
    });
*/ 