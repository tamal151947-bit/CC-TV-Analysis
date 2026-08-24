const state = {
  cameras: [],
  alerts: []
};

const totalCamerasEl = document.getElementById('total-cameras');
const activeAlertsEl = document.getElementById('active-alerts');
const cameraGridEl = document.getElementById('camera-grid');
const alertListEl = document.getElementById('alert-list');
const connectFormEl = document.getElementById('connect-camera-form');
const connectCameraBtnEl = document.getElementById('connect-camera-btn');
const upgradePlanBtnEl = document.getElementById('upgrade-plan-btn');
const connectMessageEl = document.getElementById('connect-message');
const connectionTypeEl = document.getElementById('connection-type');
const cameraUrlEl = document.getElementById('camera-url');
const connectionHelpEl = document.getElementById('connection-help');
const alertToastEl = document.getElementById('alert-toast');
const monitoringStatusEl = document.getElementById('monitoring-status');
const monitoringStatusDotEl = document.getElementById('monitoring-status-dot');
const monitoringStatusLabelEl = document.getElementById('monitoring-status-label');
let knownAlertIds = new Set();
let cameraRefreshVersion = 0;
let renderedCameraSignature = null;
const webcamMediaStreams = new Map();

function getCameraSignature(cameras) {
  return cameras.map((camera) => [
    camera.id,
    camera.name,
    camera.location,
    camera.rtsp_url,
    camera.status,
    camera.alert_level
  ].join('|')).join('||');
}

async function fetchCameras() {
  const requestVersion = ++cameraRefreshVersion;
  const response = await fetch('/api/cameras', { cache: 'no-store' });
  const data = await response.json();
  if (requestVersion !== cameraRefreshVersion) {
    return;
  }
  const nextCameras = data.cameras || [];
  const nextSignature = getCameraSignature(nextCameras);
  state.cameras = nextCameras;
  if (renderedCameraSignature === null || nextSignature !== renderedCameraSignature) {
    renderCameras();
  } else {
    updateHeader();
  }
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
  const isMonitoring = state.cameras.some((camera) => camera.status === 'online' || camera.status === 'alert');
  monitoringStatusEl.textContent = isMonitoring ? 'Monitoring live' : 'Monitoring off';
  monitoringStatusDotEl.classList.toggle('is-offline', !isMonitoring);
  monitoringStatusLabelEl.classList.toggle('is-offline', !isMonitoring);
}

function renderCameras() {
  updateHeader();
  renderedCameraSignature = getCameraSignature(state.cameras);
  const activeCameraIds = new Set(state.cameras.map((camera) => camera.id));
  webcamMediaStreams.forEach((stream, cameraId) => {
    if (!activeCameraIds.has(cameraId)) {
      stream.getTracks().forEach((track) => track.stop());
      webcamMediaStreams.delete(cameraId);
    }
  });
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
    const isWebcam = camera.rtsp_url.startsWith('webcam://');
    card.innerHTML = `
      <div class="camera-card-header">
        <h3>${camera.name}</h3>
        <span class="camera-indicator" title="${camera.status}"></span>
      </div>
      ${camera.status === 'offline'
        ? '<div class="camera-feed feed-unavailable">Camera feed unavailable</div>'
        : isWebcam
          ? `<video class="camera-feed webcam-preview" data-camera-id="${camera.id}" autoplay playsinline muted></video>`
          : `<img class="camera-feed" src="/api/cameras/${camera.id}/video" alt="Live feed from ${camera.name}" loading="eager" />`}
      <p>${camera.location}</p>
      <p>Status: ${camera.status}</p>
      <p>Alert Level: ${camera.alert_level}</p>
      ${camera.status === 'alert' ? '<span class="alert-badge">ALERT</span>' : ''}
      <button class="remove-camera-btn secondary" data-camera-id="${camera.id}" type="button">Remove camera</button>
    `;
    const feed = card.querySelector('.camera-feed');
    if (feed.tagName === 'IMG') {
      const feedUrl = `/api/cameras/${camera.id}/video`;
      feed.addEventListener('error', () => {
        card.classList.add('stream-unavailable');
        window.setTimeout(() => {
          if (feed.isConnected) {
            feed.src = `${feedUrl}?retry=${Date.now()}`;
          }
        }, 1000);
      });
    }
    if (isWebcam && feed.tagName === 'VIDEO') {
      startWebcamPreview(feed, camera.id);
    }
    card.querySelector('.remove-camera-btn').addEventListener('click', () => removeCamera(camera));
    cameraGridEl.appendChild(card);
  });
}

async function startWebcamPreview(video, cameraId) {
  const existingStream = webcamMediaStreams.get(cameraId);
  if (existingStream && existingStream.getVideoTracks().some((track) => track.readyState === 'live')) {
    video.srcObject = existingStream;
    return;
  }
  if (existingStream) {
    existingStream.getTracks().forEach((track) => track.stop());
    webcamMediaStreams.delete(cameraId);
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    video.replaceWith(createUnavailableFeed('Browser webcam access is unavailable.'));
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    if (!video.isConnected) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    webcamMediaStreams.set(cameraId, stream);
    video.srcObject = stream;
    stream.getTracks().forEach((track) => {
      track.addEventListener('ended', () => {
        if (video.isConnected && !stream.getVideoTracks().some((item) => item.readyState === 'live')) {
          webcamMediaStreams.delete(cameraId);
          startWebcamPreview(video, cameraId);
        }
      });
    });
  } catch (error) {
    video.replaceWith(createUnavailableFeed('Allow camera access in the browser to view this webcam.'));
  }
}

function createUnavailableFeed(message) {
  const feed = document.createElement('div');
  feed.className = 'camera-feed feed-unavailable';
  feed.textContent = message;
  return feed;
}

async function removeCamera(camera) {
  if (!window.confirm(`Remove ${camera.name}?`)) {
    return;
  }
  const password = window.prompt('Enter your account password to remove this camera:');
  if (password === null) {
    return;
  }
  cameraRefreshVersion += 1;
  const response = await fetch(`/api/cameras/${camera.id}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password })
  });
  const data = await response.json();
  if (!response.ok) {
    window.alert(data.detail || 'Could not remove camera.');
    return;
  }
  state.cameras = state.cameras.filter((item) => item.id !== camera.id);
  renderCameras();
  updateHeader();
  connectMessageEl.textContent = `${formatCameraCount(state.cameras.length)}.`;
  await fetchCameras();
}

function formatCameraCount(count) {
  return `${count} camera${count === 1 ? '' : 's'} connected`;
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
    const message = data.detail || 'Could not connect camera.';
    connectMessageEl.textContent = message;
    const isCameraLimit = message.toLowerCase().includes('limit') && message.toLowerCase().includes('upgrade');
    connectCameraBtnEl.hidden = isCameraLimit;
    upgradePlanBtnEl.hidden = !isCameraLimit;
    return;
  }
  connectMessageEl.textContent = `${formatCameraCount(state.cameras.length + 1)}.`;
  connectCameraBtnEl.hidden = false;
  upgradePlanBtnEl.hidden = true;
  connectFormEl.reset();
  state.cameras = [...state.cameras, data.camera];
  renderCameras();
  updateHeader();
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
