from flask import Flask, render_template_string
import json, os

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html><head><title>Парсер новостей</title><meta charset="utf-8">
<style>
body{font-family:Arial;max-width:900px;margin:0 auto;padding:20px;background:#f5f5f5}
h1{color:#333}.stats{background:#fff;padding:15px;border-radius:8px;margin-bottom:20px}
.item{background:#fff;padding:15px;margin:10px 0;border-radius:8px;border-left:4px solid #0066cc}
.source{color:#666;font-size:14px}.date{color:#999;font-size:12px}
.keywords{color:#c00;font-weight:bold}a{color:#0066cc;text-decoration:none}
button{padding:10px 20px;margin:5px;border:none;border-radius:5px;cursor:pointer;background:#0066cc;color:#fff;font-size:16px}
</style></head><body>
<h1>📰 Новости госорганов РФ</h1>
<div class="stats">📊 Всего: <b>{{total}}</b> | 🔴 Совпадений: <b>{{found}}</b></div>
<a href="/"><button>📋 Все</button></a>
<a href="/found"><button>🔴 Совпадения</button></a>
{% for item in news %}
<div class="item">
<div class="source">📌 {{item.source}}</div>
<div class="date">🕒 {{item.date or item.parsed_date or ''}}</div>
<a href="{{item.url}}" target="_blank">{{item.title[:120]}}</a>
{% if item.keywords %}<div class="keywords">🔑 {{', '.join(item.keywords)}}</div>{% endif %}
</div>{% endfor %}
</body></html>"""

@app.route('/')
def index():
    n = json.load(open('all_news.json', encoding='utf-8')) if os.path.exists('all_news.json') else []
    f = json.load(open('found_news.json', encoding='utf-8')) if os.path.exists('found_news.json') else []
    return render_template_string(HTML, news=n[-100:], total=len(n), found=len(f))

@app.route('/found')
def found():
    f = json.load(open('found_news.json', encoding='utf-8')) if os.path.exists('found_news.json') else []
    n = json.load(open('all_news.json', encoding='utf-8')) if os.path.exists('all_news.json') else []
    return render_template_string(HTML, news=f[-100:], total=len(n), found=len(f))

if __name__ == '__main__':
    print("🌐 http://127.0.0.1:5000")
    app.run(debug=True, port=5000)