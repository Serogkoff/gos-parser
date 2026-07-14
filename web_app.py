"""
ВЕБ-ИНТЕРФЕЙС ДЛЯ ПРОСМОТРА НОВОСТЕЙ
"""

from flask import Flask, render_template_string
import json
import os

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Парсер новостей госорганов</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        h1 { color: #333; }
        .stats { background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        .news-item { background: #fff; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #0066cc; }
        .source { color: #666; font-size: 14px; }
        .keywords { color: #cc0000; font-weight: bold; }
        a { color: #0066cc; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .tab { display: inline-block; padding: 10px 20px; cursor: pointer; background: #ddd; border-radius: 8px 8px 0 0; margin-right: 5px; }
        .tab.active { background: #fff; }
    </style>
</head>
<body>
    <h1>📰 Новости государственных органов РФ</h1>

    <div class="stats">
        📊 Всего новостей: <b>{{ total }}</b> | 
        🔴 Совпадений: <b>{{ found }}</b> | 
        📡 Источников: <b>26</b>
    </div>

    <div>
        <a href="/"><button>Все новости</button></a>
        <a href="/found"><button>🔴 Только совпадения ({{ found }})</button></a>
    </div>

    {% for item in news %}
    <div class="news-item">
        <div class="source">📌 {{ item.source }}</div>
        <a href="{{ item.url }}" target="_blank">{{ item.title[:120] }}</a>
        {% if item.keywords %}
        <div class="keywords">🔑 {{ ', '.join(item.keywords) }}</div>
        {% endif %}
    </div>
    {% endfor %}
</body>
</html>
"""


def load_news():
    if os.path.exists('all_news.json'):
        with open('all_news.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def load_found():
    if os.path.exists('found_news.json'):
        with open('found_news.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


@app.route('/')
def index():
    news = load_news()
    found = load_found()
    return render_template_string(
        HTML_TEMPLATE,
        news=news[-100:],  # Последние 100
        total=len(news),
        found=len(found)
    )


@app.route('/found')
def found():
    found = load_found()
    return render_template_string(
        HTML_TEMPLATE,
        news=found[-100:],
        total=len(load_news()),
        found=len(found)
    )


if __name__ == '__main__':
    print("=" * 50)
    print("🌐 САЙТ ЗАПУЩЕН!")
    print("Открой в браузере: http://127.0.0.1:5000")
    print("Нажми Ctrl+C для остановки")
    print("=" * 50)
    app.run(debug=True, port=5000)