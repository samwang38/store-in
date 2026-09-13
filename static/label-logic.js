// label-logic.js
// 標籤解析邏輯 — 移植自 samfor-work.github.io/work/label.html
// 請勿自行修改解析邏輯；如需更新請對照原始 label.html 同步。
//
// 下面的 LABEL_OVERRIDES 是「設定模式」的覆寫層，疊在解析結果之上，
// 不算解析邏輯的一部分：內建對照表（進 git、全門市一致）永遠是底，
// 覆寫層為空時行為與沒有設定模式時完全相同。

// 由設定模式載入；每張表都是 { 來源字串: 顯示字串 }。
// iphoneColors / enColors 在「解析當中」補英文色名的中文；
// products / fields 在「解析之後」對輸出欄位做整值取代。
let LABEL_OVERRIDES = { iphoneColors: {}, enColors: {}, products: {}, fields: {} };

// 覆寫層的值是空字串＝「停用這筆內建對照」，與「沒有這筆設定」不同：
// 前者會略過內建值、印回原字，後者才往下查內建表。所以一律用 hasOwnProperty 判斷，
// 不能用真假值，否則空字串會被當成沒設定。
function hasOverride(map, key) {
  return Object.prototype.hasOwnProperty.call(map, key);
}

function setLabelOverrides(source) {
  const pick = (key) => (source && typeof source[key] === 'object' && source[key]) || {};
  LABEL_OVERRIDES = {
    iphoneColors: pick('iphoneColors'),
    enColors: pick('enColors'),
    products: pick('products'),
    fields: pick('fields'),
  };
}

function getLabelOverrides() {
  return LABEL_OVERRIDES;
}

const COLOR_MAP = {
  'MDN':'午夜色','SKY':'星光色','STL':'銀色','SL':'銀色','SB':'太空黑',
  'BLK':'黑色','WHT':'白色','RED':'紅色','GRN':'綠色','BLU':'藍色',
  'PNK':'粉色','YLW':'黃色','ORG':'橙色','PRP':'紫色','PUR':'紫色',
  'PRE':'紫色','GLD':'金色','RGD':'玫瑰金','GRY':'灰色',
  'SPG':'太空灰','SGR':'太空灰',
};

const EN_COLOR_MAP = {
  'SILVER':'銀色','SILVER-TWN':'銀色',
  'SPACE GRAY':'太空灰','SPACE GREY':'太空灰',
  'BLACK':'黑色','WHITE':'白色','RED':'紅色',
  'PINK':'粉色','BLUE':'藍色','GREEN':'綠色',
  'YELLOW':'黃色','PURPLE':'紫色','ORANGE':'橙色',
  'STARLIGHT':'星光色','MIDNIGHT':'午夜色',
  'GOLD':'金色','ROSE GOLD':'玫瑰金',
  'TEAL':'藍綠色','ULTRAMARINE':'群青色',
  'NATURAL TITANIUM':'原色鈦','BLACK TITANIUM':'黑色鈦',
  'WHITE TITANIUM':'白色鈦','DESERT TITANIUM':'沙漠色鈦',
  'DEEP BLUE':'深藍色','DESERT':'沙漠色',
};

const IPHONE_COLOR_MAP = {
  'SILVER': '銀色',
  'COSMIC ORANGE': '橙色',
  'DEEP BLUE': '藏藍色',
  'BLACK': '黑色',
  'WHITE': '白色',
  'PINK': '粉色',
  'TEAL': '藍綠色',
  'ULTRAMARINE': '群青色',
  'DESERT': '沙漠色',
  'RED': '紅色',
  'BLUE': '藍色',
  'GREEN': '綠色',
  'YELLOW': '黃色',
  'PURPLE': '紫色',
  'NATURAL TITANIUM': '原色鈦',
  'BLACK TITANIUM': '黑色鈦',
  'WHITE TITANIUM': '白色鈦',
  'DESERT TITANIUM': '沙漠色鈦',
  'ROSE GOLD': '玫瑰金',
  'GOLD': '金色',
  'SOFT PINK': '粉色',
  'LAVENDER': '薰衣草紫',
  'SAGE': '鼠尾草綠',
  'MIST BLUE': '青霧藍',
  'BURGUNDY': '紅色',
  'GLACIER': '藍色',
  'STAR WHITE': '星光白',
  'NIGHT SKY': '夜空色',
};

function enColorToChinese(colorStr) {
  const upper = colorStr.toUpperCase().replace(/-TWN$/i, '').trim();
  const ov = LABEL_OVERRIDES.enColors;
  if (hasOverride(ov, upper)) return ov[upper] || colorStr;
  if (EN_COLOR_MAP[upper]) return EN_COLOR_MAP[upper];
  const firstWord = upper.split(' ')[0];
  if (hasOverride(ov, firstWord)) return ov[firstWord] || colorStr;
  // 補充：3 字母縮寫（如 STL/BLU/SPG）也查 COLOR_MAP
  return EN_COLOR_MAP[firstWord] || COLOR_MAP[upper] || COLOR_MAP[firstWord] || colorStr;
}

function iphoneColorToChinese(colorStr) {
  const upper = colorStr.toUpperCase().trim();
  const ov = LABEL_OVERRIDES.iphoneColors;
  if (hasOverride(ov, upper)) return ov[upper] || colorStr;
  if (IPHONE_COLOR_MAP[upper]) return IPHONE_COLOR_MAP[upper];
  const firstWord = upper.split(' ')[0];
  if (hasOverride(ov, firstWord)) return ov[firstWord] || colorStr;
  return IPHONE_COLOR_MAP[firstWord] || colorStr;
}

function parseiPhone(partCode, name) {
  const prodMatch = name.match(/iPhone\s+(Duo|\d+\w*(?:\s+(?:Pro\s+Max|Pro|Plus|mini))?)/i);
  const product = prodMatch ? prodMatch[1].trim() : 'iPhone';
  const storageMatch = name.match(/(\d+(?:GB|TB))/i);
  const storage = storageMatch ? storageMatch[1] : '';
  let colorFull = '';
  if (prodMatch && storageMatch) {
    const between = name.substring(prodMatch.index + prodMatch[0].length, storageMatch.index).trim();
    if (between) {
      colorFull = between;
    } else {
      const afterStorage = name.substring(storageMatch.index + storageMatch[0].length).trim();
      colorFull = afterStorage.replace(/\s+A\d+.*$/i, '').trim();
    }
  }
  const color = iphoneColorToChinese(colorFull);
  const sku = partCode.substring(2, 5);
  return { product, right1: storage, color, right2: sku, type: 'iphone' };
}

function parseWatch(partCode, name) {
  const seriesMatch = name.match(/Apple Watch (S\w+|SE\w*|Ultra\w*)/i);
  const series = seriesMatch ? seriesMatch[1] : '';
  const sizeMatch = name.match(/(\d+)mm/);
  const sizeMm = sizeMatch ? sizeMatch[1] : '';
  const product = (series && sizeMm) ? `${series} ${sizeMm}` : 'Apple Watch';
  const sku = partCode.substring(2, 5);
  const colorMatch = name.match(/(\S+?)(?:鋁金屬錶殼|不鏽鋼錶殼|鈦金屬錶殼|陶瓷錶殼)/);
  const color = colorMatch ? colorMatch[1] : '';
  const bandMatch = name.match(/-\s*([A-Z]\/[A-Z]|[A-Z]{1,2})$/);
  const band = bandMatch ? bandMatch[1] : '';
  // 連線版要印在標籤上（價格與功能都不同）。GPS 是基本款，不標。
  // cellular 只是旗標，實際接到錶殼色後面是在 applyLabelOverrides 做的——
  // 這樣 fields 的整值覆寫（例如「深古銅色 → 古銅」）才對得到。
  const cellular = /Apple Watch \S+\s+CEL\b/i.test(name);
  // 四格與 iPhone 對齊：左上 SKU、右上 型號尺寸、左下 錶殼色、右下 錶帶尺寸
  return { product, right1: band, color, right2: sku, type: 'watch', cellular };
}

function parseiPad(partCode, name) {
  let product;
  const variantMatch = name.match(/iPad\s+(Air|Pro|mini)\s+(\d+(?:\.\d+)?)/i);
  const isPro = variantMatch && variantMatch[1].toLowerCase() === 'pro';
  if (variantMatch) {
    product = variantMatch[1] + ' ' + variantMatch[2];
  } else {
    const numMatch = name.match(/iPad\s+(\d+(?:\.\d+)?)/i);
    product = numMatch ? 'iPad ' + numMatch[1] : 'iPad';
  }
  const storageMatches = name.match(/(\d+(?:GB|TB))/g);
  const storage = storageMatches ? storageMatches[storageMatches.length - 1] : '';
  let color = '';
  for (const p of name.split('/')) {
    const key = p.trim();
    // 覆寫層要優先於內建表，而且管理員新增的縮寫也要認得出來：
    // iPad 常見的 `128GB/SPG` 格式若只查 COLOR_MAP，設定功能對它完全無效。
    if (hasOverride(LABEL_OVERRIDES.enColors, key.toUpperCase()) || COLOR_MAP[key]) {
      color = isPro ? key : enColorToChinese(key);
      break;
    }
  }
  if (!color) {
    const storageMatch = name.match(/(\d+(?:GB|TB))/i);
    if (storageMatch) {
      const after = name.substring(name.indexOf(storageMatch[0]) + storageMatch[0].length).trim();
      const colorRaw = after.replace(/-TWN.*$/i, '').trim();
      if (colorRaw) {
        const isChinese = /[一-鿿]/.test(colorRaw);
        if (isChinese) {
          color = colorRaw;
        } else {
          color = isPro ? colorRaw : enColorToChinese(colorRaw);
        }
      }
    }
  }
  const sku = partCode.substring(2, 5);
  return { product, right1: storage, color, right2: sku, type: 'ipad', keepEnglish: !!isPro };
}

function parseMac(partCode, name) {
  const parts = name.split(' ');
  const rest = parts.slice(1).join(' ');
  const restParts = rest.split('/');
  const product = restParts[0].trim();
  const storageMatches = rest.match(/(\d+(?:GB|TB))/g);
  const storage = storageMatches ? storageMatches[storageMatches.length - 1] : '';
  let color = '';
  for (const p of restParts) {
    const key = p.trim();
    if (hasOverride(LABEL_OVERRIDES.enColors, key.toUpperCase()) || COLOR_MAP[key]) {
      color = enColorToChinese(key);
      break;
    }
  }
  const sku = partCode.substring(2, 5);
  return { product, right1: storage, color, right2: sku, type: 'mac' };
}

function parseProductRaw(fullName) {
  const parts = fullName.trim().split(' ');
  const partCode = parts[0];
  const name = parts.slice(1).join(' ');
  if (/Apple Watch/i.test(name)) return parseWatch(partCode, name);
  if (/^iPhone/i.test(name))     return parseiPhone(partCode, name);
  if (/^iPad/i.test(name))       return parseiPad(partCode, name);
  return parseMac(partCode, name);
}

// 解析後的整值取代：品名走 products，其餘顯示欄位走 fields。
function applyLabelOverrides(parsed) {
  const { products, fields } = LABEL_OVERRIDES;
  // 空字串（停用）在這裡等於「不覆寫」，維持解析出來的原值。
  if (products[parsed.product]) parsed.product = products[parsed.product];
  for (const key of ['color', 'right1', 'right2']) {
    const current = parsed[key];
    if (current && fields[current]) parsed[key] = fields[current];
  }
  // CEL 在覆寫之後才接上：否則 color 變成「深古銅色 CEL」，
  // fields 設的「深古銅色 → 古銅」就整值比對不到了。
  if (parsed.cellular) parsed.color = parsed.color ? `${parsed.color} CEL` : 'CEL';
  return parsed;
}

function parseProduct(fullName) {
  return applyLabelOverrides(parseProductRaw(fullName));
}

// 掃出本次查詢裡「還沒中文化」的顏色，供設定模式一鍵補字。
// 只看 iPhone / iPad / Mac：Watch 的錶殼色本來就是中文，
// iPad Pro 則是刻意保留英文（keepEnglish），兩者都不算漏。
function findUntranslatedColors(items) {
  const found = new Map();
  for (const item of items || []) {
    const name = String(item.name || '').trim();
    if (!name) continue;
    const parsed = parseProductRaw(name);
    if (parsed.type === 'watch' || parsed.keepEnglish) continue;
    const color = String(parsed.color || '').trim();
    if (!color || !/[A-Za-z]/.test(color)) continue;
    const table = parsed.type === 'iphone' ? 'iphoneColors' : 'enColors';
    const key = table + '|' + color.toUpperCase();
    if (found.has(key)) continue;
    found.set(key, { color, key: color.toUpperCase(), table, sample: name });
  }
  return [...found.values()];
}

function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
}

// 對外介面：接收 /api/purchase 回傳的 items 陣列
// 回傳展開後的標籤陣列（存貨數量=3 → 3 個 label 物件）
function expandToLabels(items) {
  const labels = [];
  for (const item of items) {
    const qty = Math.max(1, parseInt(item.stkQty) || 1);
    const name = String(item.name || '').trim();
    const brand = String(item.brandId || '').trim();
    if (!name) continue;
    const parsed = parseProduct(name);
    if (parsed.type === 'mac') continue;
    parsed.brand = brand;
    for (let q = 0; q < qty; q++) labels.push({...parsed});
  }
  return labels;
}
