let currentFileId = null;
let files = new Map(); // Key: fileId, Value: {name, content}
let authState = { loggedIn: false, username: 'guest' };

const authModal = document.getElementById('auth-modal');
const usernameDisplay = document.getElementById('username');

function showAuthModal() {
    authModal.style.display = 'block';
}

function hideAuthModal() {
    authModal.style.display = 'none';
}

function handleLogin() {
    // Placeholder for login functionality
    authState.loggedIn = true;
    authState.username = document.getElementById('login-username').value || 'user';
    usernameDisplay.textContent = authState.username;
    hideAuthModal();
}

function handleSignup() {
    // Placeholder for signup functionality
    alert('Signup functionality not implemented');
}

function continueAsGuest() {
    authState.loggedIn = false;
    authState.username = 'guest';
    usernameDisplay.textContent = 'guest';
    hideAuthModal();
}

function createNewFile() {
    const fileId = Date.now().toString();
    const fileName = `file${files.size + 1}.txt`;
    
    files.set(fileId, {
        name: fileName,
        content: ''
    });
    
    renderFileTabs();
    switchFile(fileId);
}

function switchFile(fileId) {
    currentFileId = fileId;
    document.querySelectorAll('.file-tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.dataset.fileId === fileId) {
            tab.classList.add('active');
        }
    });
    
    // For now, all files share the same content
    // textArea.value = files.get(fileId).content;
}

function renderFileTabs() {
    const fileList = document.getElementById('file-list');
    fileList.innerHTML = '';
    
    files.forEach((file, fileId) => {
        const tab = document.createElement('div');
        tab.className = `file-tab ${fileId === currentFileId ? 'active' : ''}`;
        tab.dataset.fileId = fileId;
        tab.innerHTML = `
            <span>${file.name}</span>
            <i class="fas fa-times" onclick="closeFile('${fileId}')"></i>
        `;
        tab.addEventListener('click', () => switchFile(fileId));
        fileList.appendChild(tab);
    });
}

function closeFile(fileId) {
    if (files.size === 1) return;
    files.delete(fileId);
    if (currentFileId === fileId) {
        currentFileId = Array.from(files.keys())[0];
    }
    renderFileTabs();
}

createNewFile();
showAuthModal();

const socket = io();

const textArea = document.getElementById('text-area');
const statusDisplay = document.getElementById('connection-status');
const saveSnapshotBtn = document.getElementById('save-snapshot-btn');
const snapshotList = document.getElementById('snapshot-list');
const revertSnapshotBtn = document.getElementById('revert-snapshot-btn');

let localCRDT = null;
let applyingRemoteOp = false;

socket.on('connect', () => {
    console.log('Connected to server with SID:', socket.id);
    statusDisplay.textContent = 'Connected';
    statusDisplay.className = 'connected';
    document.getElementById('connection-status').textContent = 'Connected';
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
    statusDisplay.textContent = 'Disconnected';
    statusDisplay.className = 'disconnected';
    document.getElementById('connection-status').textContent = 'Disconnected';
});

socket.on('connect_error', (error) => {
    console.error('Connection Error:', error);
    statusDisplay.textContent = 'Connection Failed';
    statusDisplay.className = 'disconnected';
});

socket.on('initial_state', (data) => {
    console.log('Received initial state:', data.value);
    applyingRemoteOp = true;
    textArea.value = data.value;
    applyingRemoteOp = false;
});

socket.on('operation', (op) => {
    console.log('Received operation:', op);
    applyOperation(op);
});

socket.on('operation_error', (data) => {
    console.error('Server reported operation error:', data.error, 'for op:', data.original_op);
    alert(`Error processing your change: ${data.error}`);

});

socket.on('snapshots_updated', (data) => {
    console.log('Snapshots updated:', data.snapshots);
    updateSnapshotList(data.snapshots || []);
});

socket.on('full_state_update', (data) => {
    console.log('Received full state update:', data.value);
    applyingRemoteOp = true;
    const currentCursorPos = textArea.selectionStart;
    const currentScrollTop = textArea.scrollTop;
    textArea.value = data.value;
    try {

        const newPos = Math.min(currentCursorPos, textArea.value.length);
        textArea.setSelectionRange(newPos, newPos);
        textArea.scrollTop = currentScrollTop;
    } catch (e) { console.error("Error restoring cursor/scroll:", e); }
    applyingRemoteOp = false;
});

function applyOperation(op) {
    console.warn('Applying received operation by requesting full state (MVP inefficiency)');
    applyingRemoteOp = true;
    const currentCursorPos = textArea.selectionStart;
    const currentScrollTop = textArea.scrollTop;
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

                try {

                    const newPos = Math.min(currentCursorPos, textArea.value.length);
                    textArea.setSelectionRange(newPos, newPos);
                    textArea.scrollTop = currentScrollTop;
                } catch (e) { console.error("Error restoring cursor/scroll:", e); }
                applyingRemoteOp = false;
            })
            .catch(error => {
                console.error('Error fetching state after operation:', error);
                applyingRemoteOp = false;

            });
}

let debounceTimer = null;
const DEBOUNCE_DELAY = 500;

textArea.addEventListener('input', (event) => {
    if (applyingRemoteOp) {
        return;
    }
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        const currentText = textArea.value;
        const cursorPos = textArea.selectionStart;
        console.log(`Input debounced. Sending text_change. Length: ${currentText.length}, Cursor: ${cursorPos}`);
        socket.emit('text_change', {
            value: currentText,
            cursor: cursorPos
        });
    }, DEBOUNCE_DELAY);

});

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
    snapshotList.innerHTML = '';
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
        snapshotList.selectedIndex = 0;
    }
}

snapshotList.addEventListener('change', () => {
    revertSnapshotBtn.disabled = !snapshotList.value;
});

saveSnapshotBtn.addEventListener('click', () => {
    console.log("Requesting snapshot save");
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

fetchSnapshots();
