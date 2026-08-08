let all = [];
let tier = null;
let selectedStore = null;
let storeNames = [];

const SIZE_ORDER = new Map(
  ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL', '4XL']
    .map((size, index) => [size, index])
);

const $ = selector => document.querySelector(selector);
const money = value => `HK$${Number(value).toLocaleString()}`;
const escapeHtml = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

function formatUpdated(value) {
  if (!value) return '未有資料';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-HK', {
    timeZone: 'Asia/Hong_Kong',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function stockLabel(skuCount, units, status) {
  if (skuCount == null) return ['待同步', 'unknown'];
  if (Number(skuCount) <= 0) return ['缺貨', 'no'];
  const suffix = status === 'stale' ? ' · 舊快照' : '';
  return [`${skuCount} SKU · ${Number(units || 0)} 件${suffix}`, 'yes'];
}

function sizeSort([left], [right]) {
  const leftKey = String(left).toUpperCase();
  const rightKey = String(right).toUpperCase();
  const leftRank = SIZE_ORDER.get(leftKey) ?? 100;
  const rightRank = SIZE_ORDER.get(rightKey) ?? 100;
  return leftRank - rightRank || leftKey.localeCompare(rightKey, 'en', { numeric: true });
}

function renderSizes(product, storeName) {
  const sizes = Object.entries((product.stockBySize || {})[storeName] || {})
    .filter(([, details]) => Number(details?.units || 0) > 0)
    .sort(sizeSort);
  if (!sizes.length) return '';

  return `<div class="size-list">${sizes.map(([size, details]) => {
    const colours = Number(details?.skuCount || 0);
    const units = Number(details?.units || 0);
    const colourLabel = colours > 0 ? `${colours}色 · ` : '';
    return `<span class="size-pill"><strong>${escapeHtml(size)}</strong><small>${colourLabel}${units}件</small></span>`;
  }).join('')}</div>`;
}

function productHasStock(product) {
  const stock = product.stock || {};
  if (selectedStore) return Number(stock[selectedStore] || 0) > 0;
  return Object.values(stock).some(value => Number(value || 0) > 0);
}

function renderStoreOptions() {
  const select = $('#storeFilter');
  select.innerHTML = '<option value="">全部分店</option>' + storeNames
    .map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
    .join('');
  select.value = selectedStore || '';
}

function render() {
  const query = $('#search').value.trim().toLowerCase();
  const onlyStock = $('#onlyStock').checked;
  const tiers = [...new Set(all.map(product => product.price))].sort((a, b) => a - b);

  $('#tiers').innerHTML =
    `<button class="${tier === null ? 'active' : ''}" data-tier="">全部價格</button>` +
    tiers.map(value => (
      `<button class="${tier === value ? 'active' : ''}" data-tier="${value}">${money(value)}</button>`
    )).join('');

  const rows = all.filter(product => {
    const haystack = `${product.name} ${product.id} ${product.itemNo || ''} ${product.productCode || ''}`.toLowerCase();
    return (!query || haystack.includes(query))
      && (tier === null || product.price === tier)
      && (!onlyStock || productHasStock(product));
  });

  $('#summary').innerHTML = `
    <div><strong>${rows.length}</strong><span>款商品</span></div>
    <div><strong>${tiers.length}</strong><span>個價格階梯</span></div>
    <div><strong>${storeNames.length}</strong><span>間分店</span></div>
    <small>庫存更新 ${formatUpdated(window.stockUpdated || window.updated)}</small>`;

  $('#grid').innerHTML = rows.map(product => {
    const entries = Object.entries(product.stock || {})
      .filter(([name]) => !selectedStore || name === selectedStore);
    const stockHtml = entries.map(([name, skuCount]) => {
      const units = (product.stockUnits || {})[name];
      const [label, className] = stockLabel(skuCount, units, product.stockStatus);
      return `<div class="store-stock">
        <div class="store-line"><span>${escapeHtml(name)}</span><b class="${className}">${label}</b></div>
        ${renderSizes(product, name)}
      </div>`;
    }).join('') || '<div class="store-stock"><div class="store-line"><span>分店庫存</span><b class="unknown">待同步</b></div></div>';

    return `<article class="card">
      <div class="visual">
        ${product.image ? `<img src="${escapeHtml(product.image)}" alt="" loading="lazy">` : '<span>GU</span>'}
        <em>SALE</em>
      </div>
      <div class="body">
        <div class="price"><strong>${money(product.price)}</strong>${product.originalPrice ? `<del>${money(product.originalPrice)}</del>` : ''}</div>
        <h2>${escapeHtml(product.name)}</h2>
        <p class="sku">商品編號 ${escapeHtml(product.id)} · ${Number(product.skuCount || 0)} SKU</p>
        <div class="stock">${stockHtml}</div>
        <a class="product" href="${escapeHtml(product.url)}" target="_blank" rel="noopener">到 GU 核實庫存 ↗</a>
      </div>
    </article>`;
  }).join('');

  $('#empty').hidden = Boolean(rows.length);
  document.querySelectorAll('[data-tier]').forEach(button => {
    button.onclick = () => {
      tier = button.dataset.tier === '' ? null : Number(button.dataset.tier);
      render();
    };
  });
}

fetch('data/products.json', { cache: 'no-store' })
  .then(response => response.json())
  .then(data => {
    all = data.products || [];
    window.updated = data.updatedAt;
    window.stockUpdated = data.stockUpdatedAt;
    storeNames = (data.stores || []).map(store => store.siteName).filter(Boolean);
    if (!storeNames.length) {
      storeNames = [...new Set(all.flatMap(product => Object.keys(product.stock || {})))].sort();
    }
    renderStoreOptions();
    render();
  })
  .catch(() => {
    all = [];
    renderStoreOptions();
    render();
  });

$('#search').addEventListener('input', render);
$('#onlyStock').addEventListener('change', render);
$('#storeFilter').addEventListener('change', event => {
  selectedStore = event.target.value || null;
  render();
});
