const state = {
  cameras: [],
  alerts: []
};

const totalCamerasEl = document.getElementById('total-cameras');
const activeAlertsEl = document.getElementById('active-alerts');
const cameraGridEl = document.getElementById('camera-grid');
const alertListEl = document.getElementById('alert-list');
const connectFormEl = document.getElementById('connect-camera-form');
const connectMessageEl = document.getElementById('connect-message');
const connectionTypeEl = document.getElementById('connection-type');
const cameraUrlEl = document.getElementById('camera-url');
const connectionHelpEl = document.getElementById('connection-help');
const alertToastEl = document.getElementById('alert-toast');
let knownAlertIds = new Set();

async function fetchCameras() {
  const response = await fetch('/api/cameras');
  const data = await response.json();
  state.cameras = data.cameras || [];
  renderCameras();
  updateHeader();
}

async function fetchAlerts() {
  const response = await fetch('/api/alerts');
  const data = await response.json();
  state.alerts = data.alerts || [];
  const newestAlerts = state.alerts.filter((alert) => !knownAlertIds.has(alert.id));
  if (knownAlertIds.size > 0 && newestAlerts.length > 0) {
    showAlertPopup(newestAlerts[0]);
  }
  knownAlertIds = new Set(state.alerts.map((alert) => alert.id));
  renderAlerts();
  updateHeader();
}

function showAlertPopup(alert) {
  alertToastEl.textContent = `${alert.threat_type.toUpperCase()} - ${alert.camera_name}`;
  alertToastEl.classList.add('visible');
  window.setTimeout(() => alertToastEl.classList.remove('visible'), 6000);
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('CCTV AI Guard alert', { body: alert.message });
  }
}

function updateHeader() {
  totalCamerasEl.textContent = state.cameras.length;
  activeAlertsEl.textContent = state.alerts.length;
}

function renderCameras() {
  cameraGridEl.innerHTML = '';
  if (state.cameras.length === 0) {
    cameraGridEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">+</div>
        <h3>Your watch floor is ready</h3>
        <p>Add your first camera from the panel on the left to start monitoring live footage.</p>
      </div>
    `;
    return;
  }
  state.cameras.forEach((camera) => {
    const card = document.createElement('article');
    card.className = `camera-card ${camera.status === 'alert' ? 'alert' : ''}`;
    card.innerHTML = `
      <div class="camera-card-header">
        <h3>${camera.name}</h3>
        <span class="camera-indicator" title="${camera.status}"></span>
      </div>
      ${camera.status === 'offline'
        ? '<div class="camera-feed feed-unavailable">No RTSP stream configured</div>'
        : `<img class="camera-feed" src="/api/cameras/${camera.id}/video" alt="Live feed from ${camera.name}" />`}
      <p>${camera.location}</p>
      <p>Status: ${camera.status}</p>
      <p>Alert Level: ${camera.alert_level}</p>
      ${camera.status === 'alert' ? '<span class="alert-badge">ALERT</span>' : ''}
    `;
    cameraGridEl.appendChild(card);
  });
}

async function connectCamera(event) {
  event.preventDefault();
  connectMessageEl.textContent = 'Connecting...';
  const formData = new FormData(connectFormEl);
  const response = await fetch('/api/cameras/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.fromEntries(formData.entries()))
  });
  const data = await response.json();
  if (!response.ok) {
    connectMessageEl.textContent = data.detail || 'Could not connect camera.';
    return;
  }
  connectMessageEl.textContent = `${data.camera.name} connected.`;
  connectFormEl.reset();
  await fetchCameras();
}

function updateConnectionHelp() {
  const help = {
    rtsp: ['rtsp://admin:password@192.168.1.50:554/stream1', 'Example: rtsp://admin:password@192.168.1.50:554/stream1'],
    http: ['http://192.168.1.50:8080/video', 'Example: http://192.168.1.50:8080/video'],
    webcam: ['webcam://0', 'Use webcam://0 for the first USB webcam, webcam://1 for the second.']
  }[connectionTypeEl.value];
  cameraUrlEl.placeholder = help[0];
  connectionHelpEl.textContent = help[1];
}

function renderAlerts() {
  alertListEl.innerHTML = '';
  if (state.alerts.length === 0) {
    alertListEl.innerHTML = '<li>No alerts.</li>';
    return;
  }

  state.alerts.slice(0, 8).forEach((alert) => {
    const item = document.createElement('li');
    item.innerHTML = `
      <strong>${alert.camera_name}</strong><br>
      ${alert.message}<br>
      <small>${alert.threat_type} • ${new Date(alert.timestamp).toLocaleString()}</small>
    `;
    alertListEl.appendChild(item);
  });
}

async function simulateAlert() {
  const camera = state.cameras[Math.floor(Math.random() * state.cameras.length)];
  const types = ['theft', 'intrusion', 'violence', 'missing_object', 'suspicious_activity'];
  const type = types[Math.floor(Math.random() * types.length)];
  await fetch(`/api/cameras/${camera.id}/simulate-activity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ threat_type: type })
  });
  await fetchCameras();
  await fetchAlerts();
}

async function clearAlerts() {
  await fetch('/api/alerts/clear', { method: 'POST' });
  await fetchCameras();
  await fetchAlerts();
}

document.getElementById('simulate-alert-btn').addEventListener('click', simulateAlert);
document.getElementById('clear-alerts-btn').addEventListener('click', clearAlerts);
connectFormEl.addEventListener('submit', connectCamera);
connectionTypeEl.addEventListener('change', updateConnectionHelp);
updateConnectionHelp();

fetchCameras();
fetchAlerts();
window.setInterval(() => {
  fetchCameras();
  fetchAlerts();
}, 5000);
