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

    if (!key || !deadline || deadline.getTime() <= now.getTime()) {
      continue;
    }

    if (!botIsActiveKeyStatus_(status)) {
      continue;
    }

    keys.push({
      key,
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

    if (!telegramId || !key || !deadline) {
      continue;
    }

    if (!recordsByTelegramId[telegramId]) {
      recordsByTelegramId[telegramId] = [];
    }

    recordsByTelegramId[telegramId].push({
      telegramId,
      key,
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
          isFreeLicenseStatus_(record.status)
        )
        .sort((left, right) => right.rowNumber - left.rowNumber);

      if (renewalCandidates.length === 0) {
        continue;
      }

      const renewal = renewalCandidates[0];
      const deduplicationKey = telegramId + '|' + normalizeKey_(renewal.key);
      if (seenRenewals[deduplicationKey]) {
        continue;
      }
      seenRenewals[deduplicationKey] = true;

      notifications.push({
        telegram_id: telegramId,
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
