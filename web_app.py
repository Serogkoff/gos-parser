from flask import Flask, render_template_string, request
import json, os

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html><head><title>Парсер новостей</title><meta charset="utf-8">
<style>
body{font-family:Arial;max-width:1000px;margin:0 auto;padding:20px;background:#f5f5f5}
h1{color:#333}.stats{background:#fff;padding:15px;border-radius:8px;margin-bottom:20px}
.item{background:#fff;padding:15px;margin:10px 0;border-radius:8px;border-left:4px solid #0066cc;cursor:pointer}
.item:hover{background:#f0f0ff}
.source{color:#666;font-size:14px}.date{color:#999;font-size:12px}
.keywords{color:#c00;font-weight:bold}a{color:#0066cc;text-decoration:none}
button{padding:8px 15px;margin:3px;border:none;border-radius:5px;cursor:pointer;background:#0066cc;color:#fff;font-size:14px}
button:hover{background:#004499}
.filters{margin:15px 0}
</style></head><body>
<h1>📰 Новости госорганов РФ</h1>
<div class="stats">📊 Всего: <b>{{total}}</b> | 🔴 Совпадений: <b>{{found}}</b> | 📡 Источник: <b>{{source_filter or 'Все'}}</b></div>

<div class="filters">
<a href="/"><button>📋 Все</button></a>
<a href="/found"><button>🔴 Совпадения</button></a>
<hr>
{% for src in sources %}
<a href="/?source={{src}}"><button>{{src}}</button></a>
{% endfor %}
</div>

{% for item in news %}
<div class="item" onclick="window.open('{{item.url}}', '_blank')">
<div class="source">📌 {{item.source}}</div>
<div class="date">🕒 {{item.date or item.parsed_date or ''}}</div>
<div>{{item.title[:120]}}</div>
{% if item.keywords %}<div class="keywords">🔑 {{', '.join(item.keywords)}}</div>{% endif %}
</div>{% endfor %}
</body></html>"""


def get_all_news():
    if os.path.exists('all_news.json'):
        with open('all_news.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def get_found_news():
    if os.path.exists('found_news.json'):
        with open('found_news.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


@app.route('/')
def index():
    all_news = get_all_news()
    found = get_found_news()
    source = request.args.get('source', '')

    if source:
        news = [n for n in all_news if n.get('source') == source]
    else:
        news = all_news[-100:]

    sources = sorted(set(n.get('source', '') for n in all_news))

    return render_template_string(HTML,
                                  news=news[-100:],
                                  total=len(all_news),
                                  found=len(found),
                                  source_filter=source,
                                  sources=sources
                                  )


@app.route('/found')
def found():
    all_news = get_all_news()
    found = get_found_news()
    sources = sorted(set(n.get('source', '') for n in all_news))

    return render_template_string(HTML,
                                  news=found[-100:],
                                  total=len(all_news),
                                  found=len(found),
                                  source_filter='',
                                  sources=sources
                                  )


if __name__ == '__main__':
    print("🌐 http://127.0.0.1:5000")
    app.run(debug=True, port=5000)