# Парсер новостей госорганов РФ

Проект собирает новости с сайтов российских государственных органов, ищет
заданные ключевые слова и сохраняет результаты в JSON.

## Установка

Рекомендуется Python 3.12 или 3.13.

### Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

## Запуск

Один полный цикл парсинга с последующим повтором каждые пять минут:

```bash
python main.py
```

Веб-интерфейс запускается отдельно:

```bash
python web_app.py
```

После этого откройте <http://127.0.0.1:5000>.

В интерфейсе заголовок открывает текст новости внутри «Монитора», а ссылка на
оригинал остаётся внизу публикации. В шапке показываются часы Москвы и Токио.
Кнопка «Ключевые слова» позволяет добавлять и удалять фразы и сразу
пересобирает раздел «Совпадения». Пользовательский список сохраняется в
`keywords.json`; до первого изменения используются слова из `config.py`.

## Основные файлы

- `main.py` — запускает все парсеры.
- `config.py` — ключевые слова и интервалы.
- `parsers/sites/` — отдельный модуль для каждого источника.
- `utils/http_client.py` — загрузка обычных HTML/XML-страниц.
- `utils/js_client.py` — загрузка сайтов через Chromium.
- `utils/storage.py` — безопасное чтение и сохранение результатов.
- `utils/news.py` — нормализация URL и удаление дублей.
- `utils/status.py` — сводка работоспособности всех источников.
- `web_app.py` — локальный интерфейс.

Ошибки сети и парсеров записываются в `parser_errors.log`.
Последнее состояние источников сохраняется в `parser_status.json`.
