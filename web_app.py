import json
import os
import secrets
from collections import Counter
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from utils.auth import load_secret_key
from utils.article_reader import extract_article
from utils.keywords import (
    add_keyword,
    load_keywords,
    rebuild_found_news,
    remove_keyword,
)
from utils.news import sort_news_by_publication
from utils.source_groups import (
    AGENCIES_GROUP,
    AGENCY_SOURCES,
    GOVERNMENT_GROUP,
    GOVERNMENT_SOURCES,
    NEWSPAPERS_GROUP,
    NEWSPAPER_SOURCES,
    filter_news_by_group,
    source_group as get_source_group,
)
from utils.storage import (
    authenticate_user,
    bookmarked_urls,
    count_users,
    count_bookmarks,
    create_bookmark_folder,
    create_user,
    delete_bookmark_folder,
    enqueue_parser_job,
    find_news_by_url,
    list_users,
    list_parser_jobs,
    list_bookmark_folders,
    list_bookmarks,
    load_source_order,
    load_source_settings,
    load_all_news,
    load_cached_article,
    load_found_news,
    load_user,
    remove_bookmark,
    rename_bookmark_folder,
    save_cached_article,
    save_bookmark,
    save_source_order,
    set_source_enabled,
    set_user_active,
    set_user_password,
    set_user_role,
    source_news_statistics,
    update_bookmark,
)


app = Flask(__name__)
PROJECT_DIR = Path(__file__).resolve().parent
NEWS_PER_PAGE = 20
app.config.update(
    SECRET_KEY=load_secret_key(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("MONITOR_HTTPS") == "1",
    AUTH_DISABLED=os.environ.get("MONITOR_AUTH_DISABLED") == "1",
)


AUTH_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{'Первый запуск' if mode == 'setup' else 'Вход'}} — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45}
        *{box-sizing:border-box}body{min-height:100vh;margin:0;display:grid;place-items:center;padding:24px;color:var(--ink);background:radial-gradient(circle at 0 0,#fff,transparent 42rem),var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}
        .card{width:min(440px,100%);padding:38px;border:1px solid var(--line);border-radius:9px;background:var(--surface);box-shadow:0 25px 70px rgba(46,38,27,.08)}
        .eyebrow{margin:0 0 9px;color:var(--coral);font-size:11px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}
        h1{margin:0;font-size:38px;line-height:1;letter-spacing:-.045em}p{margin:15px 0 25px;color:var(--muted);font-size:14px;line-height:1.55}
        label{display:block;margin-top:15px;color:#514c45;font-size:13px;font-weight:650}input{width:100%;height:48px;margin-top:7px;padding:0 13px;border:1px solid #c9c1b5;border-radius:6px;color:var(--ink);background:#fff;font:inherit}input:focus{outline:3px solid rgba(228,79,69,.18);border-color:var(--coral)}
        button{width:100%;height:49px;margin-top:23px;border:0;border-radius:6px;color:#fff;background:var(--coral);font:700 15px inherit;cursor:pointer}button:hover{background:#c93c35}
        .error{margin:18px 0 0;padding:12px;color:#a72d27;border-left:3px solid var(--coral);background:#fff1ed;font-size:13px}
        .hint{margin:13px 0 0;font-size:11px}.brand{margin-bottom:30px;font-size:19px;font-weight:800;letter-spacing:-.035em}
    </style>
</head>
<body><main class="card">
    <div class="brand">Монитор</div>
    <p class="eyebrow">{{'Настройка владельца' if mode == 'setup' else 'Личный кабинет'}}</p>
    <h1>{{'Первый запуск' if mode == 'setup' else 'Вход'}}</h1>
    <p>
        {% if mode == 'setup' %}
        Создай первую учётную запись. Она получит роль администратора и полный доступ к настройкам.
        {% else %}
        Войди в свою учётную запись, чтобы открыть мониторинг и личные данные.
        {% endif %}
    </p>
    <form method="post">
        <input type="hidden" name="csrf_token" value="{{csrf_token}}">
        <input type="hidden" name="next" value="{{next_url}}">
        <label>Логин
            <input name="username" value="{{username}}" minlength="3" maxlength="50" autocomplete="username" required autofocus>
        </label>
        <label>Пароль
            <input type="password" name="password" minlength="10" maxlength="256" autocomplete="{{'new-password' if mode == 'setup' else 'current-password'}}" required>
        </label>
        {% if mode == 'setup' %}
        <label>Повтори пароль
            <input type="password" name="password_confirm" minlength="10" maxlength="256" autocomplete="new-password" required>
        </label>
        {% endif %}
        <button type="submit">{{'Создать администратора' if mode == 'setup' else 'Войти'}}</button>
    </form>
    {% if error %}<div class="error">{{error}}</div>{% endif %}
    {% if mode == 'setup' %}<p class="hint">Пароль хранится в SQLite только в виде защищённого хеша.</p>{% endif %}
</main></body></html>
"""


SETTINGS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{title}} — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}.shell{width:min(1050px,calc(100% - 34px));margin:auto;padding:30px 0 80px}
        a{color:inherit}.back{color:var(--muted);text-decoration:none}.back:hover{color:var(--coral)}header{display:flex;align-items:end;justify-content:space-between;gap:20px;margin:34px 0 25px}h1{margin:0;font-size:clamp(36px,5vw,58px);letter-spacing:-.05em}.subtitle{margin:8px 0 0;color:var(--muted)}
        .card{padding:25px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.card h2{margin:0 0 18px;font-size:21px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}.wide{grid-column:1/-1}label{display:grid;gap:7px;color:#5e574e;font-size:12px;font-weight:650}input,select{width:100%;height:44px;padding:0 12px;border:1px solid #c9c1b5;border-radius:6px;color:var(--ink);background:#fff;font:inherit}button,.button{min-height:42px;padding:0 15px;border:1px solid var(--coral);border-radius:6px;color:var(--coral);background:transparent;font:650 13px inherit;cursor:pointer}.primary{color:#fff;background:var(--coral)}button:disabled{cursor:not-allowed;opacity:.42}.message,.error{margin:0 0 18px;padding:13px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}
        .users{display:grid;gap:12px;margin-top:18px}.user{display:grid;grid-template-columns:minmax(150px,1fr) 145px 130px minmax(230px,1.4fr);gap:14px;align-items:center;padding:18px;border:1px solid var(--line);border-radius:7px;background:var(--surface)}.identity strong{display:block}.identity small,.last-login{color:var(--muted);font-size:11px}.status{width:max-content;padding:5px 8px;border-radius:999px;color:var(--green);background:#edf6ef;font-size:10px;font-weight:750;text-transform:uppercase}.status.off{color:#9d302a;background:#fff0ed}.inline{display:flex;gap:7px;align-items:end}.inline label{flex:1}.inline button{flex:0 0 auto}.role-form{display:flex;gap:7px}.role-form select{min-width:0}.top-actions{display:flex;gap:9px;align-items:center}.button{display:inline-flex;align-items:center;text-decoration:none}
        @media(max-width:850px){.user{grid-template-columns:1fr 1fr}.user-actions{grid-column:1/-1}}@media(max-width:580px){header{align-items:start;flex-direction:column}.grid,.user{grid-template-columns:1fr}.wide,.user-actions{grid-column:auto}.inline,.role-form{align-items:stretch;flex-direction:column}}
    </style>
</head>
<body><main class="shell">
    <a class="back" href="/">← Вернуться к Монитору</a>
    <header>
        <div><h1>{{title}}</h1><p class="subtitle">{{subtitle}}</p></div>
        <div class="top-actions">
            {% if current_user.role == 'admin' %}<a class="button" href="/admin/sources">Источники</a>{% endif %}
            {% if mode == 'account' and current_user.role == 'admin' %}<a class="button" href="/admin/users">Пользователи</a>{% endif %}
            {% if mode == 'users' %}<a class="button" href="/account">Мой аккаунт</a>{% endif %}
        </div>
    </header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}
    {% if error %}<p class="error">{{error}}</p>{% endif %}

    {% if mode == 'account' %}
    <section class="card">
        <h2>Сменить пароль</h2>
        <form method="post" class="grid">
            <input type="hidden" name="csrf_token" value="{{csrf_token}}">
            <label class="wide">Текущий пароль<input type="password" name="current_password" autocomplete="current-password" required></label>
            <label>Новый пароль<input type="password" name="new_password" minlength="10" autocomplete="new-password" required></label>
            <label>Повтори новый пароль<input type="password" name="password_confirm" minlength="10" autocomplete="new-password" required></label>
            <div class="wide"><button class="primary" type="submit">Сохранить новый пароль</button></div>
        </form>
    </section>
    {% else %}
    <section class="card">
        <h2>Новый пользователь</h2>
        <form method="post" class="grid">
            <input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="create">
            <label>Логин<input name="username" minlength="3" maxlength="50" required></label>
            <label>Роль<select name="role"><option value="user">Пользователь</option><option value="admin">Администратор</option></select></label>
            <label>Временный пароль<input type="password" name="password" minlength="10" autocomplete="new-password" required></label>
            <label>Повтори пароль<input type="password" name="password_confirm" minlength="10" autocomplete="new-password" required></label>
            <div class="wide"><button class="primary" type="submit">Создать аккаунт</button></div>
        </form>
    </section>

    <section class="users">
        {% for user in users %}
        <article class="user">
            <div class="identity"><strong>{{user.username}}{{' · это вы' if user.id == current_user.id else ''}}</strong><small>Создан {{user.created_at.replace('T',' ')}}</small></div>
            <span class="status {{'off' if not user.is_active else ''}}">{{'Активен' if user.is_active else 'Отключён'}}</span>
            <form class="role-form" method="post">
                <input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="role"><input type="hidden" name="user_id" value="{{user.id}}">
                <select name="role" {{'disabled' if user.id == current_user.id else ''}}><option value="user" {{'selected' if user.role == 'user' else ''}}>Пользователь</option><option value="admin" {{'selected' if user.role == 'admin' else ''}}>Администратор</option></select>
                <button type="submit" {{'disabled' if user.id == current_user.id else ''}}>Роль</button>
            </form>
            <div class="user-actions">
                <form class="inline" method="post">
                    <input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="password"><input type="hidden" name="user_id" value="{{user.id}}">
                    <label>Новый пароль<input type="password" name="password" minlength="10" autocomplete="new-password" required></label><button type="submit">Сменить</button>
                </form>
                <form method="post" style="margin-top:8px">
                    <input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="user_id" value="{{user.id}}">
                    <button type="submit" {{'disabled' if user.id == current_user.id else ''}}>{{'Отключить вход' if user.is_active else 'Включить вход'}}</button>
                    <span class="last-login">Последний вход: {{user.last_login_at.replace('T',' ') if user.last_login_at else 'ещё не входил'}}</span>
                </form>
            </div>
        </article>
        {% endfor %}
    </section>
    {% endif %}
</main></body></html>
"""


ADMIN_SOURCES_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {% if auto_refresh %}<meta http-equiv="refresh" content="8">{% endif %}
    <title>Управление источниками — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655;--amber:#a86e16}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}.shell{width:min(1450px,calc(100% - 34px));margin:auto;padding:30px 0 80px}a{color:inherit}.top{display:flex;align-items:center;justify-content:space-between;gap:18px}.back{color:var(--muted);text-decoration:none}.back:hover{color:var(--coral)}.top-actions{display:flex;gap:8px}.button,button{min-height:40px;padding:0 14px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:6px;color:#5b554c;background:var(--surface);font:650 12px inherit;text-decoration:none;cursor:pointer}.button:hover,button:hover{color:var(--coral);border-color:var(--coral)}header{margin:36px 0 24px}h1{margin:0;font-size:clamp(38px,5vw,64px);line-height:1;letter-spacing:-.055em}.subtitle{margin:10px 0 0;color:var(--muted)}
        .message,.error{margin:0 0 18px;padding:13px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:20px}.metric{padding:20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.metric span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;margin-top:7px;font-size:31px;letter-spacing:-.04em}.metric.good strong{color:var(--green)}.metric.warn strong{color:var(--amber)}.metric.bad strong{color:var(--coral)}
        .panel{overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.panel-head{min-height:64px;padding:0 20px;display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0;font-size:18px}.panel-head p{margin:4px 0 0;color:var(--muted);font-size:11px}.source-table{width:100%;border-collapse:collapse}.source-table th{padding:11px 13px;color:var(--muted);background:#faf6ef;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em}.source-table td{padding:13px;border-top:1px solid #e6dfd4;vertical-align:middle;font-size:12px}.source-table tbody tr:hover{background:#fff9f2}.source strong{display:block;font-size:13px}.source small,.muted{display:block;margin-top:3px;color:var(--muted);font-size:10px}.badge{width:max-content;padding:5px 8px;border-radius:999px;background:#edf6ef;color:var(--green);font-size:10px;font-weight:750}.badge.empty,.badge.pending,.badge.running{color:var(--amber);background:#fff4de}.badge.error{color:#a63a32;background:#fff0ed}.badge.disabled{color:#777267;background:#eee9e1}.result b{display:block;font-size:13px}.error-copy{max-width:260px;margin-top:4px;overflow:hidden;color:#a63a32;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.actions{display:flex;justify-content:flex-end;gap:7px}.actions form{margin:0}.actions .run{color:var(--coral);border-color:rgba(228,79,69,.5)}.actions button:disabled{cursor:not-allowed;opacity:.4}.pause{min-width:86px}.jobs{margin-top:18px;padding:18px 20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.jobs h2{margin:0 0 12px;font-size:16px}.job{min-height:34px;display:grid;grid-template-columns:minmax(180px,1fr) 100px 155px minmax(0,2fr);align-items:center;gap:12px;border-top:1px solid #ece5da;font-size:11px}.job:first-of-type{border-top:0}.job-error{overflow:hidden;color:#a63a32;text-overflow:ellipsis;white-space:nowrap}.empty-jobs{color:var(--muted);font-size:12px}
        @media(max-width:1050px){.summary{grid-template-columns:repeat(2,1fr)}.table-wrap{overflow-x:auto}.source-table{min-width:980px}}@media(max-width:620px){.shell{width:min(100% - 22px,1450px)}.top{align-items:flex-start;flex-direction:column}.summary{grid-template-columns:1fr 1fr}.metric{padding:15px}.metric strong{font-size:25px}.job{grid-template-columns:1fr 90px}.job span:nth-child(n+3){display:none}}
    </style>
</head>
<body><main class="shell">
    <div class="top">
        <a class="back" href="/">← Вернуться к Монитору</a>
        <div class="top-actions"><a class="button" href="/admin/users">Пользователи</a><a class="button" href="/account">Мой аккаунт</a></div>
    </div>
    <header><h1>Источники</h1><p class="subtitle">Состояние парсеров, ручные проверки и управление расписанием</p></header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}
    {% if error %}<p class="error">{{error}}</p>{% endif %}
    <section class="summary">
        <article class="metric"><span>Всего источников</span><strong>{{summary.total}}</strong></article>
        <article class="metric good"><span>Работают</span><strong>{{summary.ok}}</strong></article>
        <article class="metric warn"><span>Ждут внимания</span><strong>{{summary.problem}}</strong></article>
        <article class="metric bad"><span>На паузе</span><strong>{{summary.disabled}}</strong></article>
    </section>
    <section class="panel">
        <div class="panel-head"><div><h2>Центр управления</h2><p>Задания выполняет запущенный main.py; страница обновляется сама, пока есть активная проверка.</p></div><a class="button" href="/admin/sources">Обновить страницу</a></div>
        <div class="table-wrap"><table class="source-table">
            <thead><tr><th>Источник</th><th>Состояние</th><th>Последняя проверка</th><th>Последняя новость</th><th>Результат</th><th></th></tr></thead>
            <tbody>{% for item in sources %}
            <tr>
                <td class="source"><strong>{{item.source}}</strong><small>{{item.group_label}} · {{item.total_news}} в базе</small></td>
                <td><span class="badge {{item.status_class}}">{{item.status_label}}</span>{% if item.job_label %}<small class="muted">{{item.job_label}}</small>{% endif %}</td>
                <td>{{item.checked_at or 'ещё не проверялся'}}<small class="muted">успешно: {{item.last_success or '—'}}</small></td>
                <td>{{item.last_received or '—'}}<small class="muted">публикация: {{item.newest_publication or '—'}}</small></td>
                <td class="result"><b>{{item.news_count}} материалов · {{item.duration}} с</b>{% if item.error %}<div class="error-copy" title="{{item.error}}">{{item.error}}</div>{% endif %}</td>
                <td><div class="actions">
                    <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="refresh"><input type="hidden" name="source" value="{{item.source}}"><button class="run" type="submit" {{'disabled' if not item.enabled or item.job_active else ''}}>Обновить</button></form>
                    <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="source" value="{{item.source}}"><button class="pause" type="submit">{{'Пауза' if item.enabled else 'Включить'}}</button></form>
                </div></td>
            </tr>{% endfor %}</tbody>
        </table></div>
    </section>
    <section class="jobs"><h2>Последние ручные проверки</h2>{% for job in jobs %}<div class="job"><strong>{{job.source}}</strong><span class="badge {{job.status}}">{{job.status_label}}</span><span>{{job.requested_at.replace('T',' ')}}</span><span class="job-error">{{job.error}}</span></div>{% else %}<p class="empty-jobs">Ручных проверок пока не было.</p>{% endfor %}</section>
</main></body></html>
"""


BOOKMARKS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Закладки — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}a{color:inherit;text-decoration:none}.shell{width:min(1250px,calc(100% - 34px));margin:auto;padding:28px 0 80px}.top{display:flex;align-items:center;justify-content:space-between;gap:15px}.back{color:var(--muted)}.account{font-size:12px;color:var(--muted)}header{margin:38px 0 26px}h1{margin:0;font-size:clamp(42px,6vw,70px);line-height:1;letter-spacing:-.055em}.subtitle{margin:10px 0 0;color:var(--muted)}.layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:20px;align-items:start}.panel,.feed{border:1px solid var(--line);border-radius:8px;background:var(--surface)}.panel{position:sticky;top:18px;overflow:hidden}.panel h2{margin:0;padding:19px;border-bottom:1px solid var(--line);font-size:17px}.folder-list{padding:9px}.folder{min-height:42px;padding:0 10px;display:flex;align-items:center;justify-content:space-between;gap:8px;border-radius:5px;color:#5e574e;font-size:13px}.folder:hover,.folder.active{color:var(--coral);background:#fff3ed}.folder b{font-size:11px}.create{padding:15px;border-top:1px solid var(--line)}label{display:grid;gap:6px;color:var(--muted);font-size:11px}input,select,textarea{width:100%;padding:10px 11px;border:1px solid #c9c1b5;border-radius:6px;color:var(--ink);background:#fff;font:inherit}input,select{height:42px}textarea{min-height:92px;resize:vertical}button{min-height:40px;padding:0 13px;border:1px solid var(--coral);border-radius:6px;color:var(--coral);background:transparent;font:650 12px Inter,Arial,sans-serif;cursor:pointer}.primary{color:#fff;background:var(--coral)}.create button{width:100%;margin-top:8px}.message,.error{margin:0 0 16px;padding:13px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}.feed-head{padding:20px 23px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.feed-head h2{margin:0;font-size:18px}.bookmark{padding:24px;border-bottom:1px solid var(--line)}.bookmark:last-child{border-bottom:0}.meta{display:flex;flex-wrap:wrap;gap:9px;color:var(--muted);font-size:12px}.bookmark h3{margin:10px 0 18px;font-size:clamp(21px,3vw,31px);line-height:1.15;letter-spacing:-.035em}.bookmark h3 a:hover{color:var(--coral)}.edit{display:grid;grid-template-columns:190px minmax(0,1fr) auto;gap:10px;align-items:end}.remove{margin-top:9px;border-color:var(--line);color:var(--muted)}.folder-tools{margin:0 9px 10px;padding:12px;border:1px solid var(--line);border-radius:6px;background:#faf6ef}.folder-tools form{display:flex;gap:7px}.folder-tools form+form{margin-top:7px}.folder-tools input{min-width:0}.empty{padding:70px 25px;color:var(--muted);text-align:center}.empty strong{display:block;margin-bottom:7px;color:var(--ink);font-size:20px}
        @media(max-width:800px){.layout{grid-template-columns:1fr}.panel{position:static}.edit{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
    </style>
</head>
<body><main class="shell">
    <div class="top"><a class="back" href="/">← Вернуться к Монитору</a><a class="account" href="/account">{{current_user.username}} · настройки аккаунта</a></div>
    <header><h1>Закладки</h1><p class="subtitle">Личные папки, сохранённые новости и рабочие заметки</p></header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}{% if error %}<p class="error">{{error}}</p>{% endif %}
    <div class="layout">
        <aside class="panel">
            <h2>Папки</h2>
            <nav class="folder-list">
                <a class="folder {{'active' if selected_folder == 'all' else ''}}" href="/bookmarks"><span>Все закладки</span><b>{{total_count}}</b></a>
                <a class="folder {{'active' if selected_folder == 'unfiled' else ''}}" href="/bookmarks?folder=unfiled"><span>Без папки</span><b>{{unfiled_count}}</b></a>
                {% for folder in folders %}<a class="folder {{'active' if selected_folder == folder.id|string else ''}}" href="/bookmarks?folder={{folder.id}}"><span>{{folder.name}}</span><b>{{folder.bookmark_count}}</b></a>{% endfor %}
            </nav>
            {% if selected_folder not in ('all','unfiled') and selected_folder_data %}
            <div class="folder-tools">
                <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="rename_folder"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><input name="name" value="{{selected_folder_data.name}}" maxlength="80" required><button type="submit">Переименовать</button></form>
                <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="delete_folder"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><button type="submit">Удалить папку</button></form>
            </div>
            {% endif %}
            <form class="create" method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="create_folder"><label>Новая папка<input name="name" maxlength="80" placeholder="Например: Выборы" required></label><button class="primary" type="submit">Создать папку</button></form>
        </aside>
        <section class="feed">
            <div class="feed-head"><h2>{{selected_title}}</h2><span>{{bookmarks|length}} материалов</span></div>
            {% if bookmarks %}
                {% for bookmark in bookmarks %}
                <article class="bookmark">
                    <div class="meta"><span>{{bookmark.source}}</span><span>•</span><time>{{bookmark.date or 'дата не указана'}}</time>{% if bookmark.folder_name %}<span>•</span><span>{{bookmark.folder_name}}</span>{% endif %}</div>
                    <h3><a href="/article?url={{bookmark.url|urlencode}}">{{bookmark.title}}</a></h3>
                    <form class="edit" method="post">
                        <input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="update_bookmark"><input type="hidden" name="bookmark_url" value="{{bookmark.url}}">
                        <label>Папка<select name="folder_id"><option value="">Без папки</option>{% for folder in folders %}<option value="{{folder.id}}" {{'selected' if bookmark.folder_id == folder.id else ''}}>{{folder.name}}</option>{% endfor %}</select></label>
                        <label>Заметка<textarea name="note" maxlength="5000" placeholder="Что важно в этой публикации?">{{bookmark.note}}</textarea></label>
                        <button class="primary" type="submit">Сохранить</button>
                    </form>
                    <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="remove_bookmark"><input type="hidden" name="bookmark_url" value="{{bookmark.url}}"><button class="remove" type="submit">Удалить из закладок</button></form>
                </article>
                {% endfor %}
            {% else %}<div class="empty"><strong>Здесь пока пусто</strong><span>Нажми ♡ у новости в ленте, чтобы сохранить её.</span></div>{% endif %}
        </section>
    </div>
</main></body></html>
"""


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Монитор — новости</title>
    <style>
        :root{
            --paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;
            --line:#d8d1c5;--coral:#e44f45;--coral-dark:#c93c35;
            --green:#3e7655;--amber:#e3992a
        }
        *{box-sizing:border-box}
        html{background:var(--paper)}
        body{
            margin:0;color:var(--ink);
            font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif;
            background:radial-gradient(circle at 0 0,rgba(255,255,255,.86),transparent 34rem),var(--paper)
        }
        a{color:inherit;text-decoration:none}
        button,input,select{font:inherit}
        button,select{cursor:pointer}
        button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{
            outline:3px solid rgba(228,79,69,.22);outline-offset:2px
        }
        .shell{width:min(1500px,calc(100% - 64px));margin:auto;padding-bottom:80px}
        .topbar{
            min-height:86px;border-bottom:1px solid var(--line);
            display:grid;grid-template-columns:auto minmax(300px,1fr) auto;
            align-items:center;gap:26px
        }
        .brand{
            position:relative;z-index:6;display:inline-flex;align-items:center;
            min-height:52px;font-size:30px;font-weight:780;letter-spacing:-.05em
        }
        .brand-text{transition:opacity .18s,transform .18s}
        .brand-easter-logo{
            position:absolute;left:-12px;top:50%;width:180px;height:auto;
            opacity:0;pointer-events:none;mix-blend-mode:multiply;
            filter:drop-shadow(0 10px 18px rgba(16,21,28,.2));
            transform:translateY(-50%) scale(.2) rotate(-14deg);
            transform-origin:38% 50%
        }
        .brand.easter-active .brand-text{opacity:0;transform:scale(.82)}
        .brand.easter-active .brand-easter-logo{
            animation:brand-easter-pop 4.2s cubic-bezier(.2,.85,.24,1) both
        }
        @keyframes brand-easter-pop{
            0%{opacity:0;transform:translateY(-50%) scale(.2) rotate(-14deg)}
            12%{opacity:1;transform:translateY(-50%) scale(1.12) rotate(4deg)}
            20%,82%{opacity:1;transform:translateY(-50%) scale(1) rotate(0)}
            92%{opacity:1;transform:translateY(-50%) scale(1.05) rotate(-3deg)}
            100%{opacity:0;transform:translateY(-50%) scale(.25) rotate(12deg)}
        }
        .site-sections{height:86px;display:flex;align-items:stretch;justify-content:center;gap:26px}
        .site-section{
            position:relative;padding:0 3px;display:flex;align-items:center;gap:7px;
            color:var(--muted);font-size:15px;font-weight:680;white-space:nowrap
        }
        .site-section:after{
            content:"";position:absolute;left:0;right:0;bottom:-1px;height:3px;
            background:var(--coral);transform:scaleX(0);transition:transform .18s
        }
        .site-section.active{color:var(--ink)}
        .site-section.active:after{transform:scaleX(1)}
        .topbar-tools{display:flex;align-items:center;gap:22px}
        .clocks{display:flex;align-items:center;gap:14px}
        .clock-card{display:grid;grid-template-columns:38px auto;align-items:center;gap:9px}
        .clock-face{position:relative;width:38px;height:38px;border:1px solid #a9a094;border-radius:50%;background:var(--surface)}
        .clock-face:before{content:"";position:absolute;inset:3px;border-radius:50%;background:repeating-conic-gradient(from -1deg,#8c8479 0 1deg,transparent 1deg 30deg)}
        .hand{position:absolute;z-index:2;left:50%;bottom:50%;width:2px;border-radius:2px;background:var(--ink);transform-origin:50% 100%}
        .hand.hour{height:10px;transform:translateX(-50%) rotate(var(--hour))}
        .hand.minute{height:14px;transform:translateX(-50%) rotate(var(--minute))}
        .hand.second{width:1px;height:15px;background:var(--coral);transform:translateX(-50%) rotate(var(--second))}
        .clock-face:after{content:"";position:absolute;z-index:3;left:50%;top:50%;width:5px;height:5px;border-radius:50%;background:var(--coral);transform:translate(-50%,-50%)}
        .clock-copy{min-width:72px}.clock-city{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
        .clock-time{display:block;margin-top:2px;font-size:13px;font-weight:680;font-variant-numeric:tabular-nums}
        .account-status{display:grid;justify-items:end;gap:6px;min-width:205px}
        .health{
            min-height:28px;display:flex;align-items:center;gap:8px;padding:0 10px;
            color:var(--green);border:1px solid rgba(62,118,85,.38);
            border-radius:5px;background:rgba(255,252,246,.55);font-size:10px;font-weight:650;text-decoration:none
        }
        .health.warning{color:#9b691e;border-color:rgba(227,153,42,.55)}
        .health-dot{width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 0 3px rgba(62,118,85,.09)}
        .account{display:flex;align-items:center;gap:9px;color:#5e574e;font-size:12px;white-space:nowrap}
        .account-copy{display:grid;line-height:1.2}.account-copy strong{font-size:12px}.account-copy small{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em}
        .logout{width:30px;height:30px;padding:0;border:1px solid var(--line);border-radius:50%;color:var(--muted);background:var(--surface);cursor:pointer}.logout:hover{color:var(--coral);border-color:var(--coral)}
        .intro{padding-top:38px;border-bottom:1px solid var(--line)}
        .eyebrow{margin:0 0 10px;color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
        h1{margin:0;font-size:clamp(38px,4vw,58px);line-height:1;letter-spacing:-.055em;font-weight:720}
        .tabs{display:flex;gap:28px;margin-top:28px}
        .tab{position:relative;padding:0 2px 16px;color:var(--muted);font-size:17px;font-weight:610}
        .tab:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:3px;background:var(--coral);transform:scaleX(0);transition:transform .18s}
        .tab.active{color:var(--ink)}.tab.active:after{transform:scaleX(1)}
        .toolbar{display:flex;gap:14px;padding:22px 0}
        .search,.source-select,.tool-button{
            height:52px;border:1px solid #c9c1b5;border-radius:6px;
            background:rgba(255,252,246,.58)
        }
        .search,.source-select{display:flex;align-items:center;gap:12px;padding:0 16px}
        .search{flex:1 1 520px}.source-select{flex:0 1 370px}
        .search-icon{font-size:25px;line-height:1}
        .search input{width:100%;border:0;outline:0;color:var(--ink);background:transparent;font-size:16px}
        .search input::placeholder{color:#918b81}
        .source-select select{width:100%;border:0;outline:0;color:var(--ink);background:transparent}
        .tool-button{
            min-width:142px;padding:0 18px;display:flex;align-items:center;justify-content:center;
            gap:10px;color:#554f48;transition:.16s
        }
        .tool-button:hover,.tool-button.active{color:var(--coral-dark);border-color:rgba(228,79,69,.55);background:#fff8f2}
        .saved-count{min-width:20px;padding:2px 6px;color:#fff;border-radius:999px;background:var(--coral);font-size:11px}
        .content-grid{display:grid;grid-template-columns:minmax(0,2.15fr) minmax(280px,.85fr);gap:22px;align-items:start}
        .feed,.panel{border:1px solid var(--line);border-radius:7px;background:rgba(255,252,246,.76)}
        .feed{overflow:hidden}
        .feed-heading{
            min-height:58px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;
            border-bottom:1px solid var(--line)
        }
        .feed-heading h2,.panel h2{margin:0;font-size:16px;font-weight:720}
        .feed-heading span{color:var(--muted);font-size:12px}
        .pagination{
            min-height:70px;padding:12px 20px;display:flex;align-items:center;
            justify-content:center;gap:7px;border-top:1px solid var(--line)
        }
        .page-link,.page-current{
            min-width:38px;height:38px;padding:0 11px;display:inline-flex;
            align-items:center;justify-content:center;border:1px solid var(--line);
            border-radius:5px;background:var(--surface);font-size:13px;font-weight:650
        }
        .page-link:hover{color:var(--coral-dark);border-color:rgba(228,79,69,.55);background:#fff8f2}
        .page-current{color:#fff;border-color:var(--coral);background:var(--coral)}
        .page-gap{padding:0 4px;color:var(--muted)}
        .news-card{
            position:relative;padding:24px 58px 24px 28px;border-bottom:1px solid var(--line);
            transition:background .17s
        }
        .news-card:last-child{border-bottom:0}.news-card:hover{background:#fff8f2}
        .news-card.match{border-left:5px solid var(--coral);padding-left:23px}
        .match-label{
            width:max-content;max-width:100%;margin-bottom:14px;padding:5px 9px;
            color:var(--coral-dark);border:1px solid rgba(228,79,69,.42);
            border-radius:5px;background:rgba(255,248,242,.65);font-size:12px;font-weight:650
        }
        .save{
            position:absolute;top:20px;right:20px;width:36px;height:36px;border:0;
            color:#766f65;background:transparent;font-size:25px;transition:.14s
        }
        .save:hover{transform:translateY(-1px)}.save.active{color:var(--coral)}
        .meta{display:flex;align-items:center;gap:10px;color:#6d675f;font-size:13px;font-weight:560}
        .meta i{width:1px;height:14px;background:var(--line)}
        .news-card h3{
            max-width:920px;margin:12px 0 0;font-size:clamp(20px,2.1vw,29px);
            line-height:1.18;letter-spacing:-.035em;font-weight:720
        }
        .news-card h3 a:hover{color:var(--coral-dark)}
        .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:15px}
        .chips span{padding:5px 9px;color:var(--coral-dark);border:1px solid rgba(228,79,69,.4);border-radius:5px;background:#fffaf5;font-size:12px}
        .empty{min-height:300px;display:grid;place-content:center;gap:8px;color:var(--muted);text-align:center}
        .empty strong{color:var(--ink)}
        .sidebar{display:grid;gap:16px}.panel{overflow:hidden}
        .panel-title{min-height:58px;padding:0 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line)}
        .panel-title-actions{display:flex;align-items:center;gap:8px}
        .panel-title button{border:0;color:var(--muted);background:transparent}
        .panel-title .collapse-button{font-size:20px}
        .mark-all-read{padding:5px 7px;border-radius:4px!important;font-size:10px;text-transform:uppercase;letter-spacing:.04em}
        .mark-all-read:hover{color:var(--coral-dark);background:#fff3ed}
        .source-order-toggle{padding:5px 7px!important;border-radius:4px!important;font-size:10px;text-transform:uppercase;letter-spacing:.04em}
        .source-order-toggle:hover,.source-order-toggle[aria-pressed="true"]{color:var(--coral-dark);background:#fff3ed}
        .source-list{padding:10px 0}
        .source-row{
            width:100%;min-height:40px;display:flex;align-items:center;
            color:#4f4a43;background:transparent;font-size:13px
        }
        .source-row:hover{background:#fff8f2}
        .source-link{
            min-width:0;min-height:40px;padding:0 7px 0 18px;display:grid;flex:1;
            grid-template-columns:20px minmax(0,1fr) auto auto;align-items:center;
            gap:9px;text-align:left
        }
        .source-link>span:nth-child(2){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .check{width:16px;height:16px;display:grid;place-items:center;color:#fff;border:1px solid #bdb5a9;border-radius:3px;font-size:11px}
        .source-row.active .check{border-color:var(--coral);background:var(--coral)}
        .source-row b{min-width:28px;padding:3px 5px;color:#827b71;border:1px solid var(--line);border-radius:5px;background:#f8f4ed;text-align:center;font-size:10px;font-weight:500}
        .source-drag-handle{display:none;flex:0 0 22px;color:#aaa196;text-align:center;font-size:13px;letter-spacing:-2px;cursor:grab;user-select:none}
        .source-list.order-editing .sortable-source{cursor:grab;background:#fffbf6}
        .source-list.order-editing .sortable-source:hover{background:#fff4ea}
        .source-list.order-editing .source-drag-handle{display:block}
        .source-list.order-editing .source-link{padding-left:4px;pointer-events:none}
        .sortable-source.source-dragging{opacity:.38}
        .sortable-source.source-drag-over{box-shadow:inset 0 2px 0 var(--coral)}
        .unread-count{min-width:28px;color:var(--green);text-align:right;font-size:11px;font-weight:700}
        .unread-count:empty{display:none}
        .unread-label{margin-left:auto;padding:3px 6px;color:var(--green);border:1px solid rgba(62,118,85,.35);border-radius:4px;background:rgba(62,118,85,.08);font-size:10px;text-transform:uppercase;letter-spacing:.04em}
        .coverage{padding-top:18px}.coverage>h2,.coverage dl{padding:0 20px}
        .coverage dl{margin:14px 0 16px}.coverage dl div{min-height:31px;display:flex;align-items:center;justify-content:space-between}
        .coverage dt,.coverage dd{margin:0;color:#686158;font-size:12px}.coverage dt{display:flex;align-items:center;gap:8px}.coverage dd{color:var(--ink)}
        .problem-sources{margin:0;padding:12px 20px 14px;border-top:1px solid var(--line)}
        .problem-sources h3{margin:0 0 9px;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
        .problem-source{min-height:28px;display:grid;grid-template-columns:7px minmax(0,1fr) auto;align-items:center;gap:8px;font-size:11px}
        .problem-source span:nth-child(2){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .problem-source em{color:var(--muted);font-style:normal}
        .dot{width:6px;height:6px;border-radius:50%}.green{background:var(--green)}.amber{background:var(--amber)}.coral{background:var(--coral)}
        .coverage .green-text{color:var(--green)}
        .coverage footer{min-height:50px;padding:0 20px;display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--line);color:#8a8379;font-size:10px}
        .hidden{display:none!important}
        .keyword-backdrop{position:fixed;z-index:20;inset:0;display:grid;place-items:center;padding:20px;background:rgba(23,24,21,.48)}
        .keyword-dialog{width:min(580px,100%);max-height:min(680px,88vh);overflow:auto;padding:25px;border:1px solid var(--line);border-radius:8px;background:var(--surface);box-shadow:0 24px 80px rgba(0,0,0,.2)}
        .dialog-head{display:flex;align-items:start;justify-content:space-between;gap:20px}.dialog-head h2{margin:0;font-size:25px}.dialog-head p{margin:7px 0 0;color:var(--muted);font-size:13px}
        .dialog-close{border:0;background:transparent;font-size:25px}.keyword-form{display:flex;gap:10px;margin:22px 0}
        .keyword-form input{min-width:0;flex:1;height:46px;padding:0 13px;border:1px solid #c9c1b5;border-radius:6px;background:#fff}
        .primary{height:46px;padding:0 18px;border:0;border-radius:6px;color:white;background:var(--coral)}
        .keyword-list{display:flex;flex-wrap:wrap;gap:9px}.keyword-chip{display:flex;align-items:center;gap:7px;padding:7px 8px 7px 11px;border:1px solid var(--line);border-radius:999px;background:#fff}
        .keyword-chip button{width:22px;height:22px;padding:0;border:0;border-radius:50%;color:var(--coral-dark);background:#fff1ed}.form-message{min-height:20px;margin:10px 0 0;color:var(--coral-dark);font-size:13px}
        @media(max-width:1050px){
            .topbar{grid-template-columns:auto 1fr;padding-top:14px}
            .topbar-tools{justify-self:end}
            .site-sections{
                width:100%;height:50px;grid-column:1/-1;grid-row:2;
                justify-content:flex-start
            }
            .toolbar{flex-wrap:wrap}.search{flex-basis:55%}.source-select{flex:1 1 35%}.content-grid{grid-template-columns:1fr}
            .sidebar{grid-template-columns:1fr 1fr;grid-row:1}
        }
        @media(max-width:680px){
            .shell{width:min(100% - 28px,1500px)}.topbar{min-height:72px}
            .topbar{align-items:flex-start;padding:17px 0 0;gap:12px}
            .topbar-tools{align-items:flex-end;flex-direction:column-reverse;gap:10px}
            .site-sections{gap:18px;overflow-x:auto}.site-section{font-size:13px}
            .clock-copy{display:none}
            .account-copy{display:none}
            .brand-easter-logo{left:-7px;width:140px}
            .account-status{min-width:0}.health{min-height:27px;padding:0 9px;font-size:9px}
            .toolbar{display:grid;grid-template-columns:1fr}.sidebar{grid-template-columns:1fr}.news-card{padding:20px 48px 20px 18px}
            .news-card.match{padding-left:13px}.feed-heading{padding:0 18px}.news-card h3{font-size:21px}
            .pagination{padding:12px 8px;gap:4px}.page-link,.page-current{min-width:34px;padding:0 8px}
            .meta{align-items:flex-start;flex-direction:column;gap:4px}.meta i{display:none}
        }
        @media(prefers-reduced-motion:reduce){
            .brand-text{transition:none}
            .brand.easter-active .brand-easter-logo{animation:none;opacity:1;transform:translateY(-50%)}
        }
    </style>
</head>
<body>
<main class="shell">
    <header class="topbar">
        <a class="brand" id="brand-home" href="/" aria-label="На главную">
            <span class="brand-text">Монитор</span>
            <img
                class="brand-easter-logo"
                src="{{url_for('static', filename='kyodo-easter-egg.webp')}}"
                alt=""
            >
        </a>
        <nav class="site-sections" aria-label="Основные разделы">
            <a class="site-section {{'active' if source_group == 'government' else ''}}" href="/">
                Госструктуры
            </a>
            <a class="site-section {{'active' if source_group == 'agencies' else ''}}" href="/agencies">
                Информагентства
            </a>
            <a class="site-section {{'active' if source_group == 'newspapers' else ''}}" href="/newspapers">
                Газеты
            </a>
            <a class="site-section" href="/bookmarks">
                Закладки
            </a>
        </nav>
        <div class="topbar-tools">
            <div class="clocks">
                <div class="clock-card" data-clock="Europe/Moscow">
                    <div class="clock-face"><i class="hand hour"></i><i class="hand minute"></i><i class="hand second"></i></div>
                    <div class="clock-copy"><span class="clock-city">Москва</span><time class="clock-time">--:--:--</time></div>
                </div>
                <div class="clock-card" data-clock="Asia/Tokyo">
                    <div class="clock-face"><i class="hand hour"></i><i class="hand minute"></i><i class="hand second"></i></div>
                    <div class="clock-copy"><span class="clock-city">Токио</span><time class="clock-time">--:--:--</time></div>
                </div>
            </div>
            <div class="account-status">
                <div class="account">
                    <a class="account-copy" href="/account" title="Настройки аккаунта">
                        <strong>{{current_user.username}}</strong>
                        <small>{{'Администратор' if current_user.role == 'admin' else 'Пользователь'}}</small>
                    </a>
                    <form method="post" action="/logout">
                        <input type="hidden" name="csrf_token" value="{{csrf_token}}">
                        <button class="logout" type="submit" aria-label="Выйти">↪</button>
                    </form>
                </div>
                {% if current_user.role == 'admin' %}<a class="health {{'warning' if health_ok < health_total else ''}}" href="/admin/sources" title="Открыть управление источниками">
                    <span class="health-dot"></span>
                    {{health_ok}} из {{health_total}} источников работают
                </a>{% else %}<div class="health {{'warning' if health_ok < health_total else ''}}"><span class="health-dot"></span>{{health_ok}} из {{health_total}} источников работают</div>{% endif %}
            </div>
        </div>
    </header>

    <section class="intro">
        <p class="eyebrow">{{group_eyebrow}}</p>
        <h1>{{group_title}}</h1>
        <nav class="tabs">
            <a class="tab {{'active' if mode == 'all' else ''}}" href="{{group_home}}">Все</a>
            <a class="tab {{'active' if mode == 'found' else ''}}" href="{{group_found}}">Совпадения</a>
        </nav>
    </section>

    <section class="toolbar">
        <form class="search" method="get" action="{{current_path}}">
            <span class="search-icon">⌕</span>
            <input id="news-search" name="q" value="{{search_query}}"
                   placeholder="Поиск по заголовкам · Enter" autocomplete="off">
        </form>
        <label class="source-select">
            <span>▱</span>
            <select onchange="goToSource(this.value)">
                <option value="">Все источники</option>
                {% for src, count in sources %}
                <option value="{{src}}" {{'selected' if src == source_filter else ''}}>{{src}} — {{count}}</option>
                {% endfor %}
            </select>
        </label>
        <button class="tool-button" id="keywords-open" type="button">✣ Ключевые слова</button>
        <a class="tool-button" href="/bookmarks">
            ♡ Закладки <span class="saved-count {{'hidden' if not bookmark_count else ''}}" id="saved-count">{{bookmark_count}}</span>
        </a>
    </section>

    <div class="content-grid">
        <section class="feed">
            <header class="feed-heading">
                <h2>{{'Совпадения' if mode == 'found' else ('Источник: ' + source_filter if source_filter else 'Последние публикации')}}</h2>
                <span id="visible-count" data-default="{{page_label}}">{{page_label}}</span>
            </header>
            <div id="empty-state" class="empty hidden">
                <strong>Ничего не найдено</strong>
                <span>Измени запрос или отключи фильтр.</span>
            </div>
            <div id="news-list">
            {% for item in news %}
                <article class="news-card {{'match' if item.keywords else ''}}"
                         data-id="{{item.url}}" data-source="{{item.source}}"
                         data-search="{{(item.title + ' ' + item.source + ' ' + (item.keywords|join(' ')))|lower}}">
                    {% if item.keywords %}
                    <div class="match-label">✣ Совпадение с ключевыми словами</div>
                    {% endif %}
                    <button class="save" type="button" aria-label="Сохранить новость" data-save="{{item.url}}">♡</button>
                    <div class="meta">
                        <span>{{item.source}}</span><i></i>
                        {% if item.section %}<span>{{item.section}}</span><i></i>{% endif %}
                        <time>
                            {% if item.date %}{{item.date}}
                            {% elif item.parsed_date %}Получено {{item.parsed_date}}
                            {% endif %}
                        </time>
                        <span class="unread-label hidden">Новая</span>
                    </div>
                    {% if item.source in ('МИД РФ', 'Минсельхоз') %}
                    <h3>
                        <a href="{{item.url}}" target="_blank" rel="noopener noreferrer" data-read-url="{{item.url}}">
                            {{item.title}}
                        </a>
                    </h3>
                    {% else %}
                    <h3><a href="/article?url={{item.url|urlencode}}" data-read-url="{{item.url}}">{{item.title}}</a></h3>
                    {% endif %}
                    {% if item.keywords %}
                    <div class="chips">{% for keyword in item.keywords %}<span>{{keyword}}</span>{% endfor %}</div>
                    {% endif %}
                </article>
            {% endfor %}
            </div>
            {% if page_count > 1 %}
            <nav class="pagination" aria-label="Страницы новостей">
                {% if previous_url %}
                <a class="page-link" href="{{previous_url}}" rel="prev">←</a>
                {% endif %}
                {% for link in page_links %}
                    {% if link.gap %}
                    <span class="page-gap">…</span>
                    {% elif link.current %}
                    <span class="page-current" aria-current="page">{{link.number}}</span>
                    {% else %}
                    <a class="page-link" href="{{link.url}}">{{link.number}}</a>
                    {% endif %}
                {% endfor %}
                {% if next_url %}
                <a class="page-link" href="{{next_url}}" rel="next">→</a>
                {% endif %}
            </nav>
            {% endif %}
        </section>

        <aside class="sidebar" id="sidebar">
            <section class="panel">
                <header class="panel-title">
                    <h2>Источники</h2>
                    <div class="panel-title-actions">
                        <button class="source-order-toggle" id="source-order-toggle" type="button" aria-pressed="false">Изменить</button>
                        <button class="mark-all-read" id="mark-all-read" type="button">Прочитать всё</button>
                        <button class="collapse-button" id="collapse-sources" type="button" aria-label="Свернуть список">−</button>
                    </div>
                </header>
                <div class="source-list" id="source-list">
                    <div class="source-row {{'active' if not source_filter else ''}}">
                        <a class="source-link" href="{{group_home}}">
                            <span class="check">{{'✓' if not source_filter else ''}}</span>
                            <span>Все источники</span>
                            <b>{{total}}</b>
                            <span class="unread-count" data-unread-source="__all__"></span>
                        </a>
                    </div>
                    {% for src, count in sources %}
                    <div class="source-row sortable-source {{'active' if src == source_filter else ''}}" data-source-row data-source-name="{{src}}">
                        <span class="source-drag-handle" aria-hidden="true">⋮⋮</span>
                        <a class="source-link" href="{{source_base}}{{src|urlencode}}">
                            <span class="check">{{'✓' if src == source_filter else ''}}</span>
                            <span>{{src}}</span>
                            <b>{{count}}</b>
                            <span class="unread-count" data-unread-source="{{src}}"></span>
                        </a>
                    </div>
                    {% endfor %}
                </div>
            </section>

            {% if show_admin_diagnostics %}
            <section class="panel coverage">
                <h2>Сводка покрытия</h2>
                <dl>
                    <div><dt>Источников всего</dt><dd>{{health_total}}</dd></div>
                    <div><dt><span class="dot green"></span>Работают</dt><dd class="green-text">{{health_ok}}</dd></div>
                    <div><dt><span class="dot amber"></span>Пустая выдача</dt><dd>{{health_empty}}</dd></div>
                    <div><dt><span class="dot coral"></span>Ошибки парсинга</dt><dd>{{health_errors}}</dd></div>
                </dl>
                {% if problem_sources %}
                <div class="problem-sources">
                    <h3>Требуют внимания</h3>
                    {% for item in problem_sources %}
                    <div class="problem-source" title="{{item.error or item.checked_at}}">
                        <span class="dot {{'amber' if item.availability == 'temporary' else 'coral'}}"></span>
                        <span>{{item.source}}</span>
                        <em>{% if item.availability == 'temporary' %}временно{% elif item.status == 'error' %}ошибка{% else %}недоступен{% endif %}</em>
                    </div>
                    {% endfor %}
                </div>
                {% endif %}
                <footer><span>Обновлено {{status_time or '—'}}</span><span>↻</span></footer>
            </section>
            {% endif %}
        </aside>
    </div>
</main>
<div class="keyword-backdrop hidden" id="keyword-modal" role="dialog" aria-modal="true" aria-labelledby="keyword-title">
    <section class="keyword-dialog">
        <header class="dialog-head">
            <div><h2 id="keyword-title">Ключевые слова</h2><p>Изменения сразу пересоберут раздел «Совпадения».</p></div>
            <button class="dialog-close" id="keywords-close" type="button" aria-label="Закрыть">×</button>
        </header>
        <form class="keyword-form" id="keyword-form">
            <input id="keyword-input" maxlength="80" placeholder="Например: Приморье" autocomplete="off">
            <button class="primary" type="submit">Добавить</button>
        </form>
        <div class="keyword-list" id="keyword-list"></div>
        <p class="form-message" id="keyword-message"></p>
    </section>
</div>
<script>
    const cards = [...document.querySelectorAll('.news-card')];
    const search = document.getElementById('news-search');
    const visibleCount = document.getElementById('visible-count');
    const emptyState = document.getElementById('empty-state');
    const savedCount = document.getElementById('saved-count');
    const brandHome = document.getElementById('brand-home');
    const newsIndex = {{news_index|tojson}};
    const groupHome = {{group_home|tojson}};
    const sourceBase = {{source_base|tojson}};
    const currentSourceGroup = {{source_group|tojson}};
    let saved = new Set({{saved_urls|tojson}});
    const legacySavedStorageKey = 'monitor-saved';
    const unreadStorageKey = 'monitor-unread-v1';
    let unreadState;
    let brandClicks = 0;
    let brandClickTimer = null;
    let brandHideTimer = null;

    brandHome.addEventListener('click', event => {
        if(
            event.detail === 0 || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        ){
            return;
        }

        event.preventDefault();
        brandClicks += 1;
        clearTimeout(brandClickTimer);

        if(brandClicks >= 5){
            brandClicks = 0;
            clearTimeout(brandHideTimer);
            brandHome.classList.remove('easter-active');
            void brandHome.offsetWidth;
            brandHome.classList.add('easter-active');
            brandHideTimer = setTimeout(
                () => brandHome.classList.remove('easter-active'),
                4200
            );
            return;
        }

        brandClickTimer = setTimeout(() => {
            if(brandClicks === 1){
                window.location.assign(brandHome.href);
            }
            brandClicks = 0;
        }, 650);
    });

    try{
        unreadState = JSON.parse(localStorage.getItem(unreadStorageKey) || 'null');
    }catch(error){
        unreadState = null;
    }

    if(!unreadState || !Array.isArray(unreadState.known) || !Array.isArray(unreadState.unread)){
        // Первый запуск: существующие материалы считаются уже прочитанными.
        unreadState = {known: newsIndex.map(item => item.url), unread: []};
    }else{
        const known = new Set(unreadState.known);
        const unreadNews = new Set(unreadState.unread);
        newsIndex.forEach(item => {
            if(item.url && !known.has(item.url)){
                known.add(item.url);
                unreadNews.add(item.url);
            }
        });
        unreadState = {known: [...known], unread: [...unreadNews]};
    }
    localStorage.setItem(unreadStorageKey, JSON.stringify(unreadState));
    let unread = new Set(unreadState.unread);

    function saveUnread(){
        unreadState.unread = [...unread];
        localStorage.setItem(unreadStorageKey, JSON.stringify(unreadState));
    }

    function refreshUnread(){
        const counts = {};
        let groupUnreadCount = 0;
        newsIndex.forEach(item => {
            if(unread.has(item.url)){
                groupUnreadCount++;
                counts[item.source] = (counts[item.source] || 0) + 1;
            }
        });
        document.querySelectorAll('[data-unread-source]').forEach(badge => {
            const source = badge.dataset.unreadSource;
            const count = source === '__all__' ? groupUnreadCount : (counts[source] || 0);
            badge.textContent = count ? '+' + count : '';
        });
        cards.forEach(card => {
            const label = card.querySelector('.unread-label');
            if(label) label.classList.toggle('hidden', !unread.has(card.dataset.id));
        });
    }

    function markRead(url){
        if(!unread.delete(url)) return;
        saveUnread();
        refreshUnread();
    }

    function refreshSavedIcons(){
        document.querySelectorAll('[data-save]').forEach(button => {
            const active = saved.has(button.dataset.save);
            button.classList.toggle('active', active);
            button.textContent = active ? '♥' : '♡';
            button.setAttribute('aria-label', active ? 'Удалить из сохранённых' : 'Сохранить новость');
        });
        savedCount.textContent = saved.size;
        savedCount.classList.toggle('hidden', saved.size === 0);
    }

    async function migrateLegacySaved(){
        let legacySaved = [];
        try{
            const stored = JSON.parse(localStorage.getItem(legacySavedStorageKey) || '[]');
            if(Array.isArray(stored)) legacySaved = stored.filter(url => typeof url === 'string' && url);
        }catch(error){
            return;
        }
        if(!legacySaved.length) return;
        try{
            const response = await fetch('/api/bookmarks', {
                method:'POST',
                headers:{
                    'Content-Type':'application/json',
                    'X-CSRF-Token': {{csrf_token|tojson}}
                },
                body:JSON.stringify({urls:legacySaved})
            });
            if(!response.ok) return;
            const data = await response.json();
            saved = new Set(data.urls || []);
            localStorage.removeItem(legacySavedStorageKey);
            refreshSavedIcons();
        }catch(error){
            // При временной сетевой ошибке старые данные остаются в браузере,
            // поэтому перенос безопасно повторится при следующем открытии.
        }
    }
    function applyFilters(){
        const query = search.value.trim().toLowerCase();
        let count = 0;
        cards.forEach(card => {
            const matchesText = !query || card.dataset.search.includes(query);
            const visible = matchesText;
            card.classList.toggle('hidden', !visible);
            if(visible) count++;
        });
        visibleCount.textContent = !query
            ? visibleCount.dataset.default
            : count + ' материалов';
        emptyState.classList.toggle('hidden', count !== 0);
    }
    document.querySelectorAll('[data-save]').forEach(button => {
        button.addEventListener('click', async () => {
            const id = button.dataset.save;
            const removing = saved.has(id);
            button.disabled = true;
            try{
                const response = await fetch('/api/bookmarks', {
                    method: removing ? 'DELETE' : 'POST',
                    headers:{
                        'Content-Type':'application/json',
                        'X-CSRF-Token': {{csrf_token|tojson}}
                    },
                    body:JSON.stringify({url:id})
                });
                if(!response.ok) throw new Error('Не удалось изменить закладку');
                removing ? saved.delete(id) : saved.add(id);
                refreshSavedIcons();
            }catch(error){
                window.alert(error.message);
            }finally{
                button.disabled = false;
            }
        });
    });
    document.querySelectorAll('[data-read-url]').forEach(link => {
        link.addEventListener('click', () => markRead(link.dataset.readUrl));
    });
    document.getElementById('mark-all-read').addEventListener('click', () => {
        newsIndex.forEach(item => unread.delete(item.url));
        saveUnread();
        refreshUnread();
    });
    search.addEventListener('input', applyFilters);
    document.getElementById('collapse-sources').addEventListener('click', event => {
        const list = document.getElementById('source-list');
        list.classList.toggle('hidden');
        event.currentTarget.textContent = list.classList.contains('hidden') ? '+' : '−';
    });
    const sourceList = document.getElementById('source-list');
    function orderedSourceRows(){
        return [...sourceList.querySelectorAll('[data-source-row]')];
    }
    async function saveSourceOrder(){
        const rows = orderedSourceRows();
        const response = await fetch('/api/source-order', {
            method:'POST',
            headers:{
                'Content-Type':'application/json',
                'X-CSRF-Token': {{csrf_token|tojson}}
            },
            body:JSON.stringify({
                source_group:currentSourceGroup,
                sources:rows.map(row => row.dataset.sourceName)
            })
        });
        if(!response.ok){
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || 'Не удалось сохранить порядок источников');
        }
    }
    const sourceOrderToggle = document.getElementById('source-order-toggle');
    let draggedSourceRow = null;
    let sourceOrderChanged = false;
    function setSourceOrderEditing(editing){
        sourceList.classList.toggle('order-editing', editing);
        sourceOrderToggle.setAttribute('aria-pressed', String(editing));
        sourceOrderToggle.textContent = editing ? 'Готово' : 'Изменить';
        orderedSourceRows().forEach(row => row.draggable = editing);
    }
    sourceOrderToggle.addEventListener('click', async () => {
        const editing = sourceList.classList.contains('order-editing');
        if(!editing){
            sourceOrderChanged = false;
            setSourceOrderEditing(true);
            return;
        }
        sourceOrderToggle.disabled = true;
        try{
            if(sourceOrderChanged) await saveSourceOrder();
            setSourceOrderEditing(false);
        }catch(error){
            window.alert(error.message);
            window.location.reload();
        }finally{
            sourceOrderToggle.disabled = false;
        }
    });
    sourceList.addEventListener('dragstart', event => {
        const row = event.target.closest('[data-source-row]');
        if(!row || !sourceList.classList.contains('order-editing')) return;
        draggedSourceRow = row;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', row.dataset.sourceName);
        requestAnimationFrame(() => row.classList.add('source-dragging'));
    });
    sourceList.addEventListener('dragover', event => {
        if(!draggedSourceRow) return;
        const target = event.target.closest('[data-source-row]');
        if(!target || target === draggedSourceRow) return;
        event.preventDefault();
        orderedSourceRows().forEach(row => row.classList.remove('source-drag-over'));
        target.classList.add('source-drag-over');
        const before = event.clientY < target.getBoundingClientRect().top + target.offsetHeight / 2;
        sourceList.insertBefore(draggedSourceRow, before ? target : target.nextSibling);
        sourceOrderChanged = true;
    });
    sourceList.addEventListener('drop', event => {
        if(draggedSourceRow) event.preventDefault();
    });
    sourceList.addEventListener('dragend', () => {
        orderedSourceRows().forEach(row => row.classList.remove('source-dragging', 'source-drag-over'));
        draggedSourceRow = null;
    });
    function goToSource(source){
        window.location.href = source ? sourceBase + encodeURIComponent(source) : groupHome;
    }
    function updateClocks(){
        document.querySelectorAll('[data-clock]').forEach(clock => {
            const parts = Object.fromEntries(
                new Intl.DateTimeFormat('ru-RU', {
                    timeZone: clock.dataset.clock, hour:'2-digit', minute:'2-digit',
                    second:'2-digit', hourCycle:'h23'
                }).formatToParts(new Date()).map(part => [part.type, part.value])
            );
            const hour = Number(parts.hour), minute = Number(parts.minute), second = Number(parts.second);
            clock.style.setProperty('--hour', (hour % 12 * 30 + minute * .5) + 'deg');
            clock.style.setProperty('--minute', (minute * 6 + second * .1) + 'deg');
            clock.style.setProperty('--second', (second * 6) + 'deg');
            clock.querySelector('.clock-time').textContent = `${parts.hour}:${parts.minute}:${parts.second}`;
        });
    }
    updateClocks(); setInterval(updateClocks, 1000);

    const keywordModal = document.getElementById('keyword-modal');
    const keywordList = document.getElementById('keyword-list');
    const keywordMessage = document.getElementById('keyword-message');
    function renderKeywords(words){
        keywordList.replaceChildren(...words.map(word => {
            const chip = document.createElement('span'); chip.className = 'keyword-chip';
            const label = document.createElement('span'); label.textContent = word;
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
            remove.setAttribute('aria-label', 'Удалить ' + word);
            remove.addEventListener('click', () => changeKeyword('DELETE', word));
            chip.append(label, remove); return chip;
        }));
    }
    async function loadKeywords(){
        const response = await fetch('/api/keywords');
        renderKeywords((await response.json()).keywords);
    }
    async function changeKeyword(method, keyword){
        keywordMessage.textContent = 'Обновляю совпадения…';
        const response = await fetch('/api/keywords', {
            method,
            headers:{
                'Content-Type':'application/json',
                'X-CSRF-Token': {{csrf_token|tojson}}
            },
            body:JSON.stringify({keyword})
        });
        const data = await response.json();
        if(!response.ok){ keywordMessage.textContent = data.error || 'Не удалось сохранить'; return; }
        renderKeywords(data.keywords);
        keywordMessage.textContent = `Готово: ${data.found_count} совпадений.`;
    }
    document.getElementById('keywords-open').addEventListener('click', () => {
        keywordModal.classList.remove('hidden'); loadKeywords();
        document.getElementById('keyword-input').focus();
    });
    document.getElementById('keywords-close').addEventListener('click', () => keywordModal.classList.add('hidden'));
    keywordModal.addEventListener('click', event => { if(event.target === keywordModal) keywordModal.classList.add('hidden'); });
    document.getElementById('keyword-form').addEventListener('submit', async event => {
        event.preventDefault();
        const input = document.getElementById('keyword-input');
        await changeKeyword('POST', input.value); input.value = '';
    });
    refreshSavedIcons();
    refreshUnread();
    applyFilters();
    migrateLegacySaved();
</script>
</body>
</html>
"""

ARTICLE_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{article.title}} — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}
        a{color:inherit}.shell{width:min(900px,calc(100% - 36px));margin:auto;padding:28px 0 80px}
        .back{display:inline-flex;gap:8px;color:var(--muted);text-decoration:none}.back:hover{color:var(--coral)}
        article{margin-top:24px;padding:clamp(24px,5vw,58px);border:1px solid var(--line);border-radius:8px;background:var(--surface)}
        .meta{display:flex;flex-wrap:wrap;gap:10px;color:var(--muted);font-size:13px}
        h1{margin:18px 0 30px;font-size:clamp(32px,5vw,54px);line-height:1.05;letter-spacing:-.045em}
        .body{font-family:Georgia,"Times New Roman",serif;font-size:19px;line-height:1.72}
        .body p{margin:0 0 1.15em}.notice{padding:18px;border-left:4px solid var(--coral);background:#fff4ee}
        .actions{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-top:26px}
        .original,.refresh{display:inline-flex;padding:12px 16px;border:1px solid var(--coral);border-radius:6px;color:var(--coral);background:transparent;text-decoration:none;font:600 14px Inter,Arial,sans-serif;cursor:pointer}
        .cache-note{color:var(--muted);font-size:12px}.refresh-error{margin-top:18px;color:var(--coral);font-size:13px}
    </style>
</head>
<body><main class="shell">
    <a class="back" href="{{back_url}}">← Вернуться к ленте</a>
    <article>
        <div class="meta"><span>{{item.source}}</span><span>•</span><time>{{item.date or item.parsed_date or ''}}</time></div>
        <h1>{{article.title or item.title}}</h1>
        <div class="body">
            {% if article.paragraphs %}
                {% for paragraph in article.paragraphs %}<p>{{paragraph}}</p>{% endfor %}
            {% else %}<p class="notice">{{article.error}}</p>{% endif %}
        </div>
        {% if article.refresh_error %}<div class="refresh-error">{{article.refresh_error}}</div>{% endif %}
        <div class="actions">
            <a class="original" href="{{item.url}}" target="_blank" rel="noopener noreferrer">Открыть оригинал ↗</a>
            {% if article.paragraphs %}
            <form method="post" action="/article">
                <input type="hidden" name="csrf_token" value="{{csrf_token}}">
                <input type="hidden" name="url" value="{{item.url}}">
                <input type="hidden" name="back_url" value="{{back_url}}">
                <button class="refresh" type="submit">Обновить текст</button>
            </form>
            {% endif %}
            {% if article.cached_at %}<span class="cache-note">Сохранено локально {{article.cached_at.replace('T', ' ')}}</span>{% endif %}
        </div>
    </article>
</main></body></html>
"""


def load_json(filename, default):
    # Новости теперь живут в SQLite. Имя функции оставлено прежним,
    # чтобы маршруты и тесты интерфейса не пришлось переписывать целиком.
    if filename == "all_news.json":
        return load_all_news()
    if filename == "found_news.json":
        return load_found_news()

    path = PROJECT_DIR / filename
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data
    except (OSError, json.JSONDecodeError):
        return default


def csrf_token():
    """Возвращает CSRF-токен текущей сессии, создавая его при необходимости."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def csrf_is_valid():
    """Проверяет токен для изменяющих состояние запросов."""
    if app.config.get("AUTH_DISABLED"):
        return True
    expected = str(session.get("_csrf_token", ""))
    supplied = str(
        request.form.get("csrf_token", "")
        or request.headers.get("X-CSRF-Token", "")
    )
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def current_user():
    """Возвращает вошедшего пользователя для проверок прав."""
    return getattr(g, "current_user", None)


def safe_next_url(value):
    """Разрешает возврат после входа только на локальный URL приложения."""
    value = str(value or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


@app.before_request
def load_current_user():
    """Загружает сессию и закрывает приложение от анонимного доступа."""
    if app.config.get("AUTH_DISABLED"):
        g.current_user = {
            "id": 0,
            "username": "Тест",
            "role": "admin",
            "is_active": True,
        }
        return None

    user = load_user(session.get("user_id"))
    if user and user.get("is_active"):
        g.current_user = user
    else:
        session.pop("user_id", None)
        g.current_user = None

    endpoint = request.endpoint or ""
    if endpoint == "static":
        return None

    users_exist = count_users() > 0
    if not users_exist:
        if endpoint != "setup":
            return redirect(url_for("setup"))
        return None

    if endpoint == "setup":
        return redirect(url_for("index") if g.current_user else url_for("login"))
    if endpoint == "login":
        if g.current_user:
            return redirect(url_for("index"))
        return None
    if not g.current_user:
        return redirect(
            url_for("login", next=safe_next_url(request.full_path or request.path))
        )
    return None


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """На первом запуске создаёт единственного первого администратора."""
    error = ""
    username = str(request.form.get("username", "")).strip()
    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        if password != password_confirm:
            error = "Пароли не совпадают"
        else:
            try:
                user = create_user(username, password, role="admin")
            except ValueError as creation_error:
                error = str(creation_error)
            else:
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                csrf_token()
                return redirect(url_for("index"))
    return render_template_string(
        AUTH_HTML,
        mode="setup",
        error=error,
        username=username,
        csrf_token=csrf_token(),
        next_url="/",
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    """Открывает защищённую сессию после проверки логина и пароля."""
    error = ""
    username = str(request.form.get("username", "")).strip()
    next_url = safe_next_url(request.values.get("next", "/"))
    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        user = authenticate_user(username, request.form.get("password", ""))
        if user is None:
            error = "Неверный логин или пароль"
        else:
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            csrf_token()
            return redirect(next_url)
    return render_template_string(
        AUTH_HTML,
        mode="login",
        error=error,
        username=username,
        csrf_token=csrf_token(),
        next_url=next_url,
    )


@app.post("/logout")
def logout():
    """Завершает текущую пользовательскую сессию."""
    if not csrf_is_valid():
        abort(400)
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
def account():
    """Позволяет вошедшему пользователю безопасно сменить свой пароль."""
    user = current_user()
    error = ""
    message = str(request.args.get("message", "")).strip()
    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        password_confirm = request.form.get("password_confirm", "")
        if authenticate_user(user["username"], current_password) is None:
            error = "Текущий пароль введён неверно"
        elif new_password != password_confirm:
            error = "Новые пароли не совпадают"
        else:
            try:
                set_user_password(user["id"], new_password)
            except ValueError as password_error:
                error = str(password_error)
            else:
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                csrf_token()
                return redirect(
                    url_for("account", message="Пароль успешно изменён")
                )
    return render_template_string(
        SETTINGS_HTML,
        mode="account",
        title="Мой аккаунт",
        subtitle=f"{user['username']} · "
        + ("администратор" if user["role"] == "admin" else "пользователь"),
        current_user=user,
        csrf_token=csrf_token(),
        message=message,
        error=error,
    )


@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    """Управляет аккаунтами, не удаляя связанные пользовательские данные."""
    administrator = current_user()
    if not administrator or administrator.get("role") != "admin":
        abort(403)

    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        action = str(request.form.get("action", "")).strip()
        try:
            if action == "create":
                password = request.form.get("password", "")
                if password != request.form.get("password_confirm", ""):
                    raise ValueError("Пароли нового пользователя не совпадают")
                created = create_user(
                    request.form.get("username", ""),
                    password,
                    request.form.get("role", "user"),
                )
                message = f"Пользователь {created['username']} создан"
            else:
                target = load_user(request.form.get("user_id"))
                if target is None:
                    raise ValueError("Пользователь не найден")
                if action == "role":
                    if target["id"] == administrator["id"]:
                        raise ValueError("Нельзя менять собственную роль")
                    updated = set_user_role(target["id"], request.form.get("role"))
                    message = f"Роль пользователя {updated['username']} изменена"
                elif action == "toggle":
                    if target["id"] == administrator["id"]:
                        raise ValueError("Нельзя отключить собственный аккаунт")
                    updated = set_user_active(target["id"], not target["is_active"])
                    state = "включён" if updated["is_active"] else "отключён"
                    message = f"Вход для {updated['username']} {state}"
                elif action == "password":
                    updated = set_user_password(
                        target["id"], request.form.get("password", "")
                    )
                    message = f"Пароль пользователя {updated['username']} изменён"
                else:
                    raise ValueError("Неизвестное действие")
        except ValueError as operation_error:
            return redirect(url_for("admin_users", error=str(operation_error)))
        return redirect(url_for("admin_users", message=message))

    return render_template_string(
        SETTINGS_HTML,
        mode="users",
        title="Пользователи",
        subtitle="Аккаунты, роли и доступ к Монитору",
        current_user=administrator,
        users=list_users(),
        csrf_token=csrf_token(),
        message=str(request.args.get("message", "")).strip(),
        error=str(request.args.get("error", "")).strip(),
    )


def _registered_admin_sources():
    """Возвращает источники интерфейса без старых совместимых псевдонимов."""
    groups = (
        ("Госструктуры", GOVERNMENT_SOURCES - {"Сахалинская обл."}),
        ("Информагентства", AGENCY_SOURCES),
        ("Газеты", NEWSPAPER_SOURCES),
    )
    return [
        (source, group_label)
        for group_label, names in groups
        for source in sorted(names, key=str.casefold)
    ]


@app.route("/admin/sources", methods=["GET", "POST"])
def admin_sources():
    """Показывает состояние парсеров и ставит ручные проверки в очередь."""
    administrator = current_user()
    if not administrator or administrator.get("role") != "admin":
        abort(403)

    registered = _registered_admin_sources()
    registered_names = {source for source, _group in registered}
    settings = load_source_settings()

    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        source = " ".join(str(request.form.get("source", "")).split())
        if source not in registered_names:
            return redirect(url_for("admin_sources", error="Источник не найден"))
        action = str(request.form.get("action", "")).strip()
        try:
            if action == "toggle":
                enabled = settings.get(source, {}).get("enabled", True)
                changed = set_source_enabled(source, not enabled)
                state = "возвращён в расписание" if changed["enabled"] else "поставлен на паузу"
                message = f"{source}: {state}"
            elif action == "refresh":
                if not settings.get(source, {}).get("enabled", True):
                    raise ValueError("Сначала включите источник")
                job = enqueue_parser_job(source, administrator.get("id"))
                state = "уже выполняется" if job["status"] == "running" else "поставлен в очередь"
                message = f"{source}: {state}"
            else:
                raise ValueError("Неизвестное действие")
        except ValueError as operation_error:
            return redirect(url_for("admin_sources", error=str(operation_error)))
        return redirect(url_for("admin_sources", message=message))

    status_document = load_json("parser_status.json", {})
    status_by_source = {
        item.get("source"): item
        for item in status_document.get("sources", [])
        if item.get("source")
    }
    database_by_source = source_news_statistics()
    jobs = list_parser_jobs(30)
    latest_job_by_source = {}
    for job in jobs:
        latest_job_by_source.setdefault(job["source"], job)

    status_labels = {
        "ok": "Работает",
        "empty": "Пустая выдача",
        "error": "Ошибка",
        "disabled": "На паузе",
        "unknown": "Нет данных",
        "pending": "В очереди",
        "running": "Обновляется",
    }
    job_labels = {
        "pending": "В очереди",
        "running": "Выполняется",
        "success": "Выполнено",
        "error": "Ошибка",
    }
    prepared_sources = []
    for source, group_label in registered:
        parser_status = status_by_source.get(source, {})
        database_status = database_by_source.get(source, {})
        enabled = settings.get(source, {}).get("enabled", True)
        job = latest_job_by_source.get(source, {})
        job_active = job.get("status") in {"pending", "running"}
        raw_status = parser_status.get("status", "unknown") if enabled else "disabled"
        display_status = job.get("status") if enabled and job_active else raw_status
        error = (
            job.get("error", "")
            if job.get("status") == "error"
            else parser_status.get("error", "")
        )
        prepared_sources.append({
            "source": source,
            "group_label": group_label,
            "enabled": enabled,
            "status_class": display_status,
            "status_label": status_labels.get(display_status, display_status),
            "job_active": job_active,
            "job_label": job_labels.get(job.get("status"), "") if job else "",
            "checked_at": parser_status.get("checked_at", ""),
            "last_success": parser_status.get("last_success", ""),
            "last_received": database_status.get("last_received", ""),
            "newest_publication": database_status.get("newest_publication", ""),
            "total_news": database_status.get("news_count", 0),
            "news_count": parser_status.get("news_count", 0),
            "duration": parser_status.get("duration_seconds", 0),
            "error": error,
        })

    enabled_sources = [item for item in prepared_sources if item["enabled"]]
    summary = {
        "total": len(prepared_sources),
        "ok": sum(item["status_class"] == "ok" for item in enabled_sources),
        "problem": sum(
            item["status_class"] in {"empty", "error", "unknown"}
            for item in enabled_sources
        ),
        "disabled": len(prepared_sources) - len(enabled_sources),
    }
    prepared_jobs = []
    for job in jobs:
        prepared = dict(job)
        prepared["status_label"] = job_labels.get(job["status"], job["status"])
        prepared_jobs.append(prepared)

    return render_template_string(
        ADMIN_SOURCES_HTML,
        sources=prepared_sources,
        jobs=prepared_jobs,
        summary=summary,
        auto_refresh=any(job["status"] in {"pending", "running"} for job in jobs),
        current_user=administrator,
        csrf_token=csrf_token(),
        message=str(request.args.get("message", "")).strip(),
        error=str(request.args.get("error", "")).strip(),
    )


@app.route("/bookmarks", methods=["GET", "POST"])
def bookmarks_page():
    """Показывает личные папки, новости и заметки текущего пользователя."""
    user = current_user()
    user_id = user["id"]
    selected_folder = str(request.args.get("folder", "all")).strip() or "all"
    folders = list_bookmark_folders(user_id)
    folder_by_id = {str(folder["id"]): folder for folder in folders}
    if selected_folder not in {"all", "unfiled", *folder_by_id}:
        abort(404)

    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        action = str(request.form.get("action", "")).strip()
        try:
            if action == "create_folder":
                created = create_bookmark_folder(user_id, request.form.get("name"))
                message = f"Папка «{created['name']}» создана"
                selected_folder = str(created["id"])
            elif action == "rename_folder":
                renamed = rename_bookmark_folder(
                    user_id,
                    request.form.get("folder_id"),
                    request.form.get("name"),
                )
                message = f"Папка переименована в «{renamed['name']}»"
                selected_folder = str(renamed["id"])
            elif action == "delete_folder":
                delete_bookmark_folder(user_id, request.form.get("folder_id"))
                message = "Папка удалена, её новости перенесены в «Без папки»"
                selected_folder = "unfiled"
            elif action == "update_bookmark":
                update_bookmark(
                    user_id,
                    request.form.get("bookmark_url"),
                    request.form.get("folder_id"),
                    request.form.get("note"),
                )
                message = "Папка и заметка сохранены"
            elif action == "remove_bookmark":
                remove_bookmark(user_id, request.form.get("bookmark_url"))
                message = "Новость удалена из закладок"
            else:
                raise ValueError("Неизвестное действие")
        except ValueError as operation_error:
            return redirect(
                url_for(
                    "bookmarks_page",
                    folder=selected_folder,
                    error=str(operation_error),
                )
            )
        return redirect(
            url_for("bookmarks_page", folder=selected_folder, message=message)
        )

    all_bookmarks = list_bookmarks(user_id)
    bookmarks = list_bookmarks(user_id, selected_folder)
    selected_folder_data = folder_by_id.get(selected_folder)
    if selected_folder_data:
        selected_title = selected_folder_data["name"]
    elif selected_folder == "unfiled":
        selected_title = "Без папки"
    else:
        selected_title = "Все закладки"
    return render_template_string(
        BOOKMARKS_HTML,
        current_user=user,
        csrf_token=csrf_token(),
        folders=folders,
        bookmarks=bookmarks,
        selected_folder=selected_folder,
        selected_folder_data=selected_folder_data,
        selected_title=selected_title,
        total_count=len(all_bookmarks),
        unfiled_count=sum(item["folder_id"] is None for item in all_bookmarks),
        message=str(request.args.get("message", "")).strip(),
        error=str(request.args.get("error", "")).strip(),
    )


def can_view_admin_diagnostics():
    """Служебная диагностика видна только администратору."""
    user = current_user()
    return bool(user and user.get("role") == "admin")


def apply_source_order(sources, preferred_names):
    """Ставит сохранённые пользователем источники первыми, новые — в конец."""
    remaining = {
        str(name).casefold(): (name, count)
        for name, count in sources
    }
    ordered = []
    for preferred in preferred_names or []:
        item = remaining.pop(str(preferred).casefold(), None)
        if item is not None:
            ordered.append(item)
    ordered.extend(
        item
        for item in sources
        if str(item[0]).casefold() in remaining
    )
    return ordered


def render_news_page(
    news,
    mode="all",
    source_filter="",
    source_group=GOVERNMENT_GROUP,
):
    user = current_user()
    if user["id"]:
        user_saved_urls = bookmarked_urls(user["id"])
        user_bookmark_count = count_bookmarks(user["id"])
    else:
        user_saved_urls = []
        user_bookmark_count = 0
    all_news = load_json("all_news.json", [])
    found_news = load_json("found_news.json", [])
    status = load_json("parser_status.json", {})

    group_news = filter_news_by_group(all_news, source_group)
    group_found_news = filter_news_by_group(found_news, source_group)
    news = filter_news_by_group(news, source_group)

    counts = Counter(
        item.get("source", "Неизвестный источник")
        for item in group_news
    )
    sources = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if user["id"]:
        sources = apply_source_order(
            sources,
            load_source_order(user["id"], source_group),
        )

    status_sources = [
        item
        for item in status.get("sources", [])
        if get_source_group(item.get("source", "")) == source_group
    ]
    total_sources = len(status_sources) or len(sources)
    ok_sources = sum(
        item.get("status") == "ok"
        for item in status_sources
    )
    if not status_sources:
        ok_sources = total_sources
    problem_sources = sorted(
        (
            item
            for item in status_sources
            if item.get("status") in {"empty", "error"}
        ),
        key=lambda item: (
            item.get("status") != "error",
            item.get("source", ""),
        ),
    )

    if source_group == AGENCIES_GROUP:
        group_title = "Новости информагентств"
        group_eyebrow = "РИА Новости · ТАСС · Интерфакс · Yonhap · Киодо"
        group_home = "/agencies"
        group_found = "/agencies/found"
        source_base = "/agencies/filter/"
    elif source_group == NEWSPAPERS_GROUP:
        group_title = "Свежие номера газет"
        group_eyebrow = "Коммерсантъ · Известия · РГ · Ведомости · Красная звезда · КП"
        group_home = "/newspapers"
        group_found = "/newspapers/found"
        source_base = "/newspapers/filter/"
    else:
        group_title = "Новости госструктур"
        group_eyebrow = "Агрегатор официальных источников"
        group_home = "/"
        group_found = "/found"
        source_base = "/filter/"

    sorted_news = sort_news_by_publication(news)
    search_query = request.args.get("q", "").strip()
    if search_query:
        needle = search_query.casefold()
        sorted_news = [
            item
            for item in sorted_news
            if needle in " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("source", "")),
                    str(item.get("section", "")),
                    str(item.get("summary", "")),
                    " ".join(item.get("keywords", []) or []),
                ]
            ).casefold()
        ]

    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    page_total = len(sorted_news)
    page_count = max(1, (page_total + NEWS_PER_PAGE - 1) // NEWS_PER_PAGE)
    page = min(page, page_count)
    page_offset = (page - 1) * NEWS_PER_PAGE
    page_news = sorted_news[page_offset:page_offset + NEWS_PER_PAGE]
    page_start = page_offset + 1 if page_news else 0
    page_end = page_offset + len(page_news)
    page_label = (
        f"{page_start}–{page_end} из {page_total}"
        if page_total
        else "0 материалов"
    )

    query_parameters = request.args.to_dict(flat=True)

    def page_url(number):
        parameters = dict(query_parameters)
        if number > 1:
            parameters["page"] = number
        else:
            parameters.pop("page", None)
        query_string = urlencode(parameters)
        return request.path + (f"?{query_string}" if query_string else "")

    visible_pages = sorted(
        {1, page_count}
        | set(range(max(1, page - 2), min(page_count, page + 2) + 1))
    )
    page_links = []
    previous_number = None
    for number in visible_pages:
        if previous_number is not None and number - previous_number > 1:
            page_links.append({"gap": True})
        page_links.append(
            {
                "gap": False,
                "number": number,
                "url": page_url(number),
                "current": number == page,
            }
        )
        previous_number = number

    return render_template_string(
        HTML,
        news=page_news,
        total=len(group_news),
        found_count=len(group_found_news),
        sources=sources,
        news_index=[
            {
                "url": item.get("url", ""),
                "source": item.get("source", "Неизвестный источник"),
            }
            for item in group_news
            if item.get("url")
        ],
        source_filter=source_filter,
        mode=mode,
        source_group=source_group,
        group_title=group_title,
        group_eyebrow=group_eyebrow,
        group_home=group_home,
        group_found=group_found,
        source_base=source_base,
        health_total=total_sources,
        health_ok=ok_sources,
        health_empty=sum(
            item.get("status") == "empty"
            for item in status_sources
        ),
        health_errors=sum(
            item.get("status") == "error"
            for item in status_sources
        ),
        problem_sources=problem_sources,
        status_time=status.get("generated_at", ""),
        current_path=request.path,
        search_query=search_query,
        page=page,
        page_count=page_count,
        page_links=page_links,
        previous_url=page_url(page - 1) if page > 1 else "",
        next_url=page_url(page + 1) if page < page_count else "",
        page_label=page_label,
        show_admin_diagnostics=can_view_admin_diagnostics(),
        current_user=user,
        csrf_token=csrf_token(),
        saved_urls=user_saved_urls,
        bookmark_count=user_bookmark_count,
    )


@app.template_filter("urlencode")
def urlencode_filter(value):
    return quote(str(value), safe="")


@app.route("/")
def index():
    return render_news_page(
        load_json("all_news.json", []),
        source_group=GOVERNMENT_GROUP,
    )


@app.route("/found")
def found_page():
    return render_news_page(
        load_json("found_news.json", []),
        mode="found",
        source_group=GOVERNMENT_GROUP,
    )


@app.route("/filter/<path:source>")
def filter_source(source):
    all_news = load_json("all_news.json", [])
    news = [item for item in all_news if item.get("source") == source]
    return render_news_page(
        news,
        source_filter=source,
        source_group=get_source_group(source),
    )


@app.route("/agencies")
def agencies_page():
    return render_news_page(
        load_json("all_news.json", []),
        source_group=AGENCIES_GROUP,
    )


@app.route("/agencies/found")
def agencies_found_page():
    return render_news_page(
        load_json("found_news.json", []),
        mode="found",
        source_group=AGENCIES_GROUP,
    )


@app.route("/agencies/filter/<path:source>")
def agencies_filter_source(source):
    all_news = load_json("all_news.json", [])
    news = [item for item in all_news if item.get("source") == source]
    return render_news_page(
        news,
        source_filter=source,
        source_group=AGENCIES_GROUP,
    )


@app.route("/newspapers")
def newspapers_page():
    return render_news_page(
        load_json("all_news.json", []),
        source_group=NEWSPAPERS_GROUP,
    )


@app.route("/newspapers/found")
def newspapers_found_page():
    return render_news_page(
        load_json("found_news.json", []),
        mode="found",
        source_group=NEWSPAPERS_GROUP,
    )


@app.route("/newspapers/filter/<path:source>")
def newspapers_filter_source(source):
    all_news = load_json("all_news.json", [])
    news = [item for item in all_news if item.get("source") == source]
    return render_news_page(
        news,
        source_filter=source,
        source_group=NEWSPAPERS_GROUP,
    )


@app.route("/article", methods=["GET", "POST"])
def article_page():
    if request.method == "POST" and not csrf_is_valid():
        abort(400)
    url = request.values.get("url", "").strip()
    item = next(
        (news for news in load_json("all_news.json", []) if news.get("url") == url),
        None,
    )
    if item is None:
        abort(404)
    force_refresh = request.method == "POST"
    cached = load_cached_article(url)
    if cached is not None and not force_refresh:
        article = cached
    elif item.get("article_paragraphs"):
        # Atom Кремля содержит официальный текст публикации. Используем его
        # сразу: повторно открывать защищённую страницу источника не нужно.
        article = {
            "title": item.get("title", ""),
            "paragraphs": item["article_paragraphs"],
            "error": "",
        }
    elif item.get("source") == "ТАСС" and item.get("summary"):
        # RSS ТАСС отдаёт официальный анонс сразу и без браузерной проверки.
        # Полную публикацию при необходимости можно открыть по ссылке.
        article = {
            "title": item.get("title", ""),
            "paragraphs": [item["summary"]],
            "error": "",
        }
    else:
        article = extract_article(url, item.get("title", ""))
        if (
            item.get("source") == "Минобороны РФ"
            and item.get("summary")
            and not article.get("paragraphs")
        ):
            # Некоторые публикации Минобороны являются видеоматериалами:
            # отдельная страница содержит заголовок и теги, но не текст.
            # В таком случае показываем официальный анонс из карточки ленты.
            article = {
                "title": item.get("title", ""),
                "paragraphs": [item["summary"]],
                "error": "",
            }
    if cached is None or force_refresh:
        saved = save_cached_article(url, article, item.get("source", ""))
        if saved is not None:
            article = saved
        elif force_refresh and cached is not None:
            refresh_error = article.get("error") or (
                "Источник не отдал новый текст — показана сохранённая версия."
            )
            article = dict(cached)
            article["refresh_error"] = refresh_error

    requested_back = request.values.get("back_url", "").strip()
    if requested_back.startswith("/") and not requested_back.startswith("//"):
        back_url = requested_back
    else:
        back_url = (
            request.referrer
            if request.referrer and request.host in request.referrer
            else "/"
        )
    return render_template_string(
        ARTICLE_HTML,
        article=article,
        item=item,
        back_url=back_url,
        csrf_token=csrf_token(),
    )


@app.route("/api/keywords", methods=["GET", "POST", "DELETE"])
def keywords_api():
    if request.method == "GET":
        return jsonify(keywords=load_keywords())

    if not csrf_is_valid():
        return jsonify(error="Сессия устарела. Обновите страницу."), 400

    payload = request.get_json(silent=True) or {}
    keyword = str(payload.get("keyword", "")).strip()
    if not 2 <= len(keyword) <= 80:
        return jsonify(error="Слово или фраза должны содержать от 2 до 80 символов."), 400

    if request.method == "POST":
        keywords = add_keyword(keyword)
    else:
        keywords = remove_keyword(keyword)
    found = rebuild_found_news()
    return jsonify(keywords=keywords, found_count=len(found))


@app.route("/api/bookmarks", methods=["GET", "POST", "DELETE"])
def bookmarks_api():
    """Быстро переключает личное сердечко у новости в общей ленте."""
    user = current_user()
    user_id = user["id"]
    if request.method == "GET":
        return jsonify(
            urls=bookmarked_urls(user_id),
            count=count_bookmarks(user_id),
        )
    if not csrf_is_valid():
        return jsonify(error="Сессия устарела. Обновите страницу."), 400

    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    if request.method == "DELETE":
        remove_bookmark(user_id, url)
    else:
        legacy_urls = payload.get("urls")
        if isinstance(legacy_urls, list):
            # Старый интерфейс хранил сердечки только в localStorage.
            # Один ограниченный пакет переносит их в текущий аккаунт.
            for legacy_url in legacy_urls[:500]:
                item = find_news_by_url(str(legacy_url).strip())
                if item is not None:
                    save_bookmark(user_id, item)
        else:
            item = find_news_by_url(url)
            if item is None:
                return jsonify(error="Новость не найдена"), 404
            save_bookmark(user_id, item)
    return jsonify(
        urls=bookmarked_urls(user_id),
        count=count_bookmarks(user_id),
    )


@app.post("/api/source-order")
def source_order_api():
    """Сохраняет личный порядок правой панели для выбранного раздела."""
    user = current_user()
    if not csrf_is_valid():
        return jsonify(error="Сессия устарела. Обновите страницу."), 400
    payload = request.get_json(silent=True) or {}
    source_group = str(payload.get("source_group", "")).strip().casefold()
    if source_group not in {
        GOVERNMENT_GROUP,
        AGENCIES_GROUP,
        NEWSPAPERS_GROUP,
    }:
        return jsonify(error="Неизвестный раздел источников"), 400
    requested = payload.get("sources")
    if not isinstance(requested, list):
        return jsonify(error="Некорректный порядок источников"), 400

    group_news = filter_news_by_group(load_json("all_news.json", []), source_group)
    counts = Counter(
        item.get("source", "Неизвестный источник")
        for item in group_news
    )
    available = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    final_order = [name for name, _ in apply_source_order(available, requested)]
    try:
        saved = save_source_order(user["id"], source_group, final_order)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(sources=saved)


if __name__ == "__main__":
    print("🌐 http://127.0.0.1:5000")
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug, port=5000)
