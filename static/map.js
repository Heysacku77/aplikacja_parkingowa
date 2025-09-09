const mapEl = document.getElementById('map');
if (!mapEl) {
} else {
  const dataEl =
    document.getElementById('search-data') ||
    document.getElementById('home-data');

  let INPUT = { lat: 50.06143, lon: 19.93658, radius: 300 };
  if (dataEl) {
    try {
      const parsed = JSON.parse(dataEl.textContent || dataEl.innerText || '{}');
      if (typeof parsed.lat === 'number' && typeof parsed.lon === 'number') {
        INPUT.lat = parsed.lat;
        INPUT.lon = parsed.lon;
      }
      if (typeof parsed.radius === 'number') {
        INPUT.radius = parsed.radius;
      }
    } catch (e) {
      console.warn('map.js: nie udało się sparsować danych JSON – używam domyślnych.', e);
    }
  }

  const CENTER = [INPUT.lat, INPUT.lon];
  let RADIUS = INPUT.radius || 300;
  let ONLY_PUBLIC = false;

  function accessLabel(item) {
    switch (item.access_class) {
      case 'public': return 'Publiczny';
      case 'restricted': return 'Ograniczony dostęp';
      case 'private': return 'Prywatny';
      default: return 'Brak informacji';
    }
  }
  function feeLabel(item) {
    switch (item.fee) {
      case 'paid': return 'Płatny';
      case 'free': return 'Bezpłatny';
      default: return 'Brak informacji';
    }
  }
  function markerColor(item) {
    switch (item.access_class) {
      case 'public': return 'green';
      case 'restricted': return 'orange';
      case 'private': return 'red';
      default: return 'gray';
    }
  }
  function makeCircleMarker(lat, lon, color) {
    return L.circleMarker([lat, lon], {
      radius: 7, weight: 2, color: color, fillColor: color, fillOpacity: 0.6
    });
  }

  const map = L.map('map').setView(CENTER, 16);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 20, attribution: '&copy; OpenStreetMap'
  }).addTo(map);


  const layerGroup = L.layerGroup().addTo(map);
  const Control = L.Control.extend({
    onAdd: function() {
      const div = L.DomUtil.create('div', 'leaflet-bar');
      div.style.background = 'white';
      div.style.padding = '8px';
      div.style.borderRadius = '8px';
      div.style.boxShadow = '0 2px 10px rgba(0,0,0,.15)';
      div.style.userSelect = 'none';
      div.innerHTML = `
        <label style="display:flex;gap:6px;align-items:center;">
          <input id="onlyPublic" type="checkbox" />
          <span>Tylko publiczne</span>
        </label>
        <div style="margin-top:6px;font-size:12px;">Promień: <span id="rval">${RADIUS}</span> m</div>
        <input id="rslider" type="range" min="100" max="1000" step="50" value="${RADIUS}" style="width:180px;">
        <div style="margin-top:6px;font-size:12px;color:#555">
          Legenda: <span style="color:green">● publiczny</span>
          <span style="color:orange">● ograniczony</span>
          <span style="color:red">● prywatny</span>
          <span style="color:gray">● brak info</span>
        </div>
      `;
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      return div;
    }
  });

  map.addControl(new Control({ position: 'topright' }));

  const onlyPublicEl = document.getElementById('onlyPublic');
  const rsliderEl = document.getElementById('rslider');
  const rvalEl = document.getElementById('rval');

  if (onlyPublicEl) {
    onlyPublicEl.addEventListener('change', () => {
      ONLY_PUBLIC = onlyPublicEl.checked;
      loadParkings();
    });
  }
  if (rsliderEl && rvalEl) {
    rsliderEl.addEventListener('input', () => {
      RADIUS = parseInt(rsliderEl.value, 10);
      rvalEl.textContent = RADIUS;
    });
    rsliderEl.addEventListener('change', loadParkings);
  }

  async function loadParkings() {
    layerGroup.clearLayers();
    const url = new URL('/api/parkings', window.location.origin);
    url.searchParams.set('lat', CENTER[0]);
    url.searchParams.set('lon', CENTER[1]);
    url.searchParams.set('radius', RADIUS);
    if (ONLY_PUBLIC) url.searchParams.set('only_public', '1');

    const res = await fetch(url.toString(), { credentials: 'same-origin' });
    if (!res.ok) return;

    const json = await res.json();
    (json.items || []).forEach(item => {
      const m = makeCircleMarker(item.lat, item.lon, markerColor(item)).addTo(layerGroup);
      const gmaps = `https://www.google.com/maps/dir/?api=1&destination=${item.lat},${item.lon}`;
      m.bindPopup(`
        <div class="popup">
          <h4>${item.name || 'Parking'}</h4>
          <div>Rodzaj parkingu: <strong>${accessLabel(item)}</strong></div>
          <div>Opłaty: <strong>${feeLabel(item)}</strong></div>
          ${item.capacity ? `<div>Pojemność: ${item.capacity}</div>` : ''}
          ${item.operator ? `<div>Operator: ${item.operator}</div>` : ''}
          <div>Zajętość: <strong>${(item.percent_occupied ?? 0)}%</strong></div>
          <div style="margin-top:8px;">
            <a href="${gmaps}" class="gmaps-link" data-osm="${item.id}" data-lat="${item.lat}" data-lon="${item.lon}">Prowadź do celu</a>
          </div>
        </div>
      `);
    });

    layerGroup.eachLayer(layer => {
      layer.on('popupopen', (e) => {
        const link = e.popup._contentNode.querySelector('.gmaps-link');
        if (!link) return;
        link.addEventListener('click', (evt) => {
          evt.preventDefault();
          const osm = link.getAttribute('data-osm');
          const lat = link.getAttribute('data-lat');
          const lon = link.getAttribute('data-lon');
          const gmaps = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
          window.open(gmaps, '_blank', 'noopener');
          if (typeof window.openDecisionModal === 'function') {
            window.openDecisionModal({ osm, lat, lon, gmaps });
          } else {
            console.warn('modal.js nie został podłączony!');
          }
        }, { once: true });
      });
    });
  }

  let pollId = null;
  function startPolling(intervalMs = 20000){
    if (pollId) return;
    pollId = setInterval(loadParkings, intervalMs);
  }
  function stopPolling(){
    if (!pollId) return;
    clearInterval(pollId);
    pollId = null;
  }

  // 7) Start
  loadParkings();
  startPolling(20000);
}
