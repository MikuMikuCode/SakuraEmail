/**
 * Protected SakuraEmail endpoints.
 *
 * Add this file to the same Apps Script project as the existing macro
 * licensing code. Set BOT_API_SECRET in Project Settings -> Script Properties.
 * Never put the secret directly into this source file.
 */

function botGetKeys_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const telegramId = normalizeTelegramId_(payload.telegram_id || '');
  if (!telegramId) {
    return {
      ok: false,
      message: 'telegram_id_required'
    };
  }

  const licenseTable = getTable_(LICENSE_SHEET_NAMES);
  const licCols = getRequiredColumns_(
    licenseTable.headers,
    licenseColumns_(),
    licenseTable.sheet.getName()
  );
  const now = new Date();
  const keys = [];

  for (const row of licenseTable.rows) {
    if (normalizeTelegramId_(cell_(row, licCols.telegramId)) !== telegramId) {
      continue;
    }

    const key = String(cell_(row, licCols.key)).trim();
    const rawStatus = String(cell_(row, licCols.status)).trim();
    const status = normalizeStatus_(rawStatus);
    const deadline = parseDateValue_(cell_(row, licCols.deadline));
    const licenseType = canonicalLicenseType_(cell_(row, licCols.licenseType));

    if (!key || !licenseType || !deadline || deadline.getTime() <= now.getTime()) {
      continue;
    }

    if (!botIsActiveKeyStatus_(status)) {
      continue;
    }

    keys.push({
      key,
      license_type: licenseType,
      status: rawStatus,
      status_code: isUsedLicenseStatus_(status) ? 'used' : 'free',
      expires_at: formatDate_(deadline),
      row_number: row.rowNumber
    });
  }

  keys.sort((left, right) => right.row_number - left.row_number);

  return {
    ok: true,
    telegram_id: telegramId,
    keys
  };
}

function botExpiringRenewals_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const licenseTable = getTable_(LICENSE_SHEET_NAMES);
  const licCols = getRequiredColumns_(
    licenseTable.headers,
    licenseColumns_(),
    licenseTable.sheet.getName()
  );
  const now = new Date();
  const recordsByTelegramId = {};

  for (const row of licenseTable.rows) {
    const telegramId = normalizeTelegramId_(cell_(row, licCols.telegramId));
    const key = String(cell_(row, licCols.key)).trim();
    const rawStatus = String(cell_(row, licCols.status)).trim();
    const status = normalizeStatus_(rawStatus);
    const deadline = parseDateValue_(cell_(row, licCols.deadline));
    const licenseType = canonicalLicenseType_(cell_(row, licCols.licenseType));

    if (!telegramId || !key || !licenseType || !deadline) {
      continue;
    }

    if (!recordsByTelegramId[telegramId]) {
      recordsByTelegramId[telegramId] = [];
    }

    recordsByTelegramId[telegramId].push({
      telegramId,
      key,
      licenseType,
      status,
      deadline,
      rowNumber: row.rowNumber
    });
  }

  const notifications = [];
  const seenRenewals = {};

  for (const telegramId in recordsByTelegramId) {
    const activeRecords = recordsByTelegramId[telegramId].filter(record =>
      botIsActiveKeyStatus_(record.status) &&
      record.deadline.getTime() > now.getTime()
    );

    for (const expiringRecord of activeRecords) {
      const daysLeft = daysBetweenDates_(now, expiringRecord.deadline);
      if (daysLeft < 0 || daysLeft > RENEW_DAYS_BEFORE) {
        continue;
      }

      const renewalCandidates = activeRecords
        .filter(record =>
          record.rowNumber > expiringRecord.rowNumber &&
          record.licenseType === expiringRecord.licenseType &&
          isFreeLicenseStatus_(record.status)
        )
        .sort((left, right) => right.rowNumber - left.rowNumber);

      if (renewalCandidates.length === 0) {
        continue;
      }

      const renewal = renewalCandidates[0];
      const deduplicationKey = telegramId + '|' + expiringRecord.licenseType + '|' + normalizeKey_(renewal.key);
      if (seenRenewals[deduplicationKey]) {
        continue;
      }
      seenRenewals[deduplicationKey] = true;

      notifications.push({
        telegram_id: telegramId,
        license_type: expiringRecord.licenseType,
        expiring_key: expiringRecord.key,
        expiring_at: formatDate_(expiringRecord.deadline),
        new_key: renewal.key,
        new_expires_at: formatDate_(renewal.deadline)
      });
    }
  }

  return {
    ok: true,
    notifications
  };
}

function botGetAccessSnapshot_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const databaseTable = getTable_(DATABASE_SHEET_NAMES);
  const databaseDefinitions = databaseColumns_();
  const databaseColumns = getRequiredColumns_(databaseTable.headers, {
    telegramId: databaseDefinitions.telegramId
  }, databaseTable.sheet.getName());
  const usersByTelegramId = Object.create(null);

  for (const row of databaseTable.rows) {
    const telegramId = normalizeTelegramId_(cell_(row, databaseColumns.telegramId));
    if (!telegramId) {
      continue;
    }

    const blocked = botIsBlockedAccessMarker_(cell_(row, 1));
    if (!Object.prototype.hasOwnProperty.call(usersByTelegramId, telegramId)) {
      usersByTelegramId[telegramId] = false;
    }
    if (blocked) {
      usersByTelegramId[telegramId] = true;
    }
  }

  return {
    ok: true,
    users: Object.keys(usersByTelegramId).map(telegramId => ({
      telegram_id: telegramId,
      blocked: usersByTelegramId[telegramId]
    }))
  };
}

function botGetWorkProfile_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const telegramId = normalizeTelegramId_(payload.telegram_id || '');
  if (!telegramId) {
    return {
      ok: false,
      message: 'telegram_id_required'
    };
  }

  const databaseTable = getTable_(DATABASE_SHEET_NAMES);
  const databaseDefinitions = databaseColumns_();
  const databaseColumns = getRequiredColumns_(databaseTable.headers, {
    fio: databaseDefinitions.fio,
    telegramId: databaseDefinitions.telegramId
  }, databaseTable.sheet.getName());
  const worker = botFindWorkerByTelegramId_(
    databaseTable.rows,
    databaseColumns,
    telegramId
  );

  if (!worker) {
    return {
      ok: true,
      found: false,
      telegram_id: telegramId
    };
  }

  const fullName = String(cell_(worker, databaseColumns.fio)).trim();
  const multiplierCatalog = botReadMultiplierCatalog_();
  const multiplierMap = botMultiplierMap_(multiplierCatalog);
  const transactions = botReadWorkTransactions_();
  const today = botMoscowCalendarDate_(new Date());
  const todayKey = botReportDateKey_(today);
  const tomorrowKey = botReportDateKey_(botAddCalendarDays_(today, 1));
  const weekdayFromMonday = (today.getUTCDay() + 6) % 7;
  const weekStartKey = botReportDateKey_(botAddCalendarDays_(today, -weekdayFromMonday));
  const monthStartKey = todayKey.substring(0, 8) + '01';

  return {
    ok: true,
    found: true,
    telegram_id: telegramId,
    full_name: fullName,
    display_name: botShortEmployeeName_(fullName),
    stats: {
      today: botCalculatePoints_(transactions, multiplierMap, telegramId, todayKey, tomorrowKey),
      week: botCalculatePoints_(transactions, multiplierMap, telegramId, weekStartKey, tomorrowKey),
      month: botCalculatePoints_(transactions, multiplierMap, telegramId, monthStartKey, tomorrowKey)
    }
  };
}

function botGetReportCatalog_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const telegramId = normalizeTelegramId_(payload.telegram_id || '');
  if (!telegramId) {
    return {
      ok: false,
      message: 'telegram_id_required'
    };
  }

  if (!botWorkerExists_(telegramId)) {
    return {
      ok: true,
      found: false,
      telegram_id: telegramId,
      items: []
    };
  }

  return {
    ok: true,
    found: true,
    telegram_id: telegramId,
    items: botReadMultiplierCatalog_()
  };
}

function botGetWorkReport_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const telegramId = normalizeTelegramId_(payload.telegram_id || '');
  const reportDate = botParseReportDate_(payload.report_date || '');

  if (!telegramId) {
    return {
      ok: false,
      message: 'telegram_id_required'
    };
  }

  if (!reportDate) {
    return {
      ok: true,
      employee_found: false,
      found: false,
      editable: false,
      message: 'invalid_report_date',
      items: []
    };
  }

  if (!botWorkerExists_(telegramId)) {
    return {
      ok: true,
      employee_found: false,
      found: false,
      editable: false,
      report_date: botReportDateKey_(reportDate),
      items: []
    };
  }

  const itemsByArticle = Object.create(null);
  const articleOrder = [];

  for (const transaction of botReadWorkTransactions_()) {
    if (
      transaction.telegramId !== telegramId ||
      botReportDateKey_(transaction.date) !== botReportDateKey_(reportDate)
    ) {
      continue;
    }

    if (!Object.prototype.hasOwnProperty.call(itemsByArticle, transaction.article)) {
      itemsByArticle[transaction.article] = 0;
      articleOrder.push(transaction.article);
    }
    itemsByArticle[transaction.article] += transaction.quantity;
  }

  const items = articleOrder.map(article => ({
    article,
    quantity: itemsByArticle[article]
  }));

  return {
    ok: true,
    employee_found: true,
    found: items.length > 0,
    editable: botIsEditableReportDate_(reportDate, new Date()),
    report_date: botReportDateKey_(reportDate),
    items
  };
}

function botSaveWorkReport_(payload) {
  if (!botIsAuthorized_(payload)) {
    return {
      ok: false,
      message: 'unauthorized'
    };
  }

  const telegramId = normalizeTelegramId_(payload.telegram_id || '');
  const reportDate = botParseReportDate_(payload.report_date || '');

  if (!telegramId) {
    return {
      ok: false,
      message: 'telegram_id_required'
    };
  }

  if (!botWorkerExists_(telegramId)) {
    return {
      ok: true,
      saved: false,
      message: 'employee_not_found'
    };
  }

  if (!reportDate || !botIsEditableReportDate_(reportDate, new Date())) {
    return {
      ok: true,
      saved: false,
      message: 'report_date_not_editable'
    };
  }

  const rawItems = Array.isArray(payload.items) ? payload.items : [];
  const multiplierCatalog = botReadMultiplierCatalog_();
  const multiplierMap = botMultiplierMap_(multiplierCatalog);
  const quantitiesByArticle = Object.create(null);
  const articleOrder = [];
  const unknownArticles = [];

  for (const rawItem of rawItems) {
    const article = botNormalizeArticle_(rawItem && rawItem.article);
    const rawQuantity = rawItem && rawItem.quantity;
    const quantity = Number(rawQuantity);

    if (
      !article ||
      typeof rawQuantity === 'boolean' ||
      !Number.isInteger(quantity) ||
      quantity <= 0 ||
      quantity > 1000000
    ) {
      return {
        ok: true,
        saved: false,
        message: 'invalid_report_items'
      };
    }

    if (!Object.prototype.hasOwnProperty.call(multiplierMap, article)) {
      if (unknownArticles.indexOf(article) === -1) {
        unknownArticles.push(article);
      }
      continue;
    }

    if (!Object.prototype.hasOwnProperty.call(quantitiesByArticle, article)) {
      quantitiesByArticle[article] = 0;
      articleOrder.push(article);
    }
    quantitiesByArticle[article] += quantity;
    if (quantitiesByArticle[article] > 1000000) {
      return {
        ok: true,
        saved: false,
        message: 'invalid_report_items'
      };
    }
  }

  if (unknownArticles.length > 0) {
    return {
      ok: true,
      saved: false,
      message: 'unknown_articles',
      unknown_articles: unknownArticles
    };
  }

  if (articleOrder.length === 0) {
    return {
      ok: true,
      saved: false,
      message: 'empty_report'
    };
  }

  const items = articleOrder.map(article => ({
    article,
    quantity: quantitiesByArticle[article]
  }));
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);

  try {
    botReplaceWorkReport_(telegramId, reportDate, items);
  } finally {
    lock.releaseLock();
  }

  return {
    ok: true,
    saved: true,
    message: 'report_saved',
    report_date: botReportDateKey_(reportDate),
    items
  };
}

function botWorkerExists_(telegramId) {
  const databaseTable = getTable_(DATABASE_SHEET_NAMES);
  const databaseDefinitions = databaseColumns_();
  const databaseColumns = getRequiredColumns_(databaseTable.headers, {
    telegramId: databaseDefinitions.telegramId
  }, databaseTable.sheet.getName());
  return Boolean(botFindWorkerByTelegramId_(databaseTable.rows, databaseColumns, telegramId));
}

function botFindWorkerByTelegramId_(rows, columns, telegramId) {
  for (const row of rows) {
    if (normalizeTelegramId_(cell_(row, columns.telegramId)) === telegramId) {
      return row;
    }
  }
  return null;
}

function botShortEmployeeName_(fullName) {
  const parts = String(fullName || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 3) {
    return parts.slice(0, -1).join(' ');
  }
  return parts.join(' ');
}

function botReadMultiplierCatalog_() {
  const table = getTable_(WORK_MULTIPLIER_SHEET_NAMES);
  const items = [];
  const positionsByArticle = Object.create(null);

  for (const row of table.rows) {
    const article = botNormalizeArticle_(cell_(row, 1));
    const rawCoefficient = cell_(row, 3);
    const coefficient = typeof rawCoefficient === 'number'
      ? rawCoefficient
      : Number(String(rawCoefficient).trim().replace(',', '.'));

    if (!article || !isFinite(coefficient) || coefficient <= 0) {
      continue;
    }

    const item = {
      article,
      coefficient
    };

    if (Object.prototype.hasOwnProperty.call(positionsByArticle, article)) {
      items[positionsByArticle[article]] = item;
    } else {
      positionsByArticle[article] = items.length;
      items.push(item);
    }
  }

  return items;
}

function botMultiplierMap_(catalog) {
  const result = Object.create(null);
  for (const item of catalog) {
    result[item.article] = item.coefficient;
  }
  return result;
}

function botReadWorkTransactions_() {
  const sheet = botGetSheetByNames_(WORK_REPORT_SHEET_NAMES);
  const maxRows = sheet.getMaxRows();
  if (maxRows < 2) {
    return [];
  }

  const dateValues = sheet.getRange(2, 1, maxRows - 1, 1).getValues();
  const reportValues = sheet.getRange(2, 4, maxRows - 1, 3).getValues();
  const transactions = [];

  for (let index = 0; index < dateValues.length; index += 1) {
    const date = parseDateValue_(dateValues[index][0]);
    const telegramId = normalizeTelegramId_(reportValues[index][0]);
    const article = botNormalizeArticle_(reportValues[index][1]);
    const quantity = Number(reportValues[index][2]);

    if (!date || !telegramId || !article || !Number.isInteger(quantity) || quantity <= 0) {
      continue;
    }

    transactions.push({
      rowNumber: index + 2,
      date,
      telegramId,
      article,
      quantity
    });
  }

  return transactions;
}

function botCalculatePoints_(transactions, multiplierMap, telegramId, startDateKey, endDateKey) {
  let total = 0;

  for (const transaction of transactions) {
    if (transaction.telegramId !== telegramId) {
      continue;
    }
    const transactionDateKey = botReportDateKey_(transaction.date);
    if (transactionDateKey < startDateKey || transactionDateKey >= endDateKey) {
      continue;
    }
    if (!Object.prototype.hasOwnProperty.call(multiplierMap, transaction.article)) {
      continue;
    }
    total += transaction.quantity * multiplierMap[transaction.article];
  }

  return Math.round(total * 10000) / 10000;
}

function botReplaceWorkReport_(telegramId, reportDate, items) {
  const sheet = botGetSheetByNames_(WORK_REPORT_SHEET_NAMES);
  const maxRows = Math.max(sheet.getMaxRows(), 2);
  const dateValues = sheet.getRange(2, 1, maxRows - 1, 1).getValues();
  const reportValues = sheet.getRange(2, 4, maxRows - 1, 3).getValues();
  const reportDateKey = botReportDateKey_(reportDate);
  const matchingRows = [];
  const availableRows = [];

  for (let index = 0; index < dateValues.length; index += 1) {
    const rowNumber = index + 2;
    const rowDate = parseDateValue_(dateValues[index][0]);
    const rowTelegramId = normalizeTelegramId_(reportValues[index][0]);

    if (
      rowDate &&
      rowTelegramId === telegramId &&
      botReportDateKey_(rowDate) === reportDateKey
    ) {
      matchingRows.push(rowNumber);
      continue;
    }

    if (
      String(dateValues[index][0]).trim() === '' &&
      String(reportValues[index][0]).trim() === '' &&
      String(reportValues[index][1]).trim() === '' &&
      String(reportValues[index][2]).trim() === ''
    ) {
      availableRows.push(rowNumber);
    }
  }

  const targetRows = matchingRows.slice(0, items.length);
  while (targetRows.length < items.length && availableRows.length > 0) {
    targetRows.push(availableRows.shift());
  }

  if (targetRows.length < items.length) {
    const rowsToAdd = items.length - targetRows.length;
    const previousMaxRows = sheet.getMaxRows();
    sheet.insertRowsAfter(previousMaxRows, rowsToAdd);
    for (let offset = 1; offset <= rowsToAdd; offset += 1) {
      targetRows.push(previousMaxRows + offset);
    }
  }

  const timestamp = botReportTimestamp_(reportDate, new Date());
  for (let index = 0; index < items.length; index += 1) {
    const rowNumber = targetRows[index];
    const item = items[index];
    sheet.getRange(rowNumber, 1).setValue(timestamp).setNumberFormat('dd.MM.yyyy HH:mm:ss');
    sheet.getRange(rowNumber, 4, 1, 3).setValues([[
      botTelegramIdCellValue_(telegramId),
      item.article,
      item.quantity
    ]]);
  }

  for (let index = items.length; index < matchingRows.length; index += 1) {
    const rowNumber = matchingRows[index];
    sheet.getRange(rowNumber, 1).clearContent();
    sheet.getRange(rowNumber, 4, 1, 3).clearContent();
  }
}

function botNormalizeArticle_(value) {
  return String(value || '').trim().toUpperCase().replace(/\s+/g, '');
}

function botTelegramIdCellValue_(telegramId) {
  const normalized = normalizeTelegramId_(telegramId);
  const numericValue = Number(normalized);
  if (/^\d+$/.test(normalized) && Number.isSafeInteger(numericValue)) {
    return numericValue;
  }
  return normalized;
}

function botParseReportDate_(value) {
  const match = String(value || '').trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return null;
  }
  try {
    const date = Utilities.parseDate(
      match[1] + '-' + match[2] + '-' + match[3] + ' 12:00:00',
      WORK_TIME_ZONE,
      'yyyy-MM-dd HH:mm:ss'
    );
    return botReportDateKey_(date) === String(value).trim() ? date : null;
  } catch (error) {
    return null;
  }
}

function botReportDateKey_(date) {
  return Utilities.formatDate(date, WORK_TIME_ZONE, 'yyyy-MM-dd');
}

function botIsEditableReportDate_(reportDate, now) {
  const today = botMoscowCalendarDate_(now);
  const daysOld = Math.round((today.getTime() - reportDate.getTime()) / 86400000);
  return daysOld >= 0 && daysOld < WORK_REPORT_EDIT_DAYS;
}

function botReportTimestamp_(reportDate, now) {
  return Utilities.parseDate(
    botReportDateKey_(reportDate) + ' ' + Utilities.formatDate(now, WORK_TIME_ZONE, 'HH:mm:ss'),
    WORK_TIME_ZONE,
    'yyyy-MM-dd HH:mm:ss'
  );
}

function botMoscowCalendarDate_(value) {
  return botParseReportDate_(Utilities.formatDate(value, WORK_TIME_ZONE, 'yyyy-MM-dd'));
}

function botAddCalendarDays_(value, days) {
  return new Date(value.getTime() + days * 86400000);
}

function botGetSheetByNames_(sheetNames) {
  const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  for (const sheetName of sheetNames) {
    const sheet = spreadsheet.getSheetByName(sheetName);
    if (sheet) {
      return sheet;
    }
  }
  throw new Error('Sheet not found: ' + sheetNames.join(' / '));
}

function botIsAuthorized_(payload) {
  const expected = String(
    PropertiesService.getScriptProperties().getProperty('BOT_API_SECRET') || ''
  );
  const provided = String(payload && payload.secret ? payload.secret : '');

  if (!expected || !provided || expected.length !== provided.length) {
    return false;
  }

  let difference = 0;
  for (let index = 0; index < expected.length; index += 1) {
    difference |= expected.charCodeAt(index) ^ provided.charCodeAt(index);
  }
  return difference === 0;
}

function botIsActiveKeyStatus_(status) {
  return isFreeLicenseStatus_(status) || isUsedLicenseStatus_(status);
}

function botIsBlockedAccessMarker_(value) {
  return ['заблокирован', 'заблокирована', 'blocked'].indexOf(normalizeStatus_(value)) !== -1;
}
