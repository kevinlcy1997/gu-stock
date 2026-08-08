let all = [];
let tier = null;
let selectedStore = null;
let storeNames = [];
const selectedColors = new Map();

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
    const colorEntries = Object.entries(details?.colors || {})
      .filter(([, colorUnits]) => Number(colorUnits || 0) > 0)
      .sort(([left], [right]) => String(left).localeCompare(String(right), 'en', { numeric: true }));
    const colours = colorEntries.length || Number(details?.skuCount || 0);
    const units = Number(details?.units || 0);
    const colourLabel = colours > 0 ? `${colours}色 · ` : '';
    const colorHtml = colorEntries.length
      ? `<div class="color-list">${colorEntries.map(([color, colorUnits]) => (
        `<span class="color-stock"><span>${escapeHtml(color)}</span><b>${Number(colorUnits)}件</b></span>`
      )).join('')}</div>`
      : '';
    return `<div class="size-group">
      <div class="size-head"><strong>${escapeHtml(size)}</strong><small>${colourLabel}${units}件</small></div>
      ${colorHtml}
    </div>`;
  }).join('')}</div>`;
}

function productColorState(product) {
  const productKey = String(product.productCode || product.id);
  const colorImages = Object.entries(product.colorImages || {})
    .filter(([color, image]) => color && image)
    .sort(([left], [right]) => String(left).localeCompare(String(right), 'en', { numeric: true }));
  const savedColor = selectedColors.get(productKey);
  const activeColor = colorImages.some(([color]) => color === savedColor)
    ? savedColor
    : (colorImages[0]?.[0] || null);
  const activeImage = colorImages.find(([color]) => color === activeColor)?.[1]
    || product.image;
  if (activeColor) selectedColors.set(productKey, activeColor);
  return { productKey, colorImages, activeColor, activeImage };
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
    const { productKey, colorImages, activeColor, activeImage } = productColorState(product);
    const colorSwitchHtml = colorImages.length ? `<div class="image-colors" aria-label="選擇商品顏色">
      ${colorImages.map(([color, image]) => `<button type="button"
        class="${color === activeColor ? 'active' : ''}"
        data-color-product="${escapeHtml(productKey)}"
        data-color="${escapeHtml(color)}"
        data-image="${escapeHtml(image)}"
        aria-pressed="${color === activeColor}">${escapeHtml(color)}</button>`).join('')}
    </div>` : '';
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
        ${activeImage ? `<img src="${escapeHtml(activeImage)}" alt="${escapeHtml(product.name)}${activeColor ? ` - ${escapeHtml(activeColor)}` : ''}" loading="lazy" data-product-image data-product-name="${escapeHtml(product.name)}">` : '<span>GU</span>'}
        <em>SALE</em>
      </div>
      ${colorSwitchHtml}
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
  document.querySelectorAll('[data-color-product]').forEach(button => {
    button.onclick = () => {
      const card = button.closest('.card');
      const image = card?.querySelector('[data-product-image]');
      const productKey = button.dataset.colorProduct;
      const color = button.dataset.color;
      if (!image || !productKey || !color || !button.dataset.image) return;
      selectedColors.set(productKey, color);
      image.src = button.dataset.image;
      image.alt = `${image.dataset.productName || ''} - ${color}`;
      card.querySelectorAll('[data-color-product]').forEach(option => {
        const active = option === button;
        option.classList.toggle('active', active);
        option.setAttribute('aria-pressed', String(active));
      });
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
