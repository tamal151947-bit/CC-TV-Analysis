const state = {
  cameras: [],
  alerts: []
};

const totalCamerasEl = document.getElementById('total-cameras');
const activeAlertsEl = document.getElementById('active-alerts');
const cameraGridEl = document.getElementById('camera-grid');
const alertListEl = document.getElementById('alert-list');
const reportStartDateEl = document.getElementById('report-start-date');
const reportEndDateEl = document.getElementById('report-end-date');
const reportIntervalEl = document.getElementById('report-interval');
const downloadReportBtnEl = document.getElementById('download-report-btn');
const emailReportBtnEl = document.getElementById('email-report-btn');
const saveReportScheduleBtnEl = document.getElementById('save-report-schedule-btn');
const stopReportScheduleBtnEl = document.getElementById('stop-report-schedule-btn');
const reportScheduleStatusEl = document.getElementById('report-schedule-status');
const reportMessageEl = document.getElementById('report-message');
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
const personMonitorFormEl = document.getElementById('person-monitor-form');
const personMonitorStatusEl = document.getElementById('person-monitor-status');
const personMonitorMessageEl = document.getElementById('person-monitor-message');
const stopPersonMonitorBtnEl = document.getElementById('stop-person-monitor-btn');
const referenceImageInputEl = personMonitorFormEl.querySelector('input[name="images"]');
const referenceUploadTitleEl = personMonitorFormEl.querySelector('.upload-title');
const referenceUploadHelpEl = personMonitorFormEl.querySelector('.upload-help');
const referenceGalleryEl = document.getElementById('reference-gallery');
const referenceCountEl = document.getElementById('reference-count');
let selectedReferenceImages = [];
let knownAlertIds = new Set();
let alertsInitialized = false;
let pendingPersonCameraId = null;
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
  if (alertsInitialized && newestAlerts.length > 0) {
    showAlertPopup(newestAlerts[0]);
  }
  knownAlertIds = new Set(state.alerts.map((alert) => alert.id));
  alertsInitialized = true;
  renderAlerts();
  updateHeader();
}

function showAlertPopup(alert) {
  const detectedAt = new Date(alert.timestamp).toLocaleString();
  alertToastEl.textContent = `${alert.threat_type === 'person_match' ? 'PERSON DETECTED' : alert.threat_type.toUpperCase()} - ${alert.camera_name} - ${detectedAt}`;
  alertToastEl.classList.add('visible');
  window.setTimeout(() => alertToastEl.classList.remove('visible'), 6000);
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('CCTV AI Guard alert', { body: alert.message });
  }
  if (alert.threat_type === 'person_match') {
    const cameraCard = document.querySelector(`[data-camera-card-id="${alert.camera_id}"]`);
    if (cameraCard) {
      cameraCard.classList.add('person-match-active');
      cameraCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      window.setTimeout(() => cameraCard.classList.remove('person-match-active'), 8000);
    } else {
      pendingPersonCameraId = alert.camera_id;
    }
  }
}

function updateHeader() {
  totalCamerasEl.textContent = state.cameras.length;
  activeAlertsEl.textContent = state.cameras.length ? state.alerts.length : 0;
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
    card.dataset.cameraCardId = camera.id;
    card.className = `camera-card ${camera.status === 'alert' ? 'alert' : ''}`;
    if (camera.id === pendingPersonCameraId) {
      card.classList.add('person-match-active');
      pendingPersonCameraId = null;
      window.setTimeout(() => card.classList.remove('person-match-active'), 8000);
      window.setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
    }
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

  state.alerts.slice(0, 10).forEach((alert) => {
    const item = document.createElement('li');
    item.className = alert.threat_type === 'person_match' ? 'person-match-alert' : '';
    item.innerHTML = `
      <strong>Camera: ${alert.camera_name}</strong><br>
      ${alert.message}<br>
      <small>${alert.threat_type === 'person_match' ? 'PERSON DETECTED' : alert.threat_type} • Detected: ${new Date(alert.timestamp).toLocaleString()}</small>
    `;
    alertListEl.appendChild(item);
  });
}

function toDateInputValue(date) {
  return date.toISOString().slice(0, 10);
}

function setDefaultReportDates() {
  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(today.getDate() - 7);
  reportStartDateEl.value = toDateInputValue(weekAgo);
  reportEndDateEl.value = toDateInputValue(today);
}

function reportRange() {
  const startDate = reportStartDateEl.value;
  const endDate = reportEndDateEl.value;
  if (!startDate || !endDate || endDate < startDate) {
    reportMessageEl.textContent = 'Choose a valid date range.';
    return null;
  }
  return { start_date: startDate, end_date: endDate };
}

function downloadAlertReport() {
  const range = reportRange();
  if (!range) return;
  const link = document.createElement('a');
  link.href = `/api/alerts/export?start_date=${encodeURIComponent(range.start_date)}&end_date=${encodeURIComponent(range.end_date)}`;
  link.download = `alert-report-${range.start_date}-to-${range.end_date}.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  reportMessageEl.textContent = 'Excel report download started.';
}

async function emailAlertReport() {
  const range = reportRange();
  if (!range) return;
  reportMessageEl.textContent = 'Sending Excel report...';
  const response = await fetch('/api/alerts/report-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(range)
  });
  const data = await response.json();
  reportMessageEl.textContent = response.ok ? `Report sent to ${data.email}.` : (data.detail || 'Report email failed.');
}

async function loadReportSchedule() {
  if (!reportIntervalEl || !reportScheduleStatusEl) return;
  const response = await fetch('/api/alerts/report-schedule');
  if (!response.ok) return;
  const data = await response.json();
  const schedule = data.schedule;
  if (!schedule || !schedule.enabled) return;
  reportIntervalEl.value = String(schedule.interval_hours);
  reportScheduleStatusEl.textContent = `Automatic reports every ${schedule.interval_hours}h`;
  saveReportScheduleBtnEl.textContent = 'Update automatic email';
  stopReportScheduleBtnEl.hidden = false;
}

async function saveReportSchedule() {
  if (!reportIntervalEl || !reportMessageEl) return;
  reportMessageEl.textContent = 'Saving automatic report schedule...';
  const response = await fetch('/api/alerts/report-schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval_hours: Number(reportIntervalEl.value) })
  });
  const data = await response.json();
  if (!response.ok) {
    reportMessageEl.textContent = data.detail || 'Could not save the report schedule.';
    return;
  }
  reportScheduleStatusEl.textContent = `Automatic reports every ${data.schedule.interval_hours}h`;
  saveReportScheduleBtnEl.textContent = 'Update automatic email';
  stopReportScheduleBtnEl.hidden = false;
  reportMessageEl.textContent = `Reports will be emailed to ${data.schedule.email}.`;
}

async function stopReportSchedule() {
  if (!stopReportScheduleBtnEl || !reportMessageEl) return;
  const response = await fetch('/api/alerts/report-schedule', { method: 'DELETE' });
  if (!response.ok) return;
  reportScheduleStatusEl.textContent = 'Automatic reports off';
  saveReportScheduleBtnEl.textContent = 'Enable automatic email';
  stopReportScheduleBtnEl.hidden = true;
  reportMessageEl.textContent = 'Automatic reports stopped.';
}

async function startPersonMonitor(event) {
  event.preventDefault();
  if (!selectedReferenceImages.length) {
    personMonitorMessageEl.textContent = 'Choose a reference picture first.';
    referenceImageInputEl.focus();
    return;
  }
  personMonitorMessageEl.textContent = 'Preparing live watch...';
  let response;
  let data;
  try {
    const formData = new FormData(personMonitorFormEl);
    formData.delete('images');
    selectedReferenceImages.forEach((file) => formData.append('images', file));
    response = await fetch('/api/person-monitor', { method: 'POST', body: formData });
    data = await response.json();
  } catch (error) {
    personMonitorMessageEl.textContent = 'Upload failed. Check that the server is running and try again.';
    return;
  }
  if (!response.ok) {
    personMonitorMessageEl.textContent = data.detail || 'Could not start person monitoring.';
    return;
  }
  personMonitorStatusEl.textContent = `Watching: ${data.name}`;
  personMonitorStatusEl.classList.add('active');
  personMonitorMessageEl.textContent = `${data.pictures} reference picture${data.pictures === 1 ? '' : 's'} active. All live cameras are being checked.`;
}

referenceImageInputEl.addEventListener('change', () => {
  const file = referenceImageInputEl.files[0];
  referenceImageInputEl.value = '';
  if (!file) {
    return;
  }
  if (selectedReferenceImages.length >= 5) {
    personMonitorMessageEl.textContent = 'You can add up to 5 reference pictures.';
    return;
  }
  selectedReferenceImages.push(file);
  referenceUploadTitleEl.textContent = `${selectedReferenceImages.length} picture${selectedReferenceImages.length === 1 ? '' : 's'} selected`;
  referenceUploadHelpEl.textContent = `${file.name} added. Select another angle or start live watch.`;
  renderReferenceImages();
});

function renderReferenceImages() {
  referenceGalleryEl.innerHTML = '';
  referenceCountEl.textContent = `${selectedReferenceImages.length}/5 angles uploaded`;
  selectedReferenceImages.forEach((file, index) => {
    const item = document.createElement('div');
    item.className = 'reference-thumb';
    const preview = document.createElement('img');
    preview.src = URL.createObjectURL(file);
    preview.alt = `Reference angle ${index + 1}`;
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.title = 'Remove reference angle';
    removeButton.setAttribute('aria-label', `Remove reference angle ${index + 1}`);
    removeButton.textContent = '\u{1F5D1}';
    item.append(preview, removeButton);
    removeButton.addEventListener('click', () => {
      selectedReferenceImages.splice(index, 1);
      referenceUploadTitleEl.textContent = selectedReferenceImages.length ? `${selectedReferenceImages.length} picture${selectedReferenceImages.length === 1 ? '' : 's'} selected` : 'Upload reference pictures';
      referenceUploadHelpEl.textContent = selectedReferenceImages.length ? 'Select another angle or start live watch.' : 'Select one picture at a time. Add up to 5 different angles.';
      renderReferenceImages();
    });
    referenceGalleryEl.appendChild(item);
  });
  if (selectedReferenceImages.length < 5) {
    const addAngle = document.createElement('button');
    addAngle.type = 'button';
    addAngle.className = 'add-angle-btn';
    addAngle.innerHTML = '<span aria-hidden="true">+</span><span>Add next angle</span>';
    addAngle.addEventListener('click', () => referenceImageInputEl.click());
    referenceGalleryEl.appendChild(addAngle);
  }
}

async function stopPersonMonitor() {
  const response = await fetch('/api/person-monitor', { method: 'DELETE' });
  if (!response.ok) return;
  personMonitorStatusEl.textContent = 'Off';
  personMonitorStatusEl.classList.remove('active');
  personMonitorMessageEl.textContent = 'Person monitoring stopped.';
  personMonitorFormEl.reset();
  selectedReferenceImages = [];
  referenceUploadTitleEl.textContent = 'Upload reference pictures';
  referenceUploadHelpEl.textContent = 'Select one picture at a time. Add up to 5 different angles.';
  renderReferenceImages();
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
personMonitorFormEl.addEventListener('submit', startPersonMonitor);
stopPersonMonitorBtnEl.addEventListener('click', stopPersonMonitor);
downloadReportBtnEl.addEventListener('click', downloadAlertReport);
emailReportBtnEl.addEventListener('click', emailAlertReport);
if (saveReportScheduleBtnEl) saveReportScheduleBtnEl.addEventListener('click', saveReportSchedule);
if (stopReportScheduleBtnEl) stopReportScheduleBtnEl.addEventListener('click', stopReportSchedule);
connectionTypeEl.addEventListener('change', updateConnectionHelp);
updateConnectionHelp();
renderReferenceImages();
setDefaultReportDates();
if (reportIntervalEl) loadReportSchedule();

fetchCameras();
fetchAlerts();
window.setInterval(() => {
  fetchCameras();
  fetchAlerts();
}, 5000);
