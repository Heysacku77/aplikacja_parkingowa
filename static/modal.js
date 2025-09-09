const PENDING_KEY = 'parkingDecisionPending'; 
const ACTIVE_KEY  = 'activeParking';          

let modalListenersAttached = false;
let timerId = null;

function getModalEls() {
  return {
    modal: document.getElementById('decision-modal'),
    okBtn: document.getElementById('btn-park'),
    noBtn: document.getElementById('btn-no-park'),
    finishBtn: document.getElementById('btn-finish'),
    decisionView: document.getElementById('decision-view'),
    activeView: document.getElementById('active-view'),
    timerEl: document.getElementById('timer'),
  };
}


function setPendingDecision(obj){ try{ localStorage.setItem(PENDING_KEY, JSON.stringify(obj)); }catch{} }
function getPendingDecision(){ try{ const r=localStorage.getItem(PENDING_KEY); return r?JSON.parse(r):null; }catch{ return null; } }
function clearPendingDecision(){ try{ localStorage.removeItem(PENDING_KEY); }catch{} }

function setActiveParking(obj){ try{ localStorage.setItem(ACTIVE_KEY, JSON.stringify(obj)); }catch{} }
function getActiveParking(){ try{ const r=localStorage.getItem(ACTIVE_KEY); return r?JSON.parse(r):null; }catch{ return null; } }
function clearActiveParking(){ try{ localStorage.removeItem(ACTIVE_KEY); }catch{} }

function fmt(n){ return String(n).padStart(2,'0'); }
function formatDuration(ms){
  const s = Math.floor(ms/1000);
  const h = Math.floor(s/3600);
  const m = Math.floor((s%3600)/60);
  const ss = s%60;
  return `${fmt(h)}:${fmt(m)}:${fmt(ss)}`;
}
function startTimer(startedAtISO){
  stopTimer();
  const { timerEl } = getModalEls();
  if (!timerEl) return;

  const hasTz = /Z$|[+\-]\d{2}:\d{2}$/.test(startedAtISO);
  const normalized = hasTz ? startedAtISO : (startedAtISO + 'Z');
  const startedMs = new Date(normalized).getTime();

  const tick = () => { timerEl.textContent = formatDuration(Date.now() - startedMs); };
  tick();
  timerId = setInterval(tick, 1000);
}
function stopTimer(){
  if (timerId){ clearInterval(timerId); timerId = null; }
}

function showDecisionView(){
  const { decisionView, activeView } = getModalEls();
  if (decisionView) decisionView.style.display = 'block';
  if (activeView)   activeView.style.display   = 'none';
}
function showActiveView(){
  const { decisionView, activeView } = getModalEls();
  if (decisionView) decisionView.style.display = 'none';
  if (activeView)   activeView.style.display   = 'block';
}

function redirectToLogin() {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/login?next=${next}`;
}

async function fetchActiveFromServerAndShow() {
  try {
    const res = await fetch('/api/me/active_reservation', { credentials: 'same-origin' });
    if (!res.ok) return false;
    const j = await res.json();
    if (!j.active) return false;
    setActiveParking({ osm_id: j.osm_id, started_at: j.started_at });
    ensureDecisionModal();
    showActiveView();
    const { modal } = getModalEls();
    if (modal) modal.classList.add('open');
    startTimer(j.started_at);
    return true;
  } catch { return false; }
}

function attachModalListeners() {
  if (modalListenersAttached) return;
  const { modal, okBtn, noBtn, finishBtn } = getModalEls();
  if (!modal || !okBtn || !noBtn || !finishBtn) return;

  okBtn.addEventListener('click', async () => {
    const pending = getPendingDecision();
    if (!pending || !pending.osm) return;

    try {
      const res = await fetch(`/api/parkings/${pending.osm}/reserve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({})
      });
      const j = await res.json();

      if (res.status === 401 || j.error === 'auth_required') {
        redirectToLogin(); return;
      }
      if (!res.ok || !j.ok) {
        if (j.error === 'already_reserved') {
          const shown = await fetchActiveFromServerAndShow();
          if (!shown) alert('Masz już aktywne parkowanie.');
          clearPendingDecision();
          return;
        }
        if (j.error === 'no_space') {
          alert('Parking jest pełny – spróbuj inny.'); return;
        }
        alert('Nie udało się zarezerwować: ' + (j.error || res.status));
        return;
      }

      clearPendingDecision();
      setActiveParking({ osm_id: j.osm_id, started_at: j.started_at });
      showActiveView();
      startTimer(j.started_at);
    } catch (err) {
      console.error(err);
      alert('Błąd sieci przy rezerwacji.');
    }
  });

  noBtn.addEventListener('click', () => {
    clearPendingDecision();
    closeDecisionModal();
  });

  finishBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/reservations/finish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
      });
      const j = await res.json();

      if (res.status === 401 || j.error === 'auth_required') {
        redirectToLogin(); return;
      }
      if (!res.ok || !j.ok) {
        alert('Nie udało się zakończyć: ' + (j.error || res.status)); return;
      }
      clearActiveParking();
      stopTimer();
      closeDecisionModal();
    } catch (err) {
      console.error(err);
      alert('Błąd sieci przy kończeniu rezerwacji.');
    }
  });

  modalListenersAttached = true;
}

function ensureDecisionModal() {
  const { modal } = getModalEls();
  if (!modal) {
    console.warn('[modal] Brak #decision-modal w DOM — dodaj parking_modal.html do base.html.');
    return false;
  }
  attachModalListeners();
  return true;
}

function openDecisionModal(payload) {
  if (!ensureDecisionModal()) return;
  const active = getActiveParking();
  if (active && active.started_at) {
    showActiveView();
    const { modal } = getModalEls();
    if (modal) modal.classList.add('open');
    startTimer(active.started_at);
    return;
  }
  showDecisionView();
  setPendingDecision(payload);
  const { modal } = getModalEls();
  modal.classList.add('open');
}

function closeDecisionModal() {
  const { modal } = getModalEls();
  if (modal) modal.classList.remove('open');
  stopTimer();
}

function restoreModalIfPending() {
  const pending = getPendingDecision();
  if (pending) openDecisionModal(pending);
}


window.openDecisionModal = openDecisionModal;

async function initModal() {
  attachModalListeners();
  restoreModalIfPending();

  try {
    const res = await fetch('/api/me/active_reservation', { credentials: 'same-origin' });
    if (res.ok) {
      const j = await res.json();
      if (j.active) {
        setActiveParking({ osm_id: j.osm_id, started_at: j.started_at });
        ensureDecisionModal();
        showActiveView();
        const { modal } = getModalEls();
        if (modal) modal.classList.add('open');
        startTimer(j.started_at);
      } else {
        clearActiveParking();
      }
    }
  } catch (e) {
    console.warn('Nie udało się zsynchronizować aktywnej rezerwacji.', e);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initModal);
} else {
  initModal();
}
