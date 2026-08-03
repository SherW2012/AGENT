/* ============================================================
 * 我的美食地图 —— 纯本地个人美食收藏
 * 数据只存在浏览器 localStorage，没有任何外部推荐。
 * ============================================================ */

'use strict';

/* ---------- 常量 ---------- */

const STORAGE_KEY = 'food-map-spots-v1';
const VIEW_KEY = 'food-map-view-v1';

// 预设种类：名称 → { emoji, color }
const CATEGORIES = {
  '火锅':   { emoji: '🍲', color: '#e03131' },
  '烧烤':   { emoji: '🍢', color: '#d9480f' },
  '面食':   { emoji: '🍜', color: '#f08c00' },
  '中餐':   { emoji: '🍚', color: '#e8590c' },
  '日料':   { emoji: '🍣', color: '#1971c2' },
  '西餐':   { emoji: '🍝', color: '#6741d9' },
  '甜点':   { emoji: '🍰', color: '#d6336c' },
  '饮品':   { emoji: '☕', color: '#795548' },
  '小吃':   { emoji: '🥟', color: '#2f9e44' },
  '其他':   { emoji: '🍽️', color: '#868e96' },
};
const DEFAULT_CATEGORY = '其他';

// 默认地图中心（北京），首次打开且未定位时使用
const DEFAULT_CENTER = [39.909, 116.397];
const DEFAULT_ZOOM = 12;

/* ---------- 状态 ---------- */

let spots = loadSpots();          // [{id,name,category,rating,price,notes,lat,lng,createdAt,updatedAt}]
let editingId = null;             // 正在编辑的 spot id；null 表示新增
let pendingLatLng = null;         // 新增时点击地图选中的坐标
let tempMarker = null;            // 新增时的临时标记
let selectedCategory = DEFAULT_CATEGORY;
let selectedRating = 0;
let activeTab = 'list';

const markerById = new Map();

/* ---------- 存储 ---------- */

function loadSpots() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter(s => s && s.id && isFinite(s.lat) && isFinite(s.lng)) : [];
  } catch (e) {
    console.warn('读取本地数据失败', e);
    return [];
  }
}

function saveSpots() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(spots));
}

function saveView() {
  const c = map.getCenter();
  localStorage.setItem(VIEW_KEY, JSON.stringify({ lat: c.lat, lng: c.lng, zoom: map.getZoom() }));
}

function loadView() {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY));
    if (v && isFinite(v.lat) && isFinite(v.lng) && isFinite(v.zoom)) return v;
  } catch (e) { /* ignore */ }
  return null;
}

/* ---------- 工具 ---------- */

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

function catInfo(name) {
  return CATEGORIES[name] || { emoji: '🍽️', color: '#868e96' };
}

function starsText(n) {
  return '★'.repeat(n) + '☆'.repeat(5 - n);
}

/* WGS-84 → GCJ-02（高德底图坐标系），仅用于浏览器定位纠偏 */
function wgs2gcj(lat, lng) {
  const a = 6378245.0, ee = 0.00669342162296594323;
  if (lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271) return [lat, lng]; // 境外不偏移
  const transLat = (x, y) => {
    let r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    r += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3;
    r += (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
    return r;
  };
  const transLng = (x, y) => {
    let r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    r += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3;
    r += (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
    return r;
  };
  let dLat = transLat(lng - 105.0, lat - 35.0);
  let dLng = transLng(lng - 105.0, lat - 35.0);
  const radLat = lat / 180.0 * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - ee * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
  dLng = (dLng * 180.0) / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
  return [lat + dLat, lng + dLng];
}

/* ---------- 地图 ---------- */

const savedView = loadView();
const map = L.map('map', { zoomControl: true })
  .setView(savedView ? [savedView.lat, savedView.lng] : DEFAULT_CENTER,
           savedView ? savedView.zoom : DEFAULT_ZOOM);

L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', {
  subdomains: ['1', '2', '3', '4'],
  maxZoom: 18,
  attribution: '&copy; 高德地图',
}).addTo(map);

map.on('moveend', saveView);

const markerLayer = L.layerGroup().addTo(map);

function makeIcon(spot) {
  const info = catInfo(spot.category);
  return L.divIcon({
    className: '',
    html: `<div class="food-marker" style="width:34px;height:34px;border-color:${info.color}">${info.emoji}</div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 32],
    popupAnchor: [0, -30],
  });
}

function popupHtml(spot) {
  const info = catInfo(spot.category);
  return `
    <div class="popup-content">
      <div class="p-name">${info.emoji} ${escapeHtml(spot.name)}</div>
      <div class="p-meta">${escapeHtml(spot.category)}${spot.price ? ` · 人均 ¥${escapeHtml(spot.price)}` : ''}</div>
      <div class="p-stars">${starsText(spot.rating)}</div>
      ${spot.notes ? `<div class="p-notes">${escapeHtml(spot.notes)}</div>` : ''}
      <div class="p-actions">
        <button class="btn btn-ghost" onclick="window.__editSpot('${spot.id}')">✏️ 编辑</button>
        <button class="btn btn-danger" onclick="window.__deleteSpot('${spot.id}')">🗑 删除</button>
      </div>
    </div>`;
}

function renderMarkers() {
  markerLayer.clearLayers();
  markerById.clear();
  for (const spot of filteredSpots()) {
    const m = L.marker([spot.lat, spot.lng], { icon: makeIcon(spot) })
      .bindPopup(popupHtml(spot));
    m.addTo(markerLayer);
    markerById.set(spot.id, m);
  }
}

/* ---------- 筛选 ---------- */

const elKeyword = document.getElementById('filter-keyword');
const elFilterCat = document.getElementById('filter-category');
const elFilterRating = document.getElementById('filter-rating');

function allCategories() {
  const set = new Set(Object.keys(CATEGORIES));
  for (const s of spots) set.add(s.category);
  return [...set];
}

function refreshCategoryFilter() {
  const cur = elFilterCat.value;
  elFilterCat.innerHTML = '<option value="">全部种类</option>' +
    allCategories().map(c => `<option value="${escapeHtml(c)}">${catInfo(c).emoji} ${escapeHtml(c)}</option>`).join('');
  if ([...elFilterCat.options].some(o => o.value === cur)) elFilterCat.value = cur;
}

function filteredSpots() {
  const kw = elKeyword.value.trim().toLowerCase();
  const cat = elFilterCat.value;
  const minRating = Number(elFilterRating.value) || 0;
  return spots.filter(s => {
    if (cat && s.category !== cat) return false;
    if (s.rating < minRating) return false;
    if (kw && !(s.name.toLowerCase().includes(kw) || (s.notes || '').toLowerCase().includes(kw))) return false;
    return true;
  });
}

[elKeyword, elFilterCat, elFilterRating].forEach(el =>
  el.addEventListener('input', renderAll));

/* ---------- 列表 & 排行榜 ---------- */

function spotCardHtml(spot, rankBadge) {
  const info = catInfo(spot.category);
  return `
    <div class="spot-card" data-id="${spot.id}">
      ${rankBadge !== undefined ? `<div class="rank-badge">${rankBadge}</div>` : ''}
      <div class="emoji" style="background:${info.color}18">${info.emoji}</div>
      <div class="info">
        <div class="name">${escapeHtml(spot.name)}</div>
        <div class="meta">
          <span class="stars">${starsText(spot.rating)}</span>
          <span>${escapeHtml(spot.category)}</span>
          ${spot.price ? `<span>¥${escapeHtml(spot.price)}/人</span>` : ''}
        </div>
        ${spot.notes ? `<div class="notes">${escapeHtml(spot.notes)}</div>` : ''}
      </div>
    </div>`;
}

function renderList() {
  const el = document.getElementById('spot-list');
  const list = filteredSpots().slice().sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  el.innerHTML = list.length
    ? list.map(s => spotCardHtml(s)).join('')
    : `<div class="empty-tip">还没有记录～<br>点击地图任意位置，添加第一家好吃的店 🍜</div>`;
}

const MEDALS = ['🥇', '🥈', '🥉'];

function renderRank() {
  const el = document.getElementById('rank-list');
  const list = filteredSpots().slice().sort((a, b) =>
    b.rating - a.rating || (b.updatedAt || 0) - (a.updatedAt || 0));
  el.innerHTML = list.length
    ? list.map((s, i) => spotCardHtml(s, MEDALS[i] || i + 1)).join('')
    : `<div class="empty-tip">暂无上榜店铺<br>先去地图上添加几家吧！</div>`;
}

/* ---------- 统计 ---------- */

function renderStats() {
  const el = document.getElementById('stats-content');
  if (!spots.length) {
    el.innerHTML = `<div class="empty-tip">暂无数据</div>`;
    return;
  }
  const total = spots.length;
  const avg = (spots.reduce((s, x) => s + x.rating, 0) / total).toFixed(1);
  const five = spots.filter(s => s.rating === 5).length;

  const counts = {};
  for (const s of spots) counts[s.category] = (counts[s.category] || 0) + 1;
  const maxCount = Math.max(...Object.values(counts));
  const rows = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([cat, n]) => `
      <div class="stat-cat-row">
        <span class="cat-name">${catInfo(cat).emoji} ${escapeHtml(cat)}</span>
        <div class="bar-wrap"><div class="bar" style="width:${(n / maxCount * 100).toFixed(0)}%;background:${catInfo(cat).color}"></div></div>
        <span class="count">${n}</span>
      </div>`).join('');

  el.innerHTML = `
    <div class="stat-summary">
      <div class="stat-box"><div class="num">${total}</div><div class="label">总店数</div></div>
      <div class="stat-box"><div class="num">${avg}</div><div class="label">平均分</div></div>
      <div class="stat-box"><div class="num">${five}</div><div class="label">五星店</div></div>
    </div>
    ${rows}`;
}

/* ---------- 标签页 ---------- */

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    activeTab = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.tab-panel').forEach(p =>
      p.classList.toggle('active', p.id === 'panel-' + activeTab));
    renderAll();
  });
});

/* 点击卡片 → 飞到对应标记 */
document.getElementById('sidebar').addEventListener('click', e => {
  const card = e.target.closest('.spot-card');
  if (!card) return;
  const spot = spots.find(s => s.id === card.dataset.id);
  if (!spot) return;
  map.flyTo([spot.lat, spot.lng], Math.max(map.getZoom(), 15), { duration: 0.6 });
  const m = markerById.get(spot.id);
  if (m) setTimeout(() => m.openPopup(), 650);
  if (window.innerWidth <= 720) sidebar.classList.add('collapsed');
});

/* ---------- 弹窗表单 ---------- */

const modalMask = document.getElementById('modal-mask');
const form = document.getElementById('spot-form');
const fName = document.getElementById('f-name');
const fPrice = document.getElementById('f-price');
const fNotes = document.getElementById('f-notes');
const fCatCustom = document.getElementById('f-category-custom');
const catPicker = document.getElementById('f-category-picker');
const starInput = document.getElementById('f-stars');

function renderCategoryPicker() {
  catPicker.innerHTML = Object.keys(CATEGORIES).map(c =>
    `<button type="button" class="cat-chip${c === selectedCategory ? ' selected' : ''}" data-cat="${escapeHtml(c)}">${CATEGORIES[c].emoji} ${escapeHtml(c)}</button>`
  ).join('');
}

catPicker.addEventListener('click', e => {
  const chip = e.target.closest('.cat-chip');
  if (!chip) return;
  selectedCategory = chip.dataset.cat;
  fCatCustom.value = '';
  renderCategoryPicker();
});

fCatCustom.addEventListener('input', () => {
  if (fCatCustom.value.trim()) {
    selectedCategory = '';
    renderCategoryPicker();
  }
});

function renderStars() {
  starInput.querySelectorAll('span').forEach(s =>
    s.classList.toggle('on', Number(s.dataset.v) <= selectedRating));
}

starInput.addEventListener('click', e => {
  const v = Number(e.target.dataset.v);
  if (v) { selectedRating = v; renderStars(); }
});

function openModal(spot) {
  editingId = spot ? spot.id : null;
  document.getElementById('modal-title').textContent = spot ? '编辑美食' : '添加美食';
  fName.value = spot ? spot.name : '';
  fPrice.value = spot && spot.price ? spot.price : '';
  fNotes.value = spot ? (spot.notes || '') : '';
  if (spot && !CATEGORIES[spot.category]) {
    selectedCategory = '';
    fCatCustom.value = spot.category;
  } else {
    selectedCategory = spot ? spot.category : DEFAULT_CATEGORY;
    fCatCustom.value = '';
  }
  selectedRating = spot ? spot.rating : 0;
  renderCategoryPicker();
  renderStars();
  modalMask.classList.remove('hidden');
  setTimeout(() => fName.focus(), 50);
}

function closeModal() {
  modalMask.classList.add('hidden');
  editingId = null;
  pendingLatLng = null;
  if (tempMarker) { map.removeLayer(tempMarker); tempMarker = null; }
}

document.getElementById('btn-cancel').addEventListener('click', closeModal);
modalMask.addEventListener('click', e => { if (e.target === modalMask) closeModal(); });

form.addEventListener('submit', e => {
  e.preventDefault();
  const name = fName.value.trim();
  if (!name) { fName.focus(); return; }
  if (!selectedRating) { alert('请点星星打个分～'); return; }
  const category = fCatCustom.value.trim() || selectedCategory || DEFAULT_CATEGORY;
  const price = fPrice.value ? Number(fPrice.value) : null;
  const notes = fNotes.value.trim();
  const now = Date.now();

  if (editingId) {
    const spot = spots.find(s => s.id === editingId);
    if (spot) Object.assign(spot, { name, category, rating: selectedRating, price, notes, updatedAt: now });
  } else {
    if (!pendingLatLng) return;
    spots.push({
      id: uid(),
      name, category,
      rating: selectedRating,
      price, notes,
      lat: pendingLatLng.lat,
      lng: pendingLatLng.lng,
      createdAt: now,
      updatedAt: now,
    });
  }
  saveSpots();
  closeModal();
  refreshCategoryFilter();
  renderAll();
});

/* ---------- 地图交互：点击添加 ---------- */

map.on('click', e => {
  if (!modalMask.classList.contains('hidden')) return;
  pendingLatLng = e.latlng;
  if (tempMarker) map.removeLayer(tempMarker);
  tempMarker = L.marker(e.latlng, {
    icon: L.divIcon({
      className: '',
      html: `<div class="food-marker" style="width:34px;height:34px;border-color:#888">📌</div>`,
      iconSize: [34, 34],
      iconAnchor: [17, 32],
    }),
  }).addTo(map);
  openModal(null);
});

/* 弹窗里的编辑 / 删除（由 popup 内联按钮调用） */
window.__editSpot = id => {
  const spot = spots.find(s => s.id === id);
  if (spot) { map.closePopup(); openModal(spot); }
};

window.__deleteSpot = id => {
  const spot = spots.find(s => s.id === id);
  if (!spot) return;
  if (!confirm(`确定删除「${spot.name}」吗？`)) return;
  spots = spots.filter(s => s.id !== id);
  saveSpots();
  map.closePopup();
  refreshCategoryFilter();
  renderAll();
};

/* ---------- 定位 ---------- */

document.getElementById('btn-locate').addEventListener('click', () => {
  if (!navigator.geolocation) { alert('当前浏览器不支持定位'); return; }
  navigator.geolocation.getCurrentPosition(
    pos => {
      const [lat, lng] = wgs2gcj(pos.coords.latitude, pos.coords.longitude);
      map.flyTo([lat, lng], 15, { duration: 0.8 });
    },
    () => alert('定位失败，请检查浏览器定位权限'),
    { enableHighAccuracy: true, timeout: 8000 },
  );
});

/* ---------- 导出 / 导入 ---------- */

document.getElementById('btn-export').addEventListener('click', () => {
  const blob = new Blob(
    [JSON.stringify({ app: 'food-map', version: 1, exportedAt: new Date().toISOString(), spots }, null, 2)],
    { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `美食地图备份-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
});

const importFile = document.getElementById('import-file');
document.getElementById('btn-import').addEventListener('click', () => importFile.click());
importFile.addEventListener('change', () => {
  const file = importFile.files[0];
  importFile.value = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      const incoming = Array.isArray(data) ? data : data.spots;
      if (!Array.isArray(incoming)) throw new Error('格式不对');
      const valid = incoming.filter(s => s && s.name && isFinite(s.lat) && isFinite(s.lng));
      if (!valid.length) { alert('文件里没有有效的店铺数据'); return; }
      const mode = spots.length
        ? confirm(`导入 ${valid.length} 家店。\n「确定」= 合并到现有数据\n「取消」= 覆盖现有数据`)
        : false;
      if (mode) {
        const existing = new Set(spots.map(s => s.id));
        for (const s of valid) {
          if (existing.has(s.id)) continue;
          spots.push({ ...s, id: s.id || uid(), rating: Math.min(5, Math.max(1, Number(s.rating) || 3)) });
        }
      } else {
        spots = valid.map(s => ({ ...s, id: s.id || uid(), rating: Math.min(5, Math.max(1, Number(s.rating) || 3)) }));
      }
      saveSpots();
      refreshCategoryFilter();
      renderAll();
      alert('导入成功！');
    } catch (err) {
      alert('导入失败：不是有效的美食地图备份文件');
    }
  };
  reader.readAsText(file);
});

/* ---------- 侧栏开关 ---------- */

const sidebar = document.getElementById('sidebar');
document.getElementById('btn-toggle-sidebar').addEventListener('click', () => {
  sidebar.classList.toggle('collapsed');
  setTimeout(() => map.invalidateSize(), 50);
});
if (window.innerWidth <= 720) sidebar.classList.add('collapsed');

/* ---------- 总渲染 ---------- */

function renderAll() {
  renderMarkers();
  if (activeTab === 'list') renderList();
  else if (activeTab === 'rank') renderRank();
  else renderStats();
  document.getElementById('add-hint').style.display = spots.length ? 'none' : '';
}

refreshCategoryFilter();
renderAll();

/* 首次有数据时，把视野对准所有标记 */
if (!savedView && spots.length) {
  const bounds = L.latLngBounds(spots.map(s => [s.lat, s.lng]));
  map.fitBounds(bounds.pad(0.2));
}
