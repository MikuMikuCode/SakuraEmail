# Подключение Apps Script API

Бот не подключается к Google Sheets напрямую. Он обращается к существующему
Apps Script Web App по HTTPS. Действия бота защищены отдельным секретом.

## 1. Добавьте файл

В том же Apps Script-проекте, где находится текущий код лицензирования:

1. Нажмите `+` рядом с `Files`.
2. Создайте Script-файл с именем `BotApi`.
3. Вставьте содержимое `BotApi.gs`.

## 2. Добавьте маршруты в doPost

В существующей функции `doPost`, после обработки `validate`, должны находиться:

```javascript
if (action === 'bot_get_keys') {
  return json_(botGetKeys_(payload));
}

if (action === 'bot_expiring_renewals') {
  return json_(botExpiringRenewals_(payload));
}
```

В рабочем файле `license_basis/apps_script/Code.txt` эти маршруты уже добавлены.

## 3. Создайте секрет

Сгенерируйте случайную строку длиной не менее 32 символов. Например, локально:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

В Apps Script откройте `Project Settings -> Script Properties` и добавьте:

```text
BOT_API_SECRET = сгенерированная строка
```

Ту же строку положите в локальный `.env` бота. Не вставляйте ее в `.gs`,
README, сообщения или будущий Git-репозиторий.

## 4. Опубликуйте новую версию

1. `Deploy -> Manage deployments`.
2. Откройте текущее Web App-развертывание.
3. Выберите `New version`.
4. Нажмите `Deploy`.
5. Убедитесь, что URL `/exec` совпадает с `APPS_SCRIPT_URL` в `.env`.

Простого сохранения исходника недостаточно: `/exec` продолжит выполнять старую
версию, пока развертывание не обновлено.

