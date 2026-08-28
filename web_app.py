import json
import re
import secrets
from calendar import monthrange
from io import BytesIO
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from flask import (
    Flask,
    abort,
    g,
    has_request_context,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from config import PROJECT_VERSION
from utils.auth import environment_value, load_secret_key
from utils.article_reader import extract_article, yahoo_article_is_polluted
from utils.diagnostics import alert_summary, source_alerts, system_alerts
from utils.keywords import (
    add_keyword,
    load_keywords,
    rebuild_found_news,
    remove_keyword,
)
from utils.logger import error_log_stats, get_logger, read_recent_errors
from utils.proxy import kyodo_proxy_status
from utils.security import AttemptLimiter
from utils.source_groups import (
    AGENCIES_GROUP,
    AGENCY_SOURCES,
    GOVERNMENT_GROUP,
    GOVERNMENT_SOURCES,
    NEWSPAPERS_GROUP,
    NEWSPAPER_SOURCES,
    is_yahoo_source,
    source_group as get_source_group,
)
from utils.storage import (
    authenticate_user,
    create_manual_backup,
    create_dictionary_deck,
    bookmarked_urls,
    count_users,
    count_bookmarks,
    create_bookmark_folder,
    delete_collection_note,
    delete_calendar_event,
    delete_personal_note,
    create_user,
    delete_user,
    delete_bookmark_folder,
    enqueue_parser_job,
    ensure_favorites_folder,
    find_news_by_url,
    list_users,
    list_database_backups,
    list_source_incidents,
    list_parser_jobs,
    list_bookmark_folders,
    list_bookmarks,
    list_collection_bookmarks,
    list_collection_note_read_ids,
    list_collection_notes,
    list_calendar_events,
    list_dictionary_cards,
    list_dictionary_decks,
    list_personal_notes,
    list_news_index,
    list_news_page,
    list_shared_collections,
    load_collection,
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
    save_bookmark_folder_order,
    save_collection_note,
    save_calendar_event,
    save_dictionary_card,
    save_personal_note,
    save_external_bookmark,
    save_source_order,
    set_source_enabled,
    set_collection_note_read,
    set_user_active,
    set_user_password,
    set_user_role,
    review_dictionary_card,
    update_collection,
    update_collection_note,
    news_group_counts,
    news_source_counts,
    source_news_statistics,
    source_incident_statistics,
    source_reliability_statistics,
    database_stats,
    update_bookmark,
)


app = Flask(__name__)
PROJECT_DIR = Path(__file__).resolve().parent
NEWS_PER_PAGE = 20
UNREAD_INDEX_LIMIT = 2000
FAST_NAVIGATION_ENDPOINTS = {
    "index",
    "found_page",
    "filter_source",
    "agencies_page",
    "agencies_found_page",
    "agencies_filter_source",
    "newspapers_page",
    "newspapers_found_page",
    "newspapers_filter_source",
    "article_page",
    "bookmarks_page",
}


def _enabled_setting(name):
    return environment_value(name).casefold() in {"1", "true", "yes", "on"}


def _allowed_hosts():
    configured = environment_value("MONITOR_ALLOWED_HOSTS")
    return {
        host.strip().casefold().rstrip(".")
        for host in configured.split(",")
        if host.strip()
    }


app.config.update(
    SECRET_KEY=load_secret_key(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    MAX_CONTENT_LENGTH=1_000_000,
    SESSION_COOKIE_NAME="news_monitor_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_enabled_setting("MONITOR_HTTPS"),
    AUTH_DISABLED=_enabled_setting("MONITOR_AUTH_DISABLED"),
    ALLOWED_HOSTS=_allowed_hosts(),
)
security_logger = get_logger("web_security")
LOGIN_PAIR_LIMITER = AttemptLimiter(5, 15 * 60, 15 * 60)
LOGIN_ACCOUNT_LIMITER = AttemptLimiter(10, 15 * 60, 30 * 60)
LOGIN_IP_LIMITER = AttemptLimiter(20, 15 * 60, 30 * 60)


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
        .hint{margin:13px 0 0;font-size:11px}.brand{margin-bottom:30px;font-size:19px;font-weight:800;letter-spacing:-.035em}.password-wrap{position:relative;display:block}.password-wrap input{padding-right:48px}.password-toggle{position:absolute;right:5px;top:12px;width:38px;height:38px;min-height:0;margin:0;padding:0;border:0;color:var(--muted);background:transparent}.password-toggle:hover{color:var(--coral);background:transparent}.password-toggle::before{content:"";display:block;width:21px;height:21px;margin:auto;background:currentColor;mask:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='black' d='M12 5c5.5 0 9.5 5.1 9.7 5.3a2.7 2.7 0 0 1 0 3.4C21.5 13.9 17.5 19 12 19S2.5 13.9 2.3 13.7a2.7 2.7 0 0 1 0-3.4C2.5 10.1 6.5 5 12 5Zm0 2c-4.4 0-7.8 4.2-8.1 4.6a.7.7 0 0 0 0 .8C4.2 12.8 7.6 17 12 17s7.8-4.2 8.1-4.6a.7.7 0 0 0 0-.8C19.8 11.2 16.4 7 12 7Zm0 1.8a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4Z'/%3E%3C/svg%3E");-webkit-mask:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='black' d='M12 5c5.5 0 9.5 5.1 9.7 5.3a2.7 2.7 0 0 1 0 3.4C21.5 13.9 17.5 19 12 19S2.5 13.9 2.3 13.7a2.7 2.7 0 0 1 0-3.4C2.5 10.1 6.5 5 12 5Zm0 2c-4.4 0-7.8 4.2-8.1 4.6a.7.7 0 0 0 0 .8C4.2 12.8 7.6 17 12 17s7.8-4.2 8.1-4.6a.7.7 0 0 0 0-.8C19.8 11.2 16.4 7 12 7Zm0 1.8a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4Z'/%3E%3C/svg%3E")}
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
</main><script>
document.querySelectorAll('input[type="password"]').forEach(input => {
    const wrapper = document.createElement('span');
    wrapper.className = 'password-wrap';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'password-toggle';
    toggle.setAttribute('aria-label', 'Показать пароль');
    toggle.title = 'Показать пароль';
    toggle.addEventListener('click', () => {
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        toggle.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
        toggle.title = show ? 'Скрыть пароль' : 'Показать пароль';
    });
    wrapper.appendChild(toggle);
});
</script></body></html>
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
        .users{display:grid;gap:12px;margin-top:18px}.user{display:grid;grid-template-columns:minmax(150px,1fr) 145px 130px minmax(230px,1.4fr);gap:14px;align-items:center;padding:18px;border:1px solid var(--line);border-radius:7px;background:var(--surface)}.identity strong{display:block}.identity small,.last-login{color:var(--muted);font-size:11px}.status{width:max-content;padding:5px 8px;border-radius:999px;color:var(--green);background:#edf6ef;font-size:10px;font-weight:750;text-transform:uppercase}.status.off{color:#9d302a;background:#fff0ed}.inline{display:flex;gap:7px;align-items:end}.inline label{flex:1}.inline button{flex:0 0 auto}.role-form{display:flex;gap:7px}.role-form select{min-width:0}.top-actions{display:flex;gap:9px;align-items:center}.button{display:inline-flex;align-items:center;text-decoration:none}.danger{color:#a52f29;border-color:#dca39d}.password-wrap{position:relative;display:block}.password-wrap input{padding-right:46px}.password-toggle{position:absolute;right:4px;top:3px;width:38px;height:38px;min-height:0;padding:0;border:0;color:var(--muted);background:transparent}.password-toggle:hover{color:var(--coral)}.password-toggle::before{content:"";display:block;width:20px;height:20px;margin:auto;background:currentColor;mask:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='black' d='M12 5c5.5 0 9.5 5.1 9.7 5.3a2.7 2.7 0 0 1 0 3.4C21.5 13.9 17.5 19 12 19S2.5 13.9 2.3 13.7a2.7 2.7 0 0 1 0-3.4C2.5 10.1 6.5 5 12 5Zm0 2c-4.4 0-7.8 4.2-8.1 4.6a.7.7 0 0 0 0 .8C4.2 12.8 7.6 17 12 17s7.8-4.2 8.1-4.6a.7.7 0 0 0 0-.8C19.8 11.2 16.4 7 12 7Zm0 1.8a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4Z'/%3E%3C/svg%3E");-webkit-mask:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='black' d='M12 5c5.5 0 9.5 5.1 9.7 5.3a2.7 2.7 0 0 1 0 3.4C21.5 13.9 17.5 19 12 19S2.5 13.9 2.3 13.7a2.7 2.7 0 0 1 0-3.4C2.5 10.1 6.5 5 12 5Zm0 2c-4.4 0-7.8 4.2-8.1 4.6a.7.7 0 0 0 0 .8C4.2 12.8 7.6 17 12 17s7.8-4.2 8.1-4.6a.7.7 0 0 0 0-.8C19.8 11.2 16.4 7 12 7Zm0 1.8a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4Z'/%3E%3C/svg%3E")}
        @media(max-width:850px){.user{grid-template-columns:1fr 1fr}.user-actions{grid-column:1/-1}}@media(max-width:580px){header{align-items:start;flex-direction:column}.grid,.user{grid-template-columns:1fr}.wide,.user-actions{grid-column:auto}.inline,.role-form{align-items:stretch;flex-direction:column}}
    </style>
</head>
<body><main class="shell">
    <a class="back" href="/">← Вернуться к Монитору</a>
    <header>
        <div><h1>{{title}}</h1><p class="subtitle">{{subtitle}}</p></div>
        <div class="top-actions">
            {% if current_user.role == 'admin' %}<a class="button" href="/admin/sources">Источники</a><a class="button" href="/admin/system">Система</a>{% endif %}
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
                {% if user.id != current_user.id %}<form method="post" style="margin-top:8px" onsubmit="return confirm('Удалить этого пользователя и все его личные данные?')"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="user_id" value="{{user.id}}"><button class="danger" type="submit">Удалить пользователя</button></form>{% endif %}
            </div>
        </article>
        {% endfor %}
    </section>
    {% endif %}
</main><script>
document.querySelectorAll('input[type="password"]').forEach(input => {
    const wrapper = document.createElement('span');
    wrapper.className = 'password-wrap';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'password-toggle';
    toggle.setAttribute('aria-label', 'Показать пароль');
    toggle.title = 'Показать пароль';
    toggle.addEventListener('click', () => {
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        toggle.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
        toggle.title = show ? 'Скрыть пароль' : 'Показать пароль';
    });
    wrapper.appendChild(toggle);
});
</script></body></html>
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
        .message,.error{margin:0 0 18px;padding:13px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}.summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:20px}.metric{padding:20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.metric span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;margin-top:7px;font-size:31px;letter-spacing:-.04em}.metric small{display:block;margin-top:7px;color:var(--muted);font-size:10px;line-height:1.35}.metric.good strong{color:var(--green)}.metric.warn strong{color:var(--amber)}.metric.bad strong{color:var(--coral)}.metric.channel strong{font-size:18px;letter-spacing:-.02em}
        .alerts{margin:0 0 20px;overflow:hidden;border:1px solid #e3b870;border-radius:8px;background:#fff9ed}.alerts.critical{border-color:#e7a39c;background:#fff4f1}.alerts-head{min-height:55px;padding:12px 17px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid rgba(168,110,22,.22)}.alerts-head h2{margin:0;font-size:16px}.alerts-head span{color:var(--muted);font-size:11px}.alert-row{padding:13px 17px;display:grid;grid-template-columns:78px minmax(180px,.7fr) minmax(0,1.5fr);align-items:center;gap:13px;border-top:1px solid rgba(168,110,22,.15);font-size:12px}.alert-row:first-of-type{border-top:0}.alert-level{width:max-content;padding:4px 7px;border-radius:999px;color:#8a5b12;background:#f8e4bc;font-size:9px;font-weight:800;text-transform:uppercase}.alert-row.critical .alert-level{color:#9d302a;background:#ffdcd7}.alert-row strong{font-size:12px}.alert-row p{margin:0;color:var(--muted);line-height:1.45}
        .panel{overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.panel-head{min-height:64px;padding:0 20px;display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0;font-size:18px}.panel-head p{margin:4px 0 0;color:var(--muted);font-size:11px}.source-table{width:100%;border-collapse:collapse}.source-table th{padding:11px 13px;color:var(--muted);background:#faf6ef;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em}.source-table td{padding:13px;border-top:1px solid #e6dfd4;vertical-align:middle;font-size:12px}.source-table tbody tr:hover{background:#fff9f2}.source strong{display:block;font-size:13px}.source small,.muted{display:block;margin-top:3px;color:var(--muted);font-size:10px}.badge{width:max-content;padding:5px 8px;border-radius:999px;background:#edf6ef;color:var(--green);font-size:10px;font-weight:750}.badge.empty,.badge.pending,.badge.running{color:var(--amber);background:#fff4de}.badge.error{color:#a63a32;background:#fff0ed}.badge.disabled{color:#777267;background:#eee9e1}.result b{display:block;font-size:13px}.error-copy{max-width:260px;margin-top:4px;overflow:hidden;color:#a63a32;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.actions{display:flex;justify-content:flex-end;gap:7px}.actions form{margin:0}.actions .run{color:var(--coral);border-color:rgba(228,79,69,.5)}.actions button:disabled{cursor:not-allowed;opacity:.4}.pause{min-width:86px}.jobs{margin-top:18px;padding:18px 20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.jobs h2{margin:0 0 12px;font-size:16px}.job{min-height:34px;display:grid;grid-template-columns:minmax(180px,1fr) 100px 155px minmax(0,2fr);align-items:center;gap:12px;border-top:1px solid #ece5da;font-size:11px}.job:first-of-type{border-top:0}.job-error{overflow:hidden;color:#a63a32;text-overflow:ellipsis;white-space:nowrap}.empty-jobs{color:var(--muted);font-size:12px}
        @media(max-width:1050px){.summary{grid-template-columns:repeat(2,1fr)}.table-wrap{overflow-x:auto}.source-table{min-width:980px}}@media(max-width:620px){.shell{width:min(100% - 22px,1450px)}.top{align-items:flex-start;flex-direction:column}.summary{grid-template-columns:1fr 1fr}.metric{padding:15px}.metric strong{font-size:25px}.job{grid-template-columns:1fr 90px}.job span:nth-child(n+3){display:none}}
    </style>
</head>
<body><main class="shell">
    <div class="top">
        <a class="back" href="/">← Вернуться к Монитору</a>
        <div class="top-actions"><a class="button" href="/admin/incidents">Инциденты</a><a class="button" href="/admin/reliability">Надёжность</a><a class="button" href="/admin/system">Система</a><a class="button" href="/admin/users">Пользователи</a><a class="button" href="/account">Мой аккаунт</a></div>
    </div>
    <header><h1>Источники</h1><p class="subtitle">Состояние парсеров, ручные проверки и управление расписанием</p></header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}
    {% if error %}<p class="error">{{error}}</p>{% endif %}
    <section class="summary">
        <article class="metric"><span>Всего источников</span><strong>{{summary.total}}</strong></article>
        <article class="metric good"><span>Работают</span><strong>{{summary.ok}}</strong></article>
        <article class="metric warn"><span>Ждут внимания</span><strong>{{summary.problem}}</strong></article>
        <article class="metric bad"><span>На паузе</span><strong>{{summary.disabled}}</strong></article>
        <article class="metric channel {{'good' if kyodo_vpn.ok else 'bad'}}"><span>Киодо</span><strong>{{kyodo_vpn.label}}</strong><small>{{kyodo_vpn.detail}}</small></article>
    </section>
    {% if alerts %}<section class="alerts {{'critical' if alert_counts.critical else ''}}">
        <div class="alerts-head"><h2>Автоматическая диагностика</h2><span>{{alert_counts.total}} предупреждений · критичных: {{alert_counts.critical}}</span></div>
        {% for alert in alerts %}<article class="alert-row {{alert.level}}"><span class="alert-level">{{alert.level_label}}</span><strong>{{alert.title}}</strong><p>{{alert.message}}</p></article>{% endfor %}
    </section>{% endif %}
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


ADMIN_SYSTEM_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Система — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655;--amber:#a86e16}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}.shell{width:min(1320px,calc(100% - 34px));margin:auto;padding:30px 0 80px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:18px}.back{color:var(--muted)}.back:hover{color:var(--coral)}.top-actions{display:flex;gap:8px;flex-wrap:wrap}.button,button{min-height:40px;padding:0 14px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:6px;color:#5b554c;background:var(--surface);font:650 12px inherit;cursor:pointer}.button:hover,button:hover{color:var(--coral);border-color:var(--coral)}header{margin:36px 0 24px}h1{margin:0;font-size:clamp(38px,5vw,64px);line-height:1;letter-spacing:-.055em}.subtitle{margin:10px 0 0;color:var(--muted)}
        .message,.error{margin:0 0 18px;padding:13px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}.metric{padding:20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.metric span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;margin-top:7px;font-size:28px;letter-spacing:-.04em}.metric.good strong{color:var(--green)}.metric.warn strong{color:var(--amber)}
        .alerts{margin:0 0 18px;overflow:hidden;border:1px solid #e3b870;border-radius:8px;background:#fff9ed}.alerts.critical{border-color:#e7a39c;background:#fff4f1}.alerts-head{min-height:55px;padding:12px 17px;display:flex;align-items:center;justify-content:space-between;gap:15px;border-bottom:1px solid rgba(168,110,22,.22)}.alerts-head h2{margin:0;font-size:16px}.alerts-head span{color:var(--muted);font-size:11px}.alert-row{padding:13px 17px;display:grid;grid-template-columns:78px minmax(180px,.7fr) minmax(0,1.5fr);align-items:center;gap:13px;border-top:1px solid rgba(168,110,22,.15);font-size:12px}.alert-row:first-of-type{border-top:0}.alert-level{width:max-content;padding:4px 7px;border-radius:999px;color:#8a5b12;background:#f8e4bc;font-size:9px;font-weight:800;text-transform:uppercase}.alert-row.critical .alert-level{color:#9d302a;background:#ffdcd7}.alert-row strong{font-size:12px}.alert-row p{margin:0;color:var(--muted);line-height:1.45}
        .grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(360px,.75fr);gap:18px;align-items:start}.panel{overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.panel+.panel{margin-top:18px}.panel-head{min-height:64px;padding:13px 20px;display:flex;align-items:center;justify-content:space-between;gap:15px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0;font-size:18px}.panel-head p{margin:4px 0 0;color:var(--muted);font-size:11px}.primary{color:var(--coral);border-color:rgba(228,79,69,.55)}.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.fact{padding:16px 20px;border-bottom:1px solid #e8e1d6}.fact:nth-child(odd){border-right:1px solid #e8e1d6}.fact span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em}.fact b{display:block;margin-top:5px;font-size:14px}.path{overflow-wrap:anywhere;color:var(--muted);font-size:10px}.backup{min-height:54px;padding:10px 16px;display:grid;grid-template-columns:minmax(0,1fr) 90px 150px;align-items:center;gap:12px;border-top:1px solid #e8e1d6;font-size:11px}.backup:first-child{border-top:0}.backup strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.kind{margin-top:3px;color:var(--muted);font-size:9px;text-transform:uppercase}.empty{padding:35px 20px;color:var(--muted);text-align:center;font-size:12px}
        .log{max-height:700px;overflow:auto;background:#201f1c;color:#eee8df}.log-line{padding:9px 13px;border-top:1px solid #37342f;font:11px/1.45 Consolas,"Cascadia Mono",monospace;overflow-wrap:anywhere}.log-line:first-child{border-top:0}.log-line.severity-warning{color:#ffd18a}.log-line.severity-error{color:#ff9d96}.log-meta{color:var(--muted);font-size:10px}.log-empty{padding:50px 20px;color:#aaa39a;text-align:center;font-size:12px}
        @media(max-width:960px){.summary{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}@media(max-width:580px){.shell{width:min(100% - 22px,1320px)}.top{align-items:flex-start;flex-direction:column}.summary{grid-template-columns:1fr 1fr}.metric{padding:15px}.metric strong{font-size:23px}.backup{grid-template-columns:1fr 72px}.backup time{display:none}.facts{grid-template-columns:1fr}.fact:nth-child(odd){border-right:0}}
    </style>
</head>
<body><main class="shell">
    <div class="top"><a class="back" href="/">← Вернуться к Монитору</a><div class="top-actions"><a class="button" href="/admin/sources">Источники</a><a class="button" href="/admin/incidents">Инциденты</a><a class="button" href="/admin/reliability">Надёжность</a><a class="button" href="/admin/users">Пользователи</a><a class="button" href="/account">Мой аккаунт</a></div></div>
    <header><h1>Система</h1><p class="subtitle">SQLite, резервные копии и журнал ошибок · версия {{version}}</p></header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}{% if error %}<p class="error">{{error}}</p>{% endif %}
    <section class="summary">
        <article class="metric good"><span>Целостность SQLite</span><strong>{{database.integrity}}</strong></article>
        <article class="metric"><span>Размер базы</span><strong>{{database.size}}</strong></article>
        <article class="metric"><span>Новостей</span><strong>{{database.news_count}}</strong></article>
        <article class="metric"><span>Текстов сохранено</span><strong>{{database.cached_articles}}</strong></article>
    </section>
    {% if alerts %}<section class="alerts {{'critical' if alert_counts.critical else ''}}">
        <div class="alerts-head"><h2>Автоматическая диагностика</h2><span>{{alert_counts.total}} предупреждений · критичных: {{alert_counts.critical}}</span></div>
        {% for alert in alerts %}<article class="alert-row {{alert.level}}"><span class="alert-level">{{alert.level_label}}</span><strong>{{alert.title}}</strong><p>{{alert.message}}</p></article>{% endfor %}
    </section>{% endif %}
    <div class="grid">
        <div>
            <section class="panel">
                <div class="panel-head"><div><h2>Рабочая база</h2><p>Проверка выполняется средствами самой SQLite.</p></div><a class="button" href="/admin/system">Проверить снова</a></div>
                <div class="facts">
                    <div class="fact"><span>Совпадений</span><b>{{database.found_count}}</b></div><div class="fact"><span>Режим журнала</span><b>{{database.journal_mode|upper}}</b></div>
                    <div class="fact"><span>Миграция JSON</span><b>{{'завершена' if database.json_migrated else 'не завершена'}}</b></div><div class="fact"><span>Резервных копий</span><b>{{backups|length}}</b></div>
                    <div class="fact" style="grid-column:1/-1"><span>Файл базы</span><b class="path">{{database.path}}</b></div>
                </div>
            </section>
            <section class="panel">
                <div class="panel-head"><div><h2>Резервные копии</h2><p>Ручных копий хранится не больше десяти.</p></div><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="backup"><button class="primary" type="submit">Создать копию</button></form></div>
                <div>{% for backup in backups %}<div class="backup"><div><strong title="{{backup.name}}">{{backup.name}}</strong><div class="kind">{{'ручная' if backup.kind == 'manual' else 'ежедневная'}}</div></div><span>{{backup.size}}</span><time>{{backup.modified_at.replace('T',' ')}}</time></div>{% else %}<div class="empty">Резервных копий пока нет.</div>{% endfor %}</div>
            </section>
        </div>
        <section class="panel">
            <div class="panel-head"><div><h2>Последние ошибки</h2><p class="log-meta">{{log.size}} · обновлён {{log.modified_at.replace('T',' ') if log.modified_at else '—'}}</p></div></div>
            <div class="log">{% for line in errors %}<div class="log-line {{'severity-error' if ' ERROR ' in line else ('severity-warning' if ' WARNING ' in line else '')}}">{{line}}</div>{% else %}<div class="log-empty">Журнал пуст — ошибок пока нет.</div>{% endfor %}</div>
        </section>
    </div>
</main></body></html>
"""


ADMIN_INCIDENTS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Инциденты — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655;--amber:#a86e16}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}.shell{width:min(1380px,calc(100% - 34px));margin:auto;padding:30px 0 80px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:18px}.back{color:var(--muted)}.back:hover{color:var(--coral)}.top-actions{display:flex;gap:8px;flex-wrap:wrap}.button{min-height:40px;padding:0 14px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:6px;color:#5b554c;background:var(--surface);font-size:12px;font-weight:650}.button:hover,.button.active{color:var(--coral);border-color:var(--coral)}header{margin:36px 0 24px}h1{margin:0;font-size:clamp(40px,5vw,66px);line-height:1;letter-spacing:-.055em}.subtitle{margin:10px 0 0;color:var(--muted)}
        .summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}.metric{padding:20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.metric span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;margin-top:7px;font-size:30px;letter-spacing:-.04em}.metric.bad strong{color:var(--coral)}.metric.warn strong{color:var(--amber)}.metric.good strong{color:var(--green)}
        .toolbar{margin-bottom:18px;display:flex;align-items:center;justify-content:space-between;gap:12px}.filters{display:flex;gap:8px;flex-wrap:wrap}.hint{color:var(--muted);font-size:11px}.panel{overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.table{width:100%;border-collapse:collapse}.table th{padding:12px 14px;color:var(--muted);background:#faf6ef;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em}.table td{padding:15px 14px;border-top:1px solid #e6dfd4;vertical-align:top;font-size:12px}.table tbody tr.active{background:#fff9ef}.table tbody tr.critical{background:#fff3f0}.status{width:max-content;padding:5px 8px;border-radius:999px;color:var(--green);background:#edf6ef;font-size:9px;font-weight:800;text-transform:uppercase}.status.warning{color:#8a5b12;background:#fae8c7}.status.critical{color:#a63a32;background:#ffdcd7}.source strong{display:block;font-size:13px}.source small,.muted{display:block;margin-top:4px;color:var(--muted);font-size:10px}.message{max-width:420px;color:var(--muted);line-height:1.45}.duration{white-space:nowrap;font-weight:700}.empty{padding:70px 25px;color:var(--muted);text-align:center}.empty strong{display:block;margin-bottom:7px;color:var(--ink);font-size:20px}
        @media(max-width:980px){.summary{grid-template-columns:repeat(2,1fr)}.table-wrap{overflow:auto}.table{min-width:1000px}}@media(max-width:620px){.shell{width:min(100% - 22px,1380px)}.top{align-items:flex-start;flex-direction:column}.summary{grid-template-columns:1fr 1fr}.metric{padding:15px}.toolbar{align-items:flex-start;flex-direction:column}}
    </style>
</head>
<body><main class="shell">
    <div class="top"><a class="back" href="/">← Вернуться к Монитору</a><div class="top-actions"><a class="button" href="/admin/sources">Источники</a><a class="button" href="/admin/reliability">Надёжность</a><a class="button" href="/admin/system">Система</a><a class="button" href="/admin/users">Пользователи</a><a class="button" href="/account">Мой аккаунт</a></div></div>
    <header><h1>Инциденты</h1><p class="subtitle">История сбоев, восстановлений и продолжительности проблем источников</p></header>
    <section class="summary">
        <article class="metric"><span>Всего записано</span><strong>{{summary.total}}</strong></article>
        <article class="metric warn"><span>Активных</span><strong>{{summary.active}}</strong></article>
        <article class="metric bad"><span>Критических</span><strong>{{summary.critical}}</strong></article>
        <article class="metric good"><span>Закрыто за 24 часа</span><strong>{{summary.resolved_24h}}</strong></article>
    </section>
    <div class="toolbar"><nav class="filters"><a class="button {{'active' if state == 'all' else ''}}" href="/admin/incidents">Все</a><a class="button {{'active' if state == 'active' else ''}}" href="/admin/incidents?state=active">Активные</a><a class="button {{'active' if state == 'resolved' else ''}}" href="/admin/incidents?state=resolved">Завершённые</a></nav><span class="hint">Записи создаёт работающий main.py после каждой проверки.</span></div>
    <section class="panel"><div class="table-wrap">
        {% if incidents %}<table class="table"><thead><tr><th>Состояние</th><th>Источник</th><th>Начало</th><th>Последняя проверка</th><th>Длительность</th><th>Проверок</th><th>Причина / результат</th></tr></thead><tbody>
        {% for item in incidents %}<tr class="{{item.level if item.is_active else ''}} {{'active' if item.is_active else ''}}">
            <td><span class="status {{item.level if item.is_active else ''}}">{{item.status_label}}</span></td>
            <td class="source"><strong>{{item.source}}</strong><small>{{'Ошибка' if item.code == 'error' else 'Пустая выдача'}}</small></td>
            <td>{{item.started_at.replace('T',' ')}}</td><td>{{item.last_seen_at.replace('T',' ')}}</td><td class="duration">{{item.duration}}</td><td>{{item.checks_count}}</td>
            <td><div class="message">{{item.message or 'Причина не указана'}}{% if not item.is_active %}<small class="muted">{{item.resolution}} · {{item.resolved_at.replace('T',' ')}}</small>{% endif %}</div></td>
        </tr>{% endfor %}</tbody></table>{% else %}<div class="empty"><strong>Инцидентов нет</strong><span>Это хороший знак: источники пока не фиксировали ошибок и пустых ответов.</span></div>{% endif %}
    </div></section>
</main></body></html>
"""


ADMIN_RELIABILITY_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Надёжность источников — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655;--amber:#a86e16}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}.shell{width:min(1380px,calc(100% - 34px));margin:auto;padding:30px 0 80px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:18px}.back{color:var(--muted)}.back:hover{color:var(--coral)}.top-actions,.periods{display:flex;gap:8px;flex-wrap:wrap}.button{min-height:40px;padding:0 14px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:6px;color:#5b554c;background:var(--surface);font-size:12px;font-weight:650}.button:hover,.button.active{color:var(--coral);border-color:var(--coral)}header{margin:36px 0 24px}h1{margin:0;font-size:clamp(40px,5vw,66px);line-height:1;letter-spacing:-.055em}.subtitle{margin:10px 0 0;color:var(--muted);line-height:1.5}
        .summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}.metric{padding:20px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.metric span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;margin-top:7px;font-size:30px;letter-spacing:-.04em}.metric.bad strong{color:var(--coral)}.metric.warn strong{color:var(--amber)}.metric.good strong{color:var(--green)}.toolbar{margin-bottom:18px;display:flex;align-items:center;justify-content:space-between;gap:12px}.hint{color:var(--muted);font-size:11px;text-align:right}
        .panel{overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.table{width:100%;border-collapse:collapse}.table th{padding:12px 14px;color:var(--muted);background:#faf6ef;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em}.table td{padding:15px 14px;border-top:1px solid #e6dfd4;vertical-align:middle;font-size:12px}.table tbody tr:hover{background:#fff9f2}.source strong{display:block;font-size:13px}.source small{display:block;margin-top:4px;color:var(--muted);font-size:10px}.uptime{min-width:180px}.uptime-head{display:flex;align-items:center;justify-content:space-between;gap:10px;font-weight:800}.uptime-head.good{color:var(--green)}.uptime-head.warn{color:var(--amber)}.uptime-head.bad{color:var(--coral)}.track{height:5px;margin-top:7px;overflow:hidden;border-radius:999px;background:#e9e2d8}.track span{height:100%;display:block;border-radius:inherit;background:var(--green)}.track span.warn{background:var(--amber)}.track span.bad{background:var(--coral)}.active{width:max-content;padding:5px 8px;border-radius:999px;color:#a63a32;background:#ffdcd7;font-size:9px;font-weight:800;text-transform:uppercase}.muted{color:var(--muted)}
        @media(max-width:980px){.summary{grid-template-columns:repeat(2,1fr)}.table-wrap{overflow:auto}.table{min-width:930px}}@media(max-width:620px){.shell{width:min(100% - 22px,1380px)}.top,.toolbar{align-items:flex-start;flex-direction:column}.summary{grid-template-columns:1fr 1fr}.metric{padding:15px}.hint{text-align:left}}
    </style>
</head>
<body><main class="shell">
    <div class="top"><a class="back" href="/">← Вернуться к Монитору</a><div class="top-actions"><a class="button" href="/admin/sources">Источники</a><a class="button" href="/admin/incidents">Инциденты</a><a class="button" href="/admin/system">Система</a><a class="button" href="/admin/users">Пользователи</a><a class="button" href="/account">Мой аккаунт</a></div></div>
    <header><h1>Надёжность</h1><p class="subtitle">Доступность источников по времени записанных сбоев. Чем меньше источник провёл в активном инциденте, тем выше процент.</p></header>
    <section class="summary">
        <article class="metric good"><span>Средняя доступность</span><strong>{{summary.average_uptime}}%</strong></article>
        <article class="metric warn"><span>Инцидентов</span><strong>{{summary.incidents}}</strong></article>
        <article class="metric bad"><span>Суммарный простой</span><strong>{{summary.downtime}}</strong></article>
        <article class="metric"><span>Источников со сбоями</span><strong>{{summary.affected}} / {{summary.total}}</strong></article>
    </section>
    <div class="toolbar"><nav class="periods"><a class="button {{'active' if days == 7 else ''}}" href="/admin/reliability?days=7">7 дней</a><a class="button {{'active' if days == 30 else ''}}" href="/admin/reliability?days=30">30 дней</a></nav><span class="hint">История считается с момента установки журнала инцидентов; источники на паузе помечены отдельно.</span></div>
    <section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>Источник</th><th>Доступность</th><th>Простой</th><th>Инцидентов</th><th>Средняя длительность</th><th>Проверок с ошибкой</th><th>Сейчас</th></tr></thead><tbody>
        {% for item in sources %}<tr><td class="source"><strong>{{item.source}}</strong><small>{{item.group_label}}</small></td><td class="uptime"><div class="uptime-head {{item.uptime_class}}"><span>{{item.uptime_display}}%</span></div><div class="track"><span class="{{item.uptime_class}}" style="width:{{item.uptime_percent}}%"></span></div></td><td>{{item.downtime}}</td><td>{{item.incident_count}}{% if item.critical_count %}<span class="muted"> · критичных {{item.critical_count}}</span>{% endif %}</td><td>{{item.average_duration}}</td><td>{{item.checks_count}}</td><td>{% if not item.enabled %}<span class="muted">На паузе</span>{% elif item.active_count %}<span class="active">Инцидент</span>{% else %}<span class="muted">Работает</span>{% endif %}</td></tr>{% endfor %}
    </tbody></table></div></section>
</main></body></html>
"""


BOOKMARKS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Подборки — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}a{color:inherit;text-decoration:none}.shell{width:min(1250px,calc(100% - 34px));margin:auto;padding:28px 0 80px}.top{display:flex;align-items:center;justify-content:space-between;gap:15px}.back{color:var(--muted)}.account{font-size:12px;color:var(--muted)}header{margin:38px 0 26px}h1{margin:0;font-size:clamp(42px,6vw,70px);line-height:1;letter-spacing:-.055em}.subtitle{margin:10px 0 0;color:var(--muted)}.layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:20px;align-items:start}.panel,.feed{border:1px solid var(--line);border-radius:8px;background:var(--surface)}.panel{position:sticky;top:18px;overflow:hidden}.panel-heading{min-height:59px;padding:0 19px;display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line)}.panel-heading h2{margin:0;font-size:17px}.folder-order-toggle{min-height:30px;padding:0 8px;border-color:transparent;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.04em}.folder-order-toggle:hover,.folder-order-toggle[aria-pressed="true"]{color:var(--coral);background:#fff3ed}.folder-list{padding:9px}.folder-row{display:flex;align-items:center}.folder{min-width:0;min-height:42px;padding:0 10px;display:flex;align-items:center;justify-content:space-between;flex:1;gap:8px;border-radius:5px;color:#5e574e;font-size:13px}.folder:hover,.folder.active{color:var(--coral);background:#fff3ed}.folder b{font-size:11px}.folder-drag-handle{display:none;flex:0 0 24px;color:#aaa196;text-align:center;font-size:13px;letter-spacing:-2px;cursor:grab;user-select:none}.folder-list.order-editing .sortable-folder{cursor:grab;background:#fffbf6}.folder-list.order-editing .folder-drag-handle{display:block}.folder-list.order-editing .folder{padding-left:4px;pointer-events:none}.sortable-folder.folder-dragging{opacity:.38}.sortable-folder.folder-drag-over{box-shadow:inset 0 2px 0 var(--coral)}.create{padding:15px;border-top:1px solid var(--line)}label{display:grid;gap:6px;color:var(--muted);font-size:11px}input,select,textarea{width:100%;padding:10px 11px;border:1px solid #c9c1b5;border-radius:6px;color:var(--ink);background:#fff;font:inherit}input,select{height:42px}textarea{min-height:92px;resize:vertical}button{min-height:40px;padding:0 13px;border:1px solid var(--coral);border-radius:6px;color:var(--coral);background:transparent;font:650 12px Inter,Arial,sans-serif;cursor:pointer}.primary{color:#fff;background:var(--coral)}.create button{width:100%;margin-top:8px}.message,.error{margin:0 0 16px;padding:13px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}.bookmark{padding:24px;border-bottom:1px solid var(--line)}.bookmark:last-child{border-bottom:0}.meta{display:flex;flex-wrap:wrap;align-items:center;gap:9px;color:var(--muted);font-size:12px}.bookmark h3{margin:10px 0 12px;font-size:clamp(21px,3vw,31px);line-height:1.15;letter-spacing:-.035em}.bookmark h3 a:hover{color:var(--coral)}.edit{display:grid;grid-template-columns:190px minmax(0,1fr) auto;gap:10px;align-items:end;margin-top:16px}.remove{margin-top:9px;border-color:var(--line);color:var(--muted)}.folder-tools{margin:0 9px 10px;padding:12px;border:1px solid var(--line);border-radius:6px;background:#faf6ef}.folder-tools form{display:flex;gap:7px}.folder-tools form+form{margin-top:7px}.folder-tools input{min-width:0}.empty{padding:70px 25px;color:var(--muted);text-align:center}.empty strong{display:block;margin-bottom:7px;color:var(--ink);font-size:20px}
        .folder small{display:block;margin-top:2px;color:var(--muted)}.section-label{padding:13px 19px 5px;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.collection-head{padding:22px 24px;border-bottom:1px solid var(--line)}.collection-head h2{margin:0 0 6px;font-size:28px}.collection-head p{margin:0;color:var(--muted);font-size:14px}.owner{margin-top:10px!important;font-size:12px!important}.search{display:flex;gap:8px;padding:14px 24px;border-bottom:1px solid var(--line);background:#fff}.search input{min-width:0}.search button{white-space:nowrap}.search-clear{display:flex;align-items:center;padding:0 8px;color:var(--muted);font-size:12px}.composer{padding:16px 24px;border-bottom:1px solid var(--line);background:#faf6ef}.composer-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.composer-label{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.composer-form{margin-top:16px}.composer-form[hidden],.composer-open[hidden]{display:none}.composer h3{margin:0 0 14px;font-size:17px}.composer-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.composer .wide{grid-column:1/-1}.composer textarea[name=body]{min-height:180px}.composer-actions{display:flex;gap:8px;margin-top:12px}.share{margin:14px 9px;padding:14px;border:1px solid var(--line);border-radius:6px;background:#faf6ef}.share h3{margin:0 0 10px;font-size:14px}.share label+label{margin-top:8px}.share-users{max-height:145px;overflow:auto;padding:8px;border:1px solid var(--line);border-radius:6px;background:#fff}.share-user{display:flex;grid-template:none;align-items:center;gap:8px;font-size:12px}.share-user input{width:auto;height:auto}.note-card{position:relative;padding:24px 72px 24px 24px;border-bottom:1px solid var(--line);background:#fffaf0}.note-card h3{margin:10px 0 8px;font-size:clamp(21px,3vw,31px);line-height:1.15}.article-read-toggle{position:absolute;top:18px;right:20px;width:38px;min-height:38px;padding:0;border:0;color:var(--muted);background:transparent;font-size:25px;line-height:1}.article-read-toggle:hover{color:var(--coral);transform:translateY(-1px)}.article-read-toggle[aria-pressed="true"]{color:var(--coral)}.note-text{margin-top:16px}.note-text-part{white-space:pre-wrap;line-height:1.55}.note-remainder[hidden]{display:none}.note-toggle{margin-top:16px}.note-actions{display:flex;align-items:center;gap:8px;margin-top:14px}.note-actions form{margin:0}.note-actions .remove{margin:0}.note-edit-form{margin-top:12px;padding:14px;border:1px solid var(--line);border-radius:6px;background:#faf6ef}.note-edit-form[hidden]{display:none}.note-edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.note-edit-grid .wide{grid-column:1/-1}.note-edit-grid textarea[name=body]{min-height:220px}.note-edit-form .primary{margin-top:12px}.comment{margin:12px 0;padding:11px 13px;border-left:3px solid var(--line);background:#fff;color:#554f46;white-space:pre-wrap;line-height:1.5}.material-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 14px;padding-bottom:12px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}.original{display:inline-flex;align-items:center;min-height:34px;padding:0 11px;color:var(--coral);border:1px solid var(--coral);border-radius:6px;font-weight:700}.readonly{padding:12px 24px;color:#655c50;background:#fff3dd;border-bottom:1px solid var(--line);font-size:13px}.badge{padding:3px 7px;border-radius:10px;background:#eee7db;font-size:10px}
        .article-read-toggle>span{display:none}
        .article-read-toggle::before{content:"";display:block;width:28px;height:28px;margin:auto;background:currentColor;mask:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3.5 5.5c2.7-.9 5.3-.4 8 1.3v12c-2.7-1.7-5.3-2.1-8-1.2zM20.5 5.5c-2.7-.9-5.3-.4-8 1.3v12c2.7-1.7 5.3-2.1 8-1.2z'/%3E%3C/svg%3E");-webkit-mask:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3.5 5.5c2.7-.9 5.3-.4 8 1.3v12c-2.7-1.7-5.3-2.1-8-1.2zM20.5 5.5c-2.7-.9-5.3-.4-8 1.3v12c2.7-1.7 5.3-2.1 8-1.2z'/%3E%3C/svg%3E")}
        .article-read-toggle[aria-pressed="true"]::before{mask-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 4.5h11.5A2.5 2.5 0 0 1 19 7v12H6.5A2.5 2.5 0 0 1 4 16.5V6a1.5 1.5 0 0 1 1-1.5Z'/%3E%3Cpath d='M4 16.5A2.5 2.5 0 0 1 6.5 14H19M8 9l1.7 1.7L13 7.5'/%3E%3C/svg%3E");-webkit-mask-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 4.5h11.5A2.5 2.5 0 0 1 19 7v12H6.5A2.5 2.5 0 0 1 4 16.5V6a1.5 1.5 0 0 1 1-1.5Z'/%3E%3Cpath d='M4 16.5A2.5 2.5 0 0 1 6.5 14H19M8 9l1.7 1.7L13 7.5'/%3E%3C/svg%3E")}
        .panel{height:calc(100vh - 36px);max-height:calc(100vh - 36px);overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable}.panel-heading{position:sticky;top:0;z-index:2;background:var(--surface)}.collection-head-main{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.collection-actions{display:flex;align-items:center;gap:8px}.export-button{min-height:38px;padding:0 12px;display:inline-flex;align-items:center;border:1px solid var(--coral);border-radius:6px;color:var(--coral);font-size:12px;font-weight:700;white-space:nowrap}.sort-bar{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:10px 24px;border-bottom:1px solid var(--line);background:#faf6ef}.sort-bar label{display:flex;align-items:center;gap:8px}.sort-bar select{width:auto;min-width:175px}
        @media(max-width:800px){.layout{grid-template-columns:1fr}.panel{position:static;height:auto;max-height:none;overflow:visible}.collection-head-main{flex-direction:column}.sort-bar{justify-content:stretch}.sort-bar label,.sort-bar select{width:100%}.edit,.composer-grid,.note-edit-grid{grid-template-columns:1fr}.note-edit-grid .wide{grid-column:auto}.top{align-items:flex-start;flex-direction:column}}
    </style>
</head>
<body><main class="shell">
    <div class="top"><a class="back" href="/">← Вернуться к Монитору</a><a class="account" href="/account">{{current_user.username}} · настройки аккаунта</a></div>
    <header><h1>Подборки</h1><p class="subtitle">Рабочие папки со статьями, внешними ссылками и заметками</p></header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}{% if error %}<p class="error">{{error}}</p>{% endif %}
    <div class="layout">
        <aside class="panel">
            <div class="panel-heading"><h2>Мои подборки</h2>{% if folders %}<button class="folder-order-toggle" id="folder-order-toggle" type="button" aria-pressed="false">Изменить</button>{% endif %}</div>
            <nav class="folder-list" id="folder-list">
                <a class="folder {{'active' if selected_folder == 'unfiled' else ''}}" href="/collections?folder=unfiled"><span>Без подборки</span><b>{{unfiled_count}}</b></a>
                {% for folder in folders %}<div class="folder-row sortable-folder" data-folder-row data-folder-id="{{folder.id}}"><span class="folder-drag-handle" aria-hidden="true">⋮⋮</span><a class="folder {{'active' if selected_folder == folder.id|string else ''}}" href="/collections?folder={{folder.id}}"><span>{{folder.name}}<small>{{folder.bookmark_count + folder.note_count}} материалов</small></span><b>{{'◉' if folder.visibility == 'all' else ('◎' if folder.visibility == 'selected' else '·')}}</b></a></div>{% endfor %}
            </nav>
            {% if shared_folders %}<div class="section-label">Доступные мне</div><nav class="folder-list">{% for folder in shared_folders %}<a class="folder {{'active' if selected_folder == folder.id|string else ''}}" href="/collections?folder={{folder.id}}"><span>{{folder.name}}<small>{{folder.owner_name}}</small></span><b>{{folder.bookmark_count + folder.note_count}}</b></a>{% endfor %}</nav>{% endif %}
            {% if selected_folder not in ('all','unfiled') and selected_folder_data and selected_folder_data.can_edit %}
            <div class="folder-tools">
                {% if not selected_folder_data.system_key %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="update_collection"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><input name="name" value="{{selected_folder_data.name}}" maxlength="80" required><button type="submit">Сохранить название</button></form>
                <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="delete_folder"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><button type="submit">Удалить папку</button></form>{% else %}<small>Системная папка для новостей, отмеченных сердечком.</small>{% endif %}
            </div>
            <form class="share" method="post"><h3>Доступ к подборке</h3><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="share_collection"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><label>Описание<textarea name="description" maxlength="1000">{{selected_folder_data.description}}</textarea></label><label>Кто видит<select name="visibility"><option value="private" {{'selected' if selected_folder_data.visibility == 'private' else ''}}>Только я</option><option value="all" {{'selected' if selected_folder_data.visibility == 'all' else ''}}>Все пользователи</option><option value="selected" {{'selected' if selected_folder_data.visibility == 'selected' else ''}}>Выбранные пользователи</option></select></label><div class="share-users">{% for account in available_users %}<label class="share-user"><input type="checkbox" name="shared_user_ids" value="{{account.id}}" {{'checked' if account.id in selected_shared_ids else ''}}>{{account.username}}</label>{% endfor %}</div><button class="primary" type="submit">Сохранить доступ</button></form>
            {% endif %}
            <form class="create" method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="create_folder"><label>Новая подборка<input name="name" maxlength="80" placeholder="Например: Выборы в Японии" required></label><button class="primary" type="submit">Создать подборку</button></form>
        </aside>
        <section class="feed">
            <div class="collection-head"><div class="collection-head-main"><div><h2>{{selected_title}}</h2>{% if selected_folder_data %}<p>{{selected_folder_data.description or 'Описание пока не добавлено'}}</p><p class="owner">Владелец: {{selected_folder_data.owner_name}} · {{'редактирование' if selected_folder_data.can_edit else 'только просмотр'}}</p>{% endif %}</div>{% if selected_folder_data %}<div class="collection-actions"><a class="export-button" href="/collections/export.docx?folder={{selected_folder_data.id}}&sort={{sort_mode}}">Скачать Word</a></div>{% endif %}</div></div>
            {% if selected_folder_data and not selected_folder_data.can_edit %}<div class="readonly">Подборка открыта тебе владельцем. Новые материалы появятся здесь автоматически.</div>{% endif %}
            <form class="search" method="get"><input type="hidden" name="folder" value="{{selected_folder}}"><input type="hidden" name="sort" value="{{sort_mode}}"><input type="search" name="q" value="{{search_query}}" maxlength="200" placeholder="Поиск по заголовку, источнику, тексту и комментариям"><button type="submit">Найти</button>{% if search_query %}<a class="search-clear" href="/collections?folder={{selected_folder}}&sort={{sort_mode}}">Сбросить</a>{% endif %}</form>
            <form class="sort-bar" method="get"><input type="hidden" name="folder" value="{{selected_folder}}">{% if search_query %}<input type="hidden" name="q" value="{{search_query}}">{% endif %}<label>Сортировка<select name="sort" onchange="this.form.submit()">{% for value, label in sort_options.items() %}<option value="{{value}}" {{'selected' if sort_mode == value else ''}}>{{label}}</option>{% endfor %}</select></label></form>
            {% if selected_folder_data and selected_folder_data.can_edit %}<div class="composer" data-article-composer><div class="composer-head"><strong class="composer-label">Статьи</strong><button class="primary composer-open" type="button" data-composer-open aria-expanded="false">+ Добавить статью</button></div><form class="composer-form" data-composer-form method="post" hidden><h3>Новая статья</h3><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="add_note"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><div class="composer-grid"><label>Ссылка<input type="url" name="url" placeholder="https://…"></label><label>Источник<input name="source" maxlength="300" placeholder="Например: Коммерсантъ"></label><label>Дата публикации<input type="date" name="publication_date"></label><label>Заголовок<input name="title" maxlength="200" required></label><label class="wide">Текст<textarea name="body" maxlength="20000" placeholder="Вставь текст статьи или напиши свой текст"></textarea></label><label class="wide">Комментарий<textarea name="comment" maxlength="5000" placeholder="Что важно в этой статье?"></textarea></label></div><div class="composer-actions"><button class="primary" type="submit">Сохранить в подборку</button><button type="button" data-composer-cancel>Отмена</button></div></form></div>{% endif %}
            {% for note in notes %}<article class="note-card"><button class="article-read-toggle" type="button" data-article-read data-folder-id="{{selected_folder_data.id}}" data-note-id="{{note.id}}" aria-pressed="{{'true' if note.is_read else 'false'}}" aria-label="{{'Отметить непрочитанной' if note.is_read else 'Отметить прочитанной'}}" title="{{'Прочитано — нажми, чтобы отменить' if note.is_read else 'Не прочитано — нажми, чтобы отметить'}}"><span aria-hidden="true">{{'📕' if note.is_read else '📖'}}</span></button><div class="meta"><span class="badge">Статья</span>{% if note.publication_date %}<time>{{note.publication_date}}</time>{% endif %}</div><h3>{{note.title}}</h3><div class="material-footer"><span>{{note.source or 'Источник не указан'}}</span>{% if note.url %}<a class="original" href="{{note.url}}" target="_blank" rel="noopener">Оригинал ↗</a>{% endif %}</div>{% if note.body_preview or note.body_remainder %}<div class="note-text" data-expandable-note><div class="note-text-part">{{note.body_preview}}{% if note.body_remainder %}<span class="note-remainder" data-note-remainder hidden>{{note.body_remainder}}</span>{% endif %}</div>{% if note.body_remainder %}<button class="note-toggle" type="button" data-note-toggle aria-expanded="false">Читать полностью</button>{% endif %}</div>{% endif %}{% if note.comment %}<div class="comment">{{note.comment}}</div>{% endif %}{% if selected_folder_data.can_edit %}<div class="note-actions"><button class="remove" type="button" data-note-edit-toggle aria-expanded="false">Изменить</button><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="delete_note"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><input type="hidden" name="note_id" value="{{note.id}}"><button class="remove" type="submit">Удалить статью</button></form></div><form class="note-edit-form" data-note-editor method="post" hidden><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="update_note"><input type="hidden" name="folder_id" value="{{selected_folder_data.id}}"><input type="hidden" name="note_id" value="{{note.id}}"><div class="note-edit-grid"><label>Ссылка<input type="url" name="url" value="{{note.url}}" placeholder="https://…"></label><label>Источник<input name="source" value="{{note.source}}" maxlength="300"></label><label>Дата публикации<input type="date" name="publication_date" value="{{note.publication_date}}"></label><label>Заголовок<input name="title" value="{{note.title}}" maxlength="200" required></label><label class="wide">Текст<textarea name="body" maxlength="20000">{{note.body}}</textarea></label><label class="wide">Комментарий<textarea name="comment" maxlength="5000">{{note.comment}}</textarea></label></div><button class="primary" type="submit">Сохранить изменения</button></form>{% endif %}</article>{% endfor %}
            {% if bookmarks %}
                {% for bookmark in bookmarks %}
                <article class="bookmark">
                    <div class="meta">{% if bookmark.date %}<time>{{bookmark.date}}</time>{% endif %}{% if bookmark.folder_name %}<span>•</span><span>{{bookmark.folder_name}}</span>{% endif %}</div>
                    <h3><a href="/article?url={{bookmark.url|urlencode}}" target="_blank" rel="noopener">{{bookmark.title}}</a></h3>
                    <div class="material-footer"><span>{{bookmark.source or 'Источник не указан'}}</span><a class="original" href="{{bookmark.url}}" target="_blank" rel="noopener">Оригинал ↗</a></div>{% if bookmark.note %}<div class="comment">{{bookmark.note}}</div>{% endif %}
                    {% if selected_folder_data is none or selected_folder_data.can_edit %}<form class="edit" method="post">
                        <input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="update_bookmark"><input type="hidden" name="bookmark_url" value="{{bookmark.url}}">
                        <label>Папка<select name="folder_id"><option value="">Без папки</option>{% for folder in folders %}<option value="{{folder.id}}" {{'selected' if bookmark.folder_id == folder.id else ''}}>{{folder.name}}</option>{% endfor %}</select></label>
                        <label>Заметка<textarea name="note" maxlength="5000" placeholder="Что важно в этой публикации?">{{bookmark.note}}</textarea></label>
                        <button class="primary" type="submit">Сохранить</button>
                    </form>
                    <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="remove_bookmark"><input type="hidden" name="bookmark_url" value="{{bookmark.url}}"><button class="remove" type="submit">Удалить из закладок</button></form>
                    {% endif %}
                </article>
                {% endfor %}
            {% elif not notes %}<div class="empty"><strong>{{'Ничего не найдено' if search_query else 'Здесь пока пусто'}}</strong><span>{{'Попробуй изменить запрос.' if search_query else 'Добавь статью или перемести сюда сохранённую новость.'}}</span></div>{% endif %}
        </section>
    </div>
    <script>
    document.querySelectorAll('[data-article-read]').forEach(button => {
        button.addEventListener('click', async () => {
            const isRead = button.getAttribute('aria-pressed') === 'true';
            button.disabled = true;
            try{
                const response = await fetch('/api/collection-note-read', {
                    method:'POST',
                    headers:{
                        'Content-Type':'application/json',
                        'X-CSRF-Token': {{csrf_token|tojson}}
                    },
                    body:JSON.stringify({
                        folder_id:Number(button.dataset.folderId),
                        note_id:Number(button.dataset.noteId),
                        is_read:!isRead
                    })
                });
                const data = await response.json().catch(() => ({}));
                if(!response.ok) throw new Error(data.error || 'Не удалось сохранить отметку');
                button.setAttribute('aria-pressed', String(data.is_read));
                button.setAttribute('aria-label', data.is_read ? 'Отметить непрочитанной' : 'Отметить прочитанной');
                button.title = data.is_read
                    ? 'Прочитано — нажми, чтобы отменить'
                    : 'Не прочитано — нажми, чтобы отметить';
                button.querySelector('span').textContent = data.is_read ? '📕' : '📖';
            }catch(error){
                window.alert(error.message);
            }finally{
                button.disabled = false;
            }
        });
    });
    document.querySelectorAll('[data-note-toggle]').forEach(button => {
        button.addEventListener('click', () => {
            const note = button.closest('[data-expandable-note]');
            const remainder = note.querySelector('[data-note-remainder]');
            const expanded = button.getAttribute('aria-expanded') === 'true';
            remainder.hidden = expanded;
            button.setAttribute('aria-expanded', String(!expanded));
            button.textContent = expanded ? 'Читать полностью' : 'Свернуть';
        });
    });
    document.querySelectorAll('[data-note-edit-toggle]').forEach(button => {
        button.addEventListener('click', () => {
            const editor = button.closest('.note-card').querySelector('[data-note-editor]');
            const expanded = button.getAttribute('aria-expanded') === 'true';
            editor.hidden = expanded;
            button.setAttribute('aria-expanded', String(!expanded));
            button.textContent = expanded ? 'Изменить' : 'Закрыть редактор';
        });
    });
    document.querySelectorAll('[data-article-composer]').forEach(composer => {
        const openButton = composer.querySelector('[data-composer-open]');
        const cancelButton = composer.querySelector('[data-composer-cancel]');
        const form = composer.querySelector('[data-composer-form]');
        function setComposerOpen(open){
            form.hidden = !open;
            openButton.hidden = open;
            openButton.setAttribute('aria-expanded', String(open));
            if(open) form.querySelector('input[name="url"]').focus();
        }
        openButton.addEventListener('click', () => setComposerOpen(true));
        cancelButton.addEventListener('click', () => setComposerOpen(false));
    });
    const folderList = document.getElementById('folder-list');
    const folderOrderToggle = document.getElementById('folder-order-toggle');
    if(folderList && folderOrderToggle){
        const orderedFolderRows = () => [...folderList.querySelectorAll('[data-folder-row]')];
        let draggedFolderRow = null;
        let folderOrderChanged = false;
        function setFolderOrderEditing(editing){
            folderList.classList.toggle('order-editing', editing);
            folderOrderToggle.setAttribute('aria-pressed', String(editing));
            folderOrderToggle.textContent = editing ? 'Готово' : 'Изменить';
            orderedFolderRows().forEach(row => row.draggable = editing);
        }
        async function saveFolderOrder(){
            const response = await fetch('/api/collection-order', {
                method:'POST',
                headers:{
                    'Content-Type':'application/json',
                    'X-CSRF-Token': {{csrf_token|tojson}}
                },
                body:JSON.stringify({
                    folder_ids:orderedFolderRows().map(row => Number(row.dataset.folderId))
                })
            });
            if(!response.ok){
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || 'Не удалось сохранить порядок подборок');
            }
        }
        folderOrderToggle.addEventListener('click', async () => {
            const editing = folderList.classList.contains('order-editing');
            if(!editing){
                folderOrderChanged = false;
                setFolderOrderEditing(true);
                return;
            }
            folderOrderToggle.disabled = true;
            try{
                if(folderOrderChanged) await saveFolderOrder();
                setFolderOrderEditing(false);
            }catch(error){
                window.alert(error.message);
                window.location.reload();
            }finally{
                folderOrderToggle.disabled = false;
            }
        });
        folderList.addEventListener('dragstart', event => {
            const row = event.target.closest('[data-folder-row]');
            if(!row || !folderList.classList.contains('order-editing')) return;
            draggedFolderRow = row;
            row.classList.add('folder-dragging');
            event.dataTransfer.effectAllowed = 'move';
        });
        folderList.addEventListener('dragover', event => {
            if(!draggedFolderRow) return;
            const target = event.target.closest('[data-folder-row]');
            if(!target || target === draggedFolderRow) return;
            event.preventDefault();
            orderedFolderRows().forEach(row => row.classList.remove('folder-drag-over'));
            target.classList.add('folder-drag-over');
            const bounds = target.getBoundingClientRect();
            folderList.insertBefore(
                draggedFolderRow,
                event.clientY < bounds.top + bounds.height / 2 ? target : target.nextSibling
            );
            folderOrderChanged = true;
        });
        folderList.addEventListener('drop', event => event.preventDefault());
        folderList.addEventListener('dragend', () => {
            orderedFolderRows().forEach(row => row.classList.remove('folder-dragging', 'folder-drag-over'));
            draggedFolderRow = null;
        });
    }
    </script>
</main></body></html>
"""


NOTES_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Заметки — Монитор</title>
    <style>
        :root{--paper:#f5f1e8;--surface:#fffcf6;--ink:#171815;--muted:#777267;--line:#d8d1c5;--coral:#e44f45;--green:#3e7655;--violet:#7262a5}
        *{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at 0 0,#fff 0,transparent 34rem),var(--paper);font-family:Inter,Manrope,"Segoe UI",Arial,sans-serif}a{color:inherit;text-decoration:none}button,input,select,textarea{font:inherit}button{cursor:pointer}.shell{width:min(1350px,calc(100% - 38px));margin:auto;padding:26px 0 70px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px}.back,.account{color:var(--muted);font-size:13px}.test{padding:5px 9px;border-radius:999px;color:#a13b34;background:#fff0eb;font-size:10px;font-weight:800;letter-spacing:.08em}.hero{margin:34px 0 20px;display:flex;align-items:end;justify-content:space-between;gap:20px}.hero h1{margin:0;font-size:clamp(42px,6vw,68px);line-height:1;letter-spacing:-.055em}.hero p{margin:9px 0 0;color:var(--muted)}.tabs{display:flex;gap:7px;margin-bottom:16px;padding-bottom:1px;overflow:auto}.tab{min-height:44px;padding:0 17px;display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:7px 7px 0 0;color:var(--muted);background:#eee8dd;font-size:13px;font-weight:700;white-space:nowrap}.tab.active{color:var(--coral);border-bottom-color:var(--surface);background:var(--surface)}.panel{border:1px solid var(--line);border-radius:8px;background:var(--surface);overflow:hidden}.panel-head{min-height:66px;padding:13px 18px;display:flex;align-items:center;justify-content:space-between;gap:14px;border-bottom:1px solid var(--line)}.panel-head h2,.panel-head h3{margin:0;font-size:18px}.panel-head p{margin:4px 0 0;color:var(--muted);font-size:12px}.message,.error{margin:0 0 14px;padding:12px 15px;border-left:3px solid var(--green);background:#eef8f0;font-size:13px}.error{color:#9d302a;border-color:var(--coral);background:#fff1ed}.button,button{min-height:39px;padding:0 13px;border:1px solid var(--coral);border-radius:6px;color:var(--coral);background:transparent;font-weight:700;font-size:12px}.primary{color:#fff;background:var(--coral)}.secondary{color:var(--muted);border-color:var(--line)}label{display:grid;gap:6px;color:var(--muted);font-size:11px}input,select,textarea{width:100%;padding:10px 11px;border:1px solid #c9c1b5;border-radius:6px;color:var(--ink);background:#fff}input,select{height:42px}textarea{min-height:105px;resize:vertical}.form{display:grid;gap:12px;padding:16px}.form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.form-actions{display:flex;justify-content:flex-end;gap:8px}.share-users{max-height:120px;overflow:auto;padding:8px;border:1px solid var(--line);border-radius:6px;background:#fff}.share-user{display:flex;grid-template:none;align-items:center;gap:8px;margin:4px 0}.share-user input{width:auto;height:auto}.calendar-layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(310px,.7fr);gap:16px;align-items:start}.month-nav{display:flex;align-items:center;gap:7px}.calendar{display:grid;grid-template-columns:repeat(7,1fr)}.weekday{padding:10px 8px;color:var(--muted);text-align:center;font-size:10px;font-weight:800;text-transform:uppercase}.day{min-height:104px;padding:8px;display:block;border:0;border-top:1px solid var(--line);border-right:1px solid var(--line);border-radius:0;color:var(--ink);background:#fff;text-align:left}.day:nth-child(7n){border-right:0}.day.outside{color:#aaa49a;background:#f2ede4}.day.selected{background:#fff0ea;box-shadow:inset 0 0 0 2px var(--coral)}.day time{display:block;margin-bottom:7px;font-weight:800}.event-chip{display:block;margin:4px 0;padding:5px 6px;border-radius:4px;color:#9f3d36;background:#fff0eb;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.event-chip.green{color:var(--green);background:#edf6ef}.event-list{display:grid;gap:9px;padding:15px;border-bottom:1px solid var(--line)}.event-card{padding:12px;border:1px solid var(--line);border-radius:6px;background:#fff}.event-card strong{display:block;margin-bottom:5px}.event-meta{color:var(--muted);font-size:12px}.event-actions{display:flex;gap:7px;margin-top:9px}.event-actions form{margin:0}.empty{padding:34px 20px;color:var(--muted);text-align:center}.records-layout{display:grid;grid-template-columns:230px 320px minmax(0,1fr);min-height:610px}.column{min-width:0;border-right:1px solid var(--line)}.column:last-child{border-right:0}.column-title{padding:15px 17px;border-bottom:1px solid var(--line);color:var(--muted);font-size:10px;font-weight:800;text-transform:uppercase}.list{padding:8px}.list-link{display:block;margin-bottom:3px;padding:11px;border-radius:5px;color:#575149;font-size:13px}.list-link:hover,.list-link.active{color:var(--coral);background:#fff0ea}.list-link strong,.list-link span{display:block}.list-link span{margin-top:4px;color:var(--muted);font-size:11px}.editor textarea{min-height:260px}.dictionary-layout{display:grid;grid-template-columns:235px minmax(0,1fr) 330px;gap:16px;align-items:start}.deck-list{padding:9px}.summary{padding:16px;border-bottom:1px solid var(--line)}.summary strong,.summary span{display:block}.summary span{margin-top:4px;color:var(--muted);font-size:12px}.word-table{width:100%;border-collapse:collapse}.word-table th,.word-table td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;font-size:12px}.word-table th{color:var(--muted);background:#faf6ef;font-size:10px;text-transform:uppercase}.term{font-size:19px!important}.quiz{padding:16px}.flashcard{min-height:230px;padding:23px;display:grid;place-items:center;border:1px solid var(--line);border-radius:8px;background:#fff;text-align:center}.flashcard .term{font-size:38px!important}.answer{margin-top:16px;padding-top:15px;border-top:1px solid var(--line)}.answer strong,.answer span{display:block}.answer span{margin-top:5px;color:var(--muted)}details summary{list-style:none}details summary::-webkit-details-marker{display:none}.ratings{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:10px}.ratings form,.ratings button{width:100%}.muted{color:var(--muted);font-size:12px}.danger{color:#9d302a;border-color:#dca39d}.access-pill{display:inline-block;margin-top:8px;padding:4px 7px;border-radius:999px;color:var(--green);background:#edf6ef;font-size:10px}.folder-filter{display:flex;align-items:center;justify-content:space-between}.folder-filter b{font-size:10px}@media(max-width:1050px){.calendar-layout,.dictionary-layout{grid-template-columns:1fr}.records-layout{grid-template-columns:200px 1fr}.records-layout .editor{grid-column:1/-1;border-top:1px solid var(--line)}.calendar .day{min-height:88px}}@media(max-width:700px){.shell{width:min(100% - 24px,1350px)}.hero{align-items:flex-start;flex-direction:column}.calendar{min-width:720px}.calendar-scroll{overflow:auto}.records-layout{grid-template-columns:1fr}.column{border-right:0;border-bottom:1px solid var(--line)}.form-row{grid-template-columns:1fr}.word-table{min-width:600px}.table-scroll{overflow:auto}}
    </style>
</head>
<body><main class="shell">
    <div class="top"><a class="back" href="/">← Вернуться к Монитору</a><div><span class="test">ТЕСТ · ТОЛЬКО АДМИНИСТРАТОР</span> <a class="account" href="/account">{{current_user.username}}</a></div></div>
    <header class="hero"><div><h1>Заметки</h1><p>Календарь, рабочие записи и личные учебные карточки</p></div></header>
    {% if message %}<p class="message">{{message}}</p>{% endif %}{% if error %}<p class="error">{{error}}</p>{% endif %}
    <nav class="tabs"><a class="tab {{'active' if view == 'calendar' else ''}}" href="/notes?view=calendar">Календарь</a><a class="tab {{'active' if view == 'records' else ''}}" href="/notes?view=records">Записи</a><a class="tab {{'active' if view == 'dictionary' else ''}}" href="/notes?view=dictionary">Словарь и квиз</a></nav>

    {% if view == 'calendar' %}
    <div class="calendar-layout">
        <section class="panel">
            <div class="panel-head"><div><h2>{{month_label}}</h2><p>Нажми на день, чтобы посмотреть его мероприятия</p></div><div class="month-nav"><a class="button secondary" href="{{previous_month_url}}">←</a><a class="button secondary" href="{{today_url}}">Сегодня</a><a class="button secondary" href="{{next_month_url}}">→</a></div></div>
            <div class="calendar-scroll"><div class="calendar"><div class="weekday">Пн</div><div class="weekday">Вт</div><div class="weekday">Ср</div><div class="weekday">Чт</div><div class="weekday">Пт</div><div class="weekday">Сб</div><div class="weekday">Вс</div>{% for day in calendar_days %}<a class="day {{'outside' if not day.in_month else ''}} {{'selected' if day.iso == selected_date else ''}}" href="{{day.url}}"><time>{{day.number}}</time>{% for event in day.events[:3] %}<span class="event-chip {{'green' if loop.index is even else ''}}">{{event.event_time or 'Весь день'}} · {{event.title}}</span>{% endfor %}{% if day.events|length > 3 %}<span class="muted">ещё {{day.events|length - 3}}</span>{% endif %}</a>{% endfor %}</div></div>
        </section>
        <aside class="panel">
            <div class="panel-head"><div><h3>{{selected_date_label}}</h3><p>{{selected_events|length}} мероприятий</p></div><a class="button" href="{{new_event_url}}">+ Добавить</a></div>
            {% if selected_events %}<div class="event-list">{% for event in selected_events %}<article class="event-card"><strong>{{event.event_time or 'Весь день'}} · {{event.title}}</strong>{% if event.place %}<div class="event-meta">{{event.place}}</div>{% endif %}{% if event.description %}<p class="muted">{{event.description}}</p>{% endif %}<span class="access-pill">{{access_labels[event.visibility]}}{% if event.shared_users %} · {{event.shared_users|map(attribute='username')|join(', ')}}{% endif %}</span><div class="event-actions"><a class="button secondary" href="{{event.edit_url}}">Изменить</a><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="delete_event"><input type="hidden" name="event_id" value="{{event.id}}"><input type="hidden" name="return_date" value="{{selected_date}}"><button class="danger" type="submit">Удалить</button></form></div></article>{% endfor %}</div>{% else %}<div class="empty">На этот день мероприятий нет.</div>{% endif %}
            <form class="form" method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="save_event"><input type="hidden" name="event_id" value="{{event_form.id or ''}}"><label>Название<input name="title" value="{{event_form.title}}" maxlength="200" required></label><div class="form-row"><label>Дата<input type="date" name="event_date" value="{{event_form.event_date}}" required></label><label>Время<input type="time" name="event_time" value="{{event_form.event_time}}"></label></div><label>Место<input name="place" value="{{event_form.place}}" maxlength="500"></label><label>Комментарий<textarea name="description" maxlength="5000">{{event_form.description}}</textarea></label><label>Доступ<select name="visibility"><option value="private" {{'selected' if event_form.visibility == 'private' else ''}}>Только я</option><option value="selected" {{'selected' if event_form.visibility == 'selected' else ''}}>Выбранные пользователи</option><option value="all" {{'selected' if event_form.visibility == 'all' else ''}}>Все пользователи</option></select></label><div class="share-users">{% for account in available_users %}<label class="share-user"><input type="checkbox" name="shared_user_ids" value="{{account.id}}" {{'checked' if account.id in event_shared_ids else ''}}>{{account.username}}</label>{% else %}<span class="muted">Других пользователей пока нет</span>{% endfor %}</div><div class="form-actions"><button class="primary" type="submit">{{'Сохранить изменения' if event_form.id else 'Создать мероприятие'}}</button></div></form>
        </aside>
    </div>

    {% elif view == 'records' %}
    <section class="panel records-layout">
        <div class="column"><div class="column-title">Папки</div><nav class="list"><a class="list-link folder-filter {{'active' if selected_folder == '' else ''}}" href="/notes?view=records"><span>Все записи</span><b>{{notes|length}}</b></a>{% for folder in note_folders %}<a class="list-link folder-filter {{'active' if selected_folder == folder.name else ''}}" href="{{folder.url}}"><span>{{folder.name}}</span><b>{{folder.count}}</b></a>{% endfor %}</nav></div>
        <div class="column"><div class="column-title">Записи</div><nav class="list">{% for note in filtered_notes %}<a class="list-link {{'active' if selected_note and selected_note.id == note.id else ''}}" href="{{note.url}}"><strong>{{note.title}}</strong><span>{{note.folder}} · {{note.updated_at[:16]|replace('T',' ')}}</span></a>{% else %}<div class="empty">В этой папке пока пусто.</div>{% endfor %}</nav></div>
        <div class="column editor"><div class="panel-head"><div><h3>{{'Редактирование записи' if note_form.id else 'Новая запись'}}</h3><p>Адреса, телефоны, ссылки и рабочий текст</p></div>{% if note_form.id %}<a class="button" href="/notes?view=records{% if selected_folder %}&folder={{selected_folder|urlencode}}{% endif %}">+ Новая</a>{% endif %}</div><form class="form" method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="save_note"><input type="hidden" name="note_id" value="{{note_form.id or ''}}"><label>Папка<input name="folder" value="{{note_form.folder}}" maxlength="80" placeholder="Например: Контакты"></label><label>Заголовок<input name="title" value="{{note_form.title}}" maxlength="200" required></label><label>Текст<textarea name="body" maxlength="20000" placeholder="Телефоны, адреса, ссылки, комментарии…">{{note_form.body}}</textarea></label><label>Доступ<select name="visibility"><option value="private" {{'selected' if note_form.visibility == 'private' else ''}}>Только я</option><option value="selected" {{'selected' if note_form.visibility == 'selected' else ''}}>Выбранные пользователи</option><option value="all" {{'selected' if note_form.visibility == 'all' else ''}}>Все пользователи</option></select></label><div class="share-users">{% for account in available_users %}<label class="share-user"><input type="checkbox" name="shared_user_ids" value="{{account.id}}" {{'checked' if account.id in note_shared_ids else ''}}>{{account.username}}</label>{% else %}<span class="muted">Других пользователей пока нет</span>{% endfor %}</div><div class="form-actions">{% if note_form.id %}<button class="danger" type="submit" name="action" value="delete_note">Удалить</button>{% endif %}<button class="primary" type="submit">Сохранить</button></div></form></div>
    </section>

    {% else %}
    <div class="dictionary-layout">
        <aside class="panel"><div class="summary"><strong>{{deck_total}} словарей</strong><span>{{due_total}} карточек на сегодня</span></div><nav class="deck-list">{% for deck in decks %}<a class="list-link folder-filter {{'active' if selected_deck and selected_deck.id == deck.id else ''}}" href="{{deck.url}}"><span>{{deck.name}}<small>{{deck.card_count}} слов · {{deck.due_count}} повторить</small></span><b>›</b></a>{% endfor %}</nav><form class="form" method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="create_deck"><label>Новый словарь<input name="name" maxlength="100" placeholder="Например: Политика" required></label><button class="primary" type="submit">Создать</button></form></aside>
        <section class="panel"><div class="panel-head"><div><h2>{{selected_deck.name if selected_deck else 'Словарь'}}</h2><p>Иероглиф, чтение и перевод</p></div></div>{% if selected_deck %}<div class="table-scroll"><table class="word-table"><thead><tr><th>Слово</th><th>Чтение</th><th>Перевод</th><th>Следующий повтор</th></tr></thead><tbody>{% for card in cards %}<tr><td class="term">{{card.term}}</td><td>{{card.reading or '—'}}</td><td>{{card.translation}}</td><td>{{card.next_review or 'сегодня'}}</td></tr>{% else %}<tr><td colspan="4" class="muted">Добавь первую карточку.</td></tr>{% endfor %}</tbody></table></div><form class="form" method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="add_card"><input type="hidden" name="deck_id" value="{{selected_deck.id}}"><div class="form-row"><label>Слово / иероглиф<input name="term" maxlength="200" required></label><label>Чтение<input name="reading" maxlength="300"></label></div><label>Перевод<input name="translation" maxlength="1000" required></label><div class="form-actions"><button class="primary" type="submit">Добавить карточку</button></div></form>{% else %}<div class="empty">Создай словарь слева.</div>{% endif %}</section>
        <aside class="panel"><div class="panel-head"><div><h3>Квиз на сегодня</h3><p>Интервальные повторения</p></div></div><div class="quiz">{% if quiz_card %}<details><summary class="button primary" style="display:grid;place-items:center">Показать ответ</summary><div class="flashcard"><div><div class="term">{{quiz_card.term}}</div><div class="muted">Вспомни чтение и перевод</div><div class="answer"><strong>{{quiz_card.reading or 'Без чтения'}}</strong><span>{{quiz_card.translation}}</span></div></div></div><div class="ratings">{% for rating,label in ratings %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><input type="hidden" name="action" value="review_card"><input type="hidden" name="card_id" value="{{quiz_card.id}}"><input type="hidden" name="deck_id" value="{{selected_deck.id}}"><input type="hidden" name="rating" value="{{rating}}"><button type="submit">{{label}}</button></form>{% endfor %}</div></details>{% elif selected_deck %}<div class="empty">Все карточки на сегодня повторены 🎉</div>{% else %}<div class="empty">Выбери или создай словарь.</div>{% endif %}</div></aside>
    </div>
    {% endif %}
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
        .source-summary{flex:0 0 auto;display:flex;align-items:center;gap:10px;padding:0 14px;color:var(--muted);font-size:12px}
        .source-summary a{color:var(--coral-dark);font-weight:700}
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
        .chips a{padding:5px 9px;color:var(--coral-dark);border:1px solid rgba(228,79,69,.4);border-radius:5px;background:#fffaf5;font-size:12px}
        .chips a:hover,.chips a.active{border-color:var(--coral);background:#fff0e9}
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
            width:100%;min-width:0;min-height:40px;padding:0 7px 0 18px;display:grid;flex:1;
            grid-template-columns:20px minmax(0,1fr) auto;align-items:center;
            gap:9px;border:0;color:inherit;background:transparent;text-align:left
        }
        .source-link>span:nth-child(2){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .check{width:16px;height:16px;display:grid;place-items:center;color:#fff;border:1px solid #bdb5a9;border-radius:3px;font-size:11px}
        .source-row.active .check{border-color:var(--coral);background:var(--coral)}
        .yahoo-source-toggle{width:100%;border:0;color:inherit;background:transparent}
        .yahoo-source-toggle.source-link{grid-template-columns:20px minmax(0,1fr) auto auto}
        .yahoo-chevron{color:var(--muted);font-size:14px;transition:transform .2s}
        .source-list.yahoo-expanded .yahoo-chevron{transform:rotate(180deg)}
        .yahoo-source-row{max-height:0;min-height:0;padding-left:20px;overflow:hidden;opacity:0;transition:max-height .22s ease,opacity .18s ease}
        .source-list.yahoo-expanded .yahoo-source-row{max-height:44px;min-height:40px;opacity:1}
        .yahoo-source-row .source-link{padding-left:8px}
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
        .keyword-list{display:flex;flex-wrap:wrap;gap:9px}.keyword-chip{display:flex;align-items:center;gap:4px;padding:4px;border:1px solid var(--line);border-radius:999px;background:#fff}
        .keyword-chip.active{border-color:var(--coral);background:#fff0e9}.keyword-filter{height:28px;padding:0 7px;border:0;color:var(--ink);background:transparent;font-size:13px}.keyword-chip.active .keyword-filter{color:var(--coral-dark);font-weight:700}
        .keyword-remove{width:22px;height:22px;padding:0;border:0;border-radius:50%;color:var(--coral-dark);background:#fff1ed}.keyword-reset{height:38px;padding:0 13px;border:1px solid var(--line);border-radius:999px;color:var(--muted);background:#fff;font-size:13px}.keyword-reset.active{color:#fff;border-color:var(--coral);background:var(--coral)}.form-message{min-height:20px;margin:10px 0 0;color:var(--coral-dark);font-size:13px}
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
            <a class="site-section" href="/collections">
                Подборки
            </a>
            {% if current_user.role == 'admin' %}<a class="site-section" href="/notes">
                Заметки <small style="font-size:8px;color:var(--coral);vertical-align:top">ТЕСТ</small>
            </a>{% endif %}
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
            <a class="tab {{'active' if mode == 'all' else ''}}" href="{{group_home_url}}">Все</a>
            <a class="tab {{'active' if mode == 'found' else ''}}" href="{{group_found_url}}">Совпадения</a>
        </nav>
    </section>

    <section class="toolbar">
        <form class="search" method="get" action="{{current_path}}">
            <span class="search-icon">⌕</span>
            {% for src in source_filters %}<input type="hidden" name="source" value="{{src}}">{% endfor %}
            {% if keyword_filter %}<input type="hidden" name="keyword" value="{{keyword_filter}}">{% endif %}
            <input id="news-search" name="q" value="{{search_query}}"
                   placeholder="Поиск по заголовкам · Enter" autocomplete="off">
        </form>
        {% if source_filters %}<div class="source-summary"><span>Выбрано: {{source_filters|length}}</span><a href="{{clear_sources_url}}">Сбросить</a></div>{% endif %}
        <button class="tool-button {{'active' if keyword_filter else ''}}" id="keywords-open" type="button">✣ {{keyword_filter or 'Ключевые слова'}}</button>
    </section>

    <div class="content-grid">
        <section class="feed">
            <header class="feed-heading">
                <h2>{{feed_title}}</h2>
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
                    <h3><a href="/article?url={{item.url|urlencode}}&back_url={{current_url|urlencode}}" target="_blank" rel="noopener" data-read-url="{{item.url}}">{{item.title}}</a></h3>
                    {% endif %}
                    {% if item.keywords %}
                    <div class="chips">{% for keyword in item.keywords %}<a class="{{'active' if keyword|lower == keyword_filter|lower else ''}}" href="{{keyword_urls.get(keyword, group_found_url)}}">{{keyword}}</a>{% endfor %}</div>
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
                <div class="source-list {{'yahoo-expanded' if yahoo_expanded else ''}}" id="source-list">
                    <div class="source-row {{'active' if not source_filters else ''}}">
                        <button class="source-link" type="button" data-source-clear>
                            <span class="check">{{'✓' if not source_filters else ''}}</span>
                            <span>Все источники</span>
                            <span class="unread-count" data-unread-source="__all__"></span>
                        </button>
                    </div>
                    {% for src, count in sidebar_sources %}
                    <div class="source-row sortable-source {{'active' if src in source_filters else ''}}" data-source-row data-source-name="{{src}}">
                        <span class="source-drag-handle" aria-hidden="true">⋮⋮</span>
                        <button class="source-link" type="button" data-source-filter="{{src}}">
                            <span class="check">{{'✓' if src in source_filters else ''}}</span>
                            <span>{{src}}</span>
                            <span class="unread-count" data-unread-source="{{src}}"></span>
                        </button>
                    </div>
                    {% endfor %}
                    {% if yahoo_sources %}
                    <div class="source-row yahoo-source-header {{'active' if yahoo_active else ''}}">
                        <button class="source-link yahoo-source-toggle" id="yahoo-source-toggle" type="button" aria-expanded="{{'true' if yahoo_expanded else 'false'}}" aria-controls="yahoo-source-items">
                            <span class="check">{{'✓' if yahoo_active else ''}}</span>
                            <span>Yahoo! JAPAN</span>
                            <span class="unread-count" data-unread-source="__yahoo__"></span>
                            <span class="yahoo-chevron" aria-hidden="true">⌄</span>
                        </button>
                    </div>
                    <span id="yahoo-source-items"></span>
                    {% for src, count, label in yahoo_sources %}
                    <div class="source-row sortable-source yahoo-source-row {{'active' if src in source_filters else ''}}" data-source-row data-source-name="{{src}}">
                        <span class="source-drag-handle" aria-hidden="true">⋮⋮</span>
                        <button class="source-link" type="button" data-source-filter="{{src}}">
                            <span class="check">{{'✓' if src in source_filters else ''}}</span>
                            <span>{{label}}</span>
                            <span class="unread-count" data-unread-source="{{src}}"></span>
                        </button>
                    </div>
                    {% endfor %}
                    {% endif %}
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
            <div><h2 id="keyword-title">Ключевые слова</h2><p>Нажми на слово, чтобы показать совпадения только с ним.</p></div>
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
    let newsIndex = {{news_index|tojson}};
    const sourceFilterHome = {{filter_home|tojson}};
    const keywordFilterHome = {{group_found|tojson}};
    const selectedKeyword = {{keyword_filter|tojson}};
    const selectedSources = new Set({{source_filters|tojson}});
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

    let unread = new Set();

    async function initializeUnread(){
        try{
            const response = await fetch(
                '/api/news-index?group=' + encodeURIComponent(currentSourceGroup),
                {credentials:'same-origin'}
            );
            if(response.ok){
                const data = await response.json();
                if(Array.isArray(data.items)) newsIndex = data.items;
            }
        }catch(error){
            // Карточки уже доступны; счётчики обновятся при следующем открытии.
        }
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
        unread = new Set(unreadState.unread);
        refreshUnread();
    }

    function saveUnread(){
        if(!unreadState) return;
        unreadState.unread = [...unread];
        localStorage.setItem(unreadStorageKey, JSON.stringify(unreadState));
    }

    function refreshUnread(){
        const counts = {};
        let groupUnreadCount = 0;
        let yahooUnreadCount = 0;
        newsIndex.forEach(item => {
            if(unread.has(item.url)){
                groupUnreadCount++;
                counts[item.source] = (counts[item.source] || 0) + 1;
                if(item.source.startsWith('Yahoo! JAPAN')) yahooUnreadCount++;
            }
        });
        document.querySelectorAll('[data-unread-source]').forEach(badge => {
            const source = badge.dataset.unreadSource;
            const count = source === '__all__'
                ? groupUnreadCount
                : (source === '__yahoo__' ? yahooUnreadCount : (counts[source] || 0));
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
        if(savedCount){
            savedCount.textContent = saved.size;
            savedCount.classList.toggle('hidden', saved.size === 0);
        }
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
    initializeUnread();
    search.addEventListener('input', applyFilters);
    document.getElementById('collapse-sources').addEventListener('click', event => {
        const list = document.getElementById('source-list');
        list.classList.toggle('hidden');
        event.currentTarget.textContent = list.classList.contains('hidden') ? '+' : '−';
    });
    const sourceList = document.getElementById('source-list');
    const yahooSourceToggle = document.getElementById('yahoo-source-toggle');
    if(yahooSourceToggle){
        yahooSourceToggle.addEventListener('click', () => {
            const expanded = sourceList.classList.toggle('yahoo-expanded');
            yahooSourceToggle.setAttribute('aria-expanded', String(expanded));
        });
    }
    function filteredSourceUrl(sources){
        const target = new URL(sourceFilterHome, window.location.origin);
        const current = new URL(window.location.href);
        current.searchParams.forEach((value, key) => {
            if(key !== 'source' && key !== 'page') target.searchParams.append(key, value);
        });
        sources.forEach(source => target.searchParams.append('source', source));
        return target.pathname + target.search;
    }
    document.querySelector('[data-source-clear]').addEventListener('click', () => {
        window.location.href = filteredSourceUrl([]);
    });
    document.querySelectorAll('[data-source-filter]').forEach(button => {
        button.addEventListener('click', () => {
            const source = button.dataset.sourceFilter;
            selectedSources.has(source)
                ? selectedSources.delete(source)
                : selectedSources.add(source);
            window.location.href = filteredSourceUrl([...selectedSources]);
        });
    });
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
        if(editing && yahooSourceToggle){
            sourceList.classList.add('yahoo-expanded');
            yahooSourceToggle.setAttribute('aria-expanded', 'true');
        }
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
        if(
            target.classList.contains('yahoo-source-row') !==
            draggedSourceRow.classList.contains('yahoo-source-row')
        ) return;
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
    function keywordUrl(word){
        const target = new URL(keywordFilterHome, window.location.origin);
        const current = new URL(window.location.href);
        current.searchParams.forEach((value, key) => {
            if(key !== 'keyword' && key !== 'page') target.searchParams.append(key, value);
        });
        if(word) target.searchParams.set('keyword', word);
        return target.pathname + target.search;
    }
    function renderKeywords(words){
        const reset = document.createElement('button');
        reset.type = 'button';
        reset.className = 'keyword-reset' + (selectedKeyword ? '' : ' active');
        reset.textContent = 'Все ключевые слова';
        reset.addEventListener('click', () => { window.location.href = keywordUrl(''); });
        const chips = words.map(word => {
            const chip = document.createElement('span'); chip.className = 'keyword-chip';
            const active = word.localeCompare(selectedKeyword, undefined, {sensitivity:'accent'}) === 0;
            if(active) chip.classList.add('active');
            const label = document.createElement('button');
            label.type = 'button'; label.className = 'keyword-filter'; label.textContent = word;
            label.setAttribute('aria-pressed', String(active));
            label.addEventListener('click', () => {
                window.location.href = keywordUrl(active ? '' : word);
            });
            const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'keyword-remove'; remove.textContent = '×';
            remove.setAttribute('aria-label', 'Удалить ' + word);
            remove.addEventListener('click', () => changeKeyword('DELETE', word));
            chip.append(label, remove); return chip;
        });
        keywordList.replaceChildren(reset, ...chips);
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
        if(method === 'DELETE' && keyword.localeCompare(selectedKeyword, undefined, {sensitivity:'accent'}) === 0){
            window.location.href = keywordUrl('');
            return;
        }
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
    <a class="back" id="article-back" href="{{back_url}}">← Вернуться к ленте</a>
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
</main>
<script>
    const articleBack = document.getElementById('article-back');
    articleBack.addEventListener('click', event => {
        if(
            event.button !== 0 || event.ctrlKey || event.metaKey ||
            event.shiftKey || event.altKey || window.history.length < 2
        ) return;
        try{
            if(!document.referrer || new URL(document.referrer).origin !== window.location.origin) return;
        }catch(error){
            return;
        }
        event.preventDefault();
        window.history.back();
    });
</script>
</body></html>
"""


def load_json(filename, default):
    # Новости теперь живут в SQLite. Имя функции оставлено прежним,
    # чтобы маршруты и тесты интерфейса не пришлось переписывать целиком.
    collection_loaders = {
        "all_news.json": load_all_news,
        "found_news.json": load_found_news,
    }
    loader = collection_loaders.get(filename)
    if loader is not None:
        request_cache = None
        if has_request_context():
            request_cache = getattr(g, "_news_collection_cache", None)
            if request_cache is None:
                request_cache = {}
                g._news_collection_cache = request_cache
            if filename in request_cache:
                return request_cache[filename]
        result = loader()
        if request_cache is not None:
            request_cache[filename] = result
        return result

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


def _request_host():
    """Возвращает имя узла без порта для строгой проверки Host."""
    host = str(request.host or "").strip().casefold().rstrip(".")
    if host.startswith("["):
        return host.partition("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def _client_address():
    return str(request.remote_addr or "unknown")[:80]


def _login_limit_keys(username):
    address = _client_address()
    account = " ".join(str(username or "").split()).casefold()[:80]
    return (
        (LOGIN_PAIR_LIMITER, f"{address}|{account}"),
        (LOGIN_ACCOUNT_LIMITER, account),
        (LOGIN_IP_LIMITER, address),
    )


def _login_retry_after(username):
    return max(
        limiter.retry_after(key)
        for limiter, key in _login_limit_keys(username)
    )


def _register_login_failure(username):
    return max(
        limiter.register_failure(key)
        for limiter, key in _login_limit_keys(username)
    )


def _clear_login_failures(username):
    for limiter, key in _login_limit_keys(username):
        limiter.clear(key)


@app.before_request
def validate_request_host():
    """Отклоняет подменённый Host после включения публичного режима."""
    allowed = app.config.get("ALLOWED_HOSTS") or set()
    if allowed and _request_host() not in allowed | {"127.0.0.1", "localhost"}:
        abort(400)


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
    if endpoint in {"static", "healthz"}:
        return None

    users_exist = count_users() > 0
    if not users_exist:
        if app.config.get("ALLOWED_HOSTS") and not _enabled_setting(
            "MONITOR_ALLOW_REMOTE_SETUP"
        ):
            abort(403)
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


@app.after_request
def add_security_headers(response):
    """Добавляет безопасные браузерные настройки ко всем ответам."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'self'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'",
    )
    if request.endpoint != "static":
        fast_navigation_response = (
            request.method == "GET"
            and request.endpoint in FAST_NAVIGATION_ENDPOINTS
            and response.status_code == 200
        )
        if fast_navigation_response:
            # Это только приватный кэш конкретного браузера. Короткое окно
            # убирает повторную загрузку после статьи и позволяет безопасно
            # подогреть соседний раздел, не кэшируя вход и админские формы.
            response.headers.setdefault(
                "Cache-Control",
                "private, max-age=30, must-revalidate",
            )
            response.vary.add("Cookie")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
    if app.config.get("SESSION_COOKIE_SECURE") and request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.get("/healthz")
def healthz():
    """Лёгкая проверка для Nginx и systemd без раскрытия данных проекта."""
    return jsonify(status="ok")


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
    retry_after = 0
    username = str(request.form.get("username", "")).strip()
    next_url = safe_next_url(request.values.get("next", "/"))
    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        retry_after = _login_retry_after(username)
        if retry_after:
            error = "Слишком много попыток. Попробуйте немного позже."
        else:
            user = authenticate_user(username, request.form.get("password", ""))
            if user is None:
                retry_after = _register_login_failure(username)
                error = (
                    "Слишком много попыток. Попробуйте немного позже."
                    if retry_after
                    else "Неверный логин или пароль"
                )
                security_logger.info(
                    "Неудачный вход: пользователь=%r адрес=%s",
                    " ".join(username.split())[:80],
                    _client_address(),
                )
                if retry_after:
                    security_logger.warning(
                        "Временная блокировка входа: пользователь=%r адрес=%s",
                        " ".join(username.split())[:80],
                        _client_address(),
                    )
            else:
                _clear_login_failures(username)
                security_logger.info(
                    "Успешный вход: пользователь=%r адрес=%s",
                    user["username"],
                    _client_address(),
                )
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                csrf_token()
                return redirect(next_url)
    rendered = render_template_string(
        AUTH_HTML,
        mode="login",
        error=error,
        username=username,
        csrf_token=csrf_token(),
        next_url=next_url,
    )
    if retry_after:
        return rendered, 429, {"Retry-After": str(retry_after)}
    return rendered


@app.post("/logout")
def logout():
    """Завершает текущую пользовательскую сессию."""
    if not csrf_is_valid():
        abort(400)
    session.clear()
    response = redirect(url_for("login"))
    # Приватный кэш ускоряет навигацию только внутри активной сессии.
    # При выходе браузеру явно поручается удалить сохранённые страницы.
    response.headers["Clear-Site-Data"] = '"cache"'
    return response


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
    """Управляет аккаунтами и позволяет администратору удалить чужой аккаунт."""
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
                elif action == "delete":
                    if target["id"] == administrator["id"]:
                        raise ValueError("Нельзя удалить собственный аккаунт")
                    deleted_name = delete_user(target["id"])
                    message = f"Пользователь {deleted_name} удалён"
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


def _format_file_size(value):
    """Показывает размер файла без технических байтовых чисел."""
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        size = 0
    units = ("Б", "КБ", "МБ", "ГБ")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "Б" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} Б"


def _format_duration(value):
    """Показывает длительность инцидента компактно и без секундного шума."""
    try:
        seconds = max(0, int(value))
    except (TypeError, ValueError):
        seconds = 0
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} д. {hours} ч."
    if hours:
        return f"{hours} ч. {minutes} мин."
    return f"{max(1, minutes)} мин."


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
            "failure_streak": parser_status.get("failure_streak", 0),
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

    alerts = source_alerts(prepared_sources)

    return render_template_string(
        ADMIN_SOURCES_HTML,
        sources=prepared_sources,
        jobs=prepared_jobs,
        summary=summary,
        alerts=alerts,
        alert_counts=alert_summary(alerts),
        kyodo_vpn=kyodo_proxy_status(),
        auto_refresh=any(job["status"] in {"pending", "running"} for job in jobs),
        current_user=administrator,
        csrf_token=csrf_token(),
        message=str(request.args.get("message", "")).strip(),
        error=str(request.args.get("error", "")).strip(),
    )


@app.route("/admin/system", methods=["GET", "POST"])
def admin_system():
    """Показывает состояние SQLite, копии базы и хвост журнала ошибок."""
    administrator = current_user()
    if not administrator or administrator.get("role") != "admin":
        abort(403)

    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        action = str(request.form.get("action", "")).strip()
        if action != "backup":
            return redirect(url_for("admin_system", error="Неизвестное действие"))
        try:
            created = create_manual_backup(retention=10)
        except Exception as backup_error:
            return redirect(url_for(
                "admin_system",
                error=(
                    "Не удалось создать резервную копию: "
                    f"{type(backup_error).__name__}: {backup_error}"
                ),
            ))
        return redirect(url_for(
            "admin_system",
            message=f"Создана резервная копия {created['name']}",
        ))

    database = database_stats()
    prepared_database = dict(database)
    prepared_database["size"] = _format_file_size(database.get("size_bytes", 0))
    backups = list_database_backups()
    prepared_backups = []
    for item in backups:
        prepared = dict(item)
        prepared["size"] = _format_file_size(item.get("size_bytes", 0))
        prepared_backups.append(prepared)
    log = error_log_stats()
    log["size"] = _format_file_size(log.get("size_bytes", 0))
    alerts = system_alerts(database, backups)

    return render_template_string(
        ADMIN_SYSTEM_HTML,
        database=prepared_database,
        backups=prepared_backups,
        errors=list(reversed(read_recent_errors(limit=120))),
        log=log,
        alerts=alerts,
        alert_counts=alert_summary(alerts),
        version=PROJECT_VERSION,
        current_user=administrator,
        csrf_token=csrf_token(),
        message=str(request.args.get("message", "")).strip(),
        error=str(request.args.get("error", "")).strip(),
    )


@app.route("/admin/incidents")
def admin_incidents():
    """Показывает администраторам историю сбоев и восстановлений."""
    administrator = current_user()
    if not administrator or administrator.get("role") != "admin":
        abort(403)
    state = str(request.args.get("state", "all")).strip().casefold()
    if state not in {"all", "active", "resolved"}:
        state = "all"
    prepared = []
    for incident in list_source_incidents(state=state, limit=250):
        item = dict(incident)
        item["duration"] = _format_duration(item.get("duration_seconds", 0))
        item["status_label"] = (
            "Критично"
            if item["is_active"] and item["level"] == "critical"
            else ("Внимание" if item["is_active"] else "Восстановлен")
        )
        prepared.append(item)
    return render_template_string(
        ADMIN_INCIDENTS_HTML,
        incidents=prepared,
        summary=source_incident_statistics(),
        state=state,
        current_user=administrator,
    )


@app.route("/admin/reliability")
def admin_reliability():
    """Показывает администраторам доступность источников за выбранный период."""
    administrator = current_user()
    if not administrator or administrator.get("role") != "admin":
        abort(403)
    try:
        days = int(request.args.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in {7, 30}:
        days = 7

    registered = _registered_admin_sources()
    group_by_source = dict(registered)
    settings = load_source_settings()
    statistics = source_reliability_statistics(
        days=days,
        sources=[source for source, _group in registered],
    )
    prepared = []
    for raw_item in statistics:
        item = dict(raw_item)
        uptime = item["uptime_percent"]
        item["group_label"] = group_by_source.get(item["source"], "Другие")
        item["enabled"] = settings.get(item["source"], {}).get("enabled", True)
        item["uptime_display"] = f"{uptime:.3f}".rstrip("0").rstrip(".")
        item["uptime_class"] = (
            "bad" if uptime < 95 else ("warn" if uptime < 99.5 else "good")
        )
        item["downtime"] = (
            _format_duration(item["downtime_seconds"])
            if item["downtime_seconds"]
            else "—"
        )
        item["average_duration"] = (
            _format_duration(item["average_incident_seconds"])
            if item["average_incident_seconds"]
            else "—"
        )
        prepared.append(item)

    total = len(prepared)
    average_uptime = (
        sum(item["uptime_percent"] for item in prepared) / total
        if total
        else 100
    )
    total_downtime = sum(item["downtime_seconds"] for item in prepared)
    return render_template_string(
        ADMIN_RELIABILITY_HTML,
        sources=prepared,
        days=days,
        summary={
            "average_uptime": f"{average_uptime:.3f}".rstrip("0").rstrip("."),
            "incidents": sum(item["incident_count"] for item in prepared),
            "downtime": (
                _format_duration(total_downtime) if total_downtime else "0 мин."
            ),
            "affected": sum(item["incident_count"] > 0 for item in prepared),
            "total": total,
        },
        current_user=administrator,
    )


def _matches_collection_search(item, query, fields):
    if not query:
        return True
    haystack = "\n".join(str(item.get(field, "") or "") for field in fields)
    return query.casefold() in haystack.casefold()


def _prepare_collection_note(note):
    """Оставляет в ленте первый абзац или до 650 знаков."""
    prepared = dict(note)
    body = str(prepared.get("body", "") or "").strip()
    paragraph_break = re.search(r"\n\s*\n", body)
    preview_limit = min(paragraph_break.start() if paragraph_break else len(body), 650)
    split_at = preview_limit
    if preview_limit == 650 and len(body) > preview_limit:
        word_break = body.rfind(" ", 0, preview_limit)
        if word_break >= 400:
            split_at = word_break
    prepared["body_preview"] = body[:split_at].rstrip()
    prepared["body_remainder"] = body[split_at:] if split_at < len(body) else ""
    return prepared


COLLECTION_SORTS = {
    "newest": "Сначала новые",
    "oldest": "Сначала старые",
    "title": "По заголовку",
    "source": "По источнику",
}


def _collection_materials(bookmarks, notes, sort_mode="newest"):
    """Объединяет статьи из ленты и добавленные вручную материалы для сортировки."""
    materials = []
    for note in notes:
        item = dict(note)
        item["kind"] = "note"
        item["date"] = item.get("publication_date", "")
        materials.append(item)
    for bookmark in bookmarks:
        item = dict(bookmark)
        item["kind"] = "bookmark"
        item["publication_date"] = item.get("date", "")
        materials.append(item)

    sort_mode = sort_mode if sort_mode in COLLECTION_SORTS else "newest"
    if sort_mode in {"title", "source"}:
        field = sort_mode
        return sorted(
            materials,
            key=lambda item: (
                str(item.get(field, "") or "").casefold(),
                str(item.get("title", "") or "").casefold(),
            ),
        )

    def date_key(item):
        return (
            bool(item.get("publication_date")),
            str(item.get("publication_date", "") or ""),
            str(item.get("updated_at", "") or item.get("created_at", "") or ""),
            int(item.get("id", 0)),
        )

    return sorted(materials, key=date_key, reverse=sort_mode == "newest")


def _collection_export_name(value):
    safe = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "-", str(value or "")).strip("-")
    return (safe or "podborka")[:80] + ".docx"


@app.get("/collections/export.docx")
def export_collection_docx():
    """Скачивает доступную подборку как Word-документ со ссылками и реквизитами."""
    from docx import Document
    from docx.shared import Pt

    user = current_user()
    folder_id = request.args.get("folder")
    collection = load_collection(user["id"], folder_id)
    if collection is None:
        abort(404)
    materials = _collection_materials(
        list_collection_bookmarks(user["id"], folder_id),
        list_collection_notes(user["id"], folder_id),
        request.args.get("sort", "newest"),
    )

    document = Document()
    document.styles["Normal"].font.name = "Arial"
    document.styles["Normal"].font.size = Pt(11)
    document.add_heading(collection["name"], level=0)
    if collection.get("description"):
        document.add_paragraph(collection["description"])
    document.add_paragraph(f"Материалов: {len(materials)}")
    for number, item in enumerate(materials, start=1):
        document.add_heading(f"{number}. {item.get('title') or 'Без заголовка'}", level=1)
        document.add_paragraph(f"Источник: {item.get('source') or 'не указан'}")
        document.add_paragraph(
            f"Дата публикации: {item.get('publication_date') or 'не указана'}"
        )
        document.add_paragraph(f"Ссылка: {item.get('url') or 'не указана'}")

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=_collection_export_name(collection["name"]),
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


MONTH_NAMES_RU = (
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
ACCESS_LABELS = {
    "private": "Только я", "selected": "Выбранные пользователи",
    "all": "Все пользователи",
}


def _notes_admin():
    user = current_user()
    if not user or user.get("role") != "admin":
        abort(403)
    return user


def _notes_redirect(view, **values):
    return redirect(url_for("notes_page", view=view, **values))


@app.route("/notes", methods=["GET", "POST"])
def notes_page():
    """Экспериментальные заметки, доступные только администратору."""
    user = _notes_admin()
    user_id = user["id"]
    view = str(request.values.get("view", "calendar")).strip().casefold()
    if view not in {"calendar", "records", "dictionary"}:
        view = "calendar"

    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        action = str(request.form.get("action", "")).strip()
        try:
            if action == "save_event":
                event_id = save_calendar_event(
                    user_id, request.form.get("title"),
                    request.form.get("event_date"), request.form.get("event_time"),
                    request.form.get("place"), request.form.get("description"),
                    request.form.get("visibility"),
                    request.form.getlist("shared_user_ids"),
                    request.form.get("event_id"),
                )
                event_date = request.form.get("event_date")
                return _notes_redirect(
                    "calendar", selected=event_date, event=event_id,
                    message="Мероприятие сохранено",
                )
            if action == "delete_event":
                delete_calendar_event(user_id, request.form.get("event_id"))
                return _notes_redirect(
                    "calendar", selected=request.form.get("return_date"),
                    message="Мероприятие удалено",
                )
            if action == "save_note":
                if "delete_note" in request.form.getlist("action"):
                    delete_personal_note(user_id, request.form.get("note_id"))
                    return _notes_redirect("records", message="Запись удалена")
                note_id = save_personal_note(
                    user_id, request.form.get("folder"), request.form.get("title"),
                    request.form.get("body"), request.form.get("visibility"),
                    request.form.getlist("shared_user_ids"),
                    request.form.get("note_id"),
                )
                return _notes_redirect(
                    "records", note=note_id, message="Запись сохранена"
                )
            if action == "create_deck":
                deck_id = create_dictionary_deck(user_id, request.form.get("name"))
                return _notes_redirect(
                    "dictionary", deck=deck_id, message="Словарь создан"
                )
            if action == "add_card":
                deck_id = request.form.get("deck_id")
                save_dictionary_card(
                    user_id, deck_id, request.form.get("term"),
                    request.form.get("reading"), request.form.get("translation"),
                )
                return _notes_redirect(
                    "dictionary", deck=deck_id, message="Карточка добавлена"
                )
            if action == "review_card":
                deck_id = request.form.get("deck_id")
                result = review_dictionary_card(
                    user_id, request.form.get("card_id"), request.form.get("rating")
                )
                return _notes_redirect(
                    "dictionary", deck=deck_id,
                    message=f"Следующий повтор: {result['next_review']}",
                )
            raise ValueError("Неизвестное действие")
        except ValueError as operation_error:
            return _notes_redirect(view, error=str(operation_error))

    available_users = [
        account for account in list_users()
        if account["is_active"] and account["id"] != user_id
    ]
    context = {
        "current_user": user,
        "csrf_token": csrf_token(),
        "view": view,
        "available_users": available_users,
        "message": str(request.args.get("message", "")).strip(),
        "error": str(request.args.get("error", "")).strip(),
        "access_labels": ACCESS_LABELS,
    }

    if view == "calendar":
        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
            month = int(request.args.get("month", today.month))
            if not 2000 <= year <= 2100 or not 1 <= month <= 12:
                raise ValueError
        except (TypeError, ValueError):
            year, month = today.year, today.month
        first_day = date(year, month, 1)
        days_in_month = monthrange(year, month)[1]
        last_day = date(year, month, days_in_month)
        grid_start = first_day - timedelta(days=first_day.weekday())
        grid_end = grid_start + timedelta(days=41)
        events = list_calendar_events(
            user_id, grid_start.isoformat(), grid_end.isoformat()
        )
        events_by_date = {}
        for event in events:
            events_by_date.setdefault(event["event_date"], []).append(event)
        selected_date = str(request.args.get("selected", "")).strip()
        try:
            parsed_selected = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except ValueError:
            parsed_selected = today if first_day <= today <= last_day else first_day
            selected_date = parsed_selected.isoformat()
        calendar_days = []
        for offset in range(42):
            item_date = grid_start + timedelta(days=offset)
            calendar_days.append({
                "number": item_date.day,
                "iso": item_date.isoformat(),
                "in_month": item_date.month == month,
                "events": events_by_date.get(item_date.isoformat(), []),
                "url": url_for(
                    "notes_page", view="calendar", year=item_date.year,
                    month=item_date.month, selected=item_date.isoformat(),
                ),
            })
        selected_events = list(events_by_date.get(selected_date, []))
        for event in selected_events:
            event["edit_url"] = url_for(
                "notes_page", view="calendar", year=year, month=month,
                selected=selected_date, event=event["id"],
            )
        selected_event = next(
            (
                event for event in events
                if str(event["id"]) == str(request.args.get("event", ""))
            ),
            None,
        )
        event_form = selected_event or {
            "id": "", "title": "", "event_date": selected_date,
            "event_time": "", "place": "", "description": "",
            "visibility": "private", "shared_users": [],
        }
        previous_anchor = first_day - timedelta(days=1)
        next_anchor = last_day + timedelta(days=1)
        context.update(
            month_label=f"{MONTH_NAMES_RU[month]} {year}",
            calendar_days=calendar_days,
            selected_date=selected_date,
            selected_date_label=parsed_selected.strftime("%d.%m.%Y"),
            selected_events=selected_events,
            event_form=event_form,
            event_shared_ids={item["id"] for item in event_form["shared_users"]},
            previous_month_url=url_for(
                "notes_page", view="calendar", year=previous_anchor.year,
                month=previous_anchor.month,
            ),
            next_month_url=url_for(
                "notes_page", view="calendar", year=next_anchor.year,
                month=next_anchor.month,
            ),
            today_url=url_for(
                "notes_page", view="calendar", year=today.year,
                month=today.month, selected=today.isoformat(),
            ),
            new_event_url=url_for(
                "notes_page", view="calendar", year=year, month=month,
                selected=selected_date,
            ),
        )
    elif view == "records":
        notes = list_personal_notes(user_id)
        selected_folder = str(request.args.get("folder", "")).strip()
        folder_counts = {}
        for note in notes:
            folder_counts[note["folder"]] = folder_counts.get(note["folder"], 0) + 1
            note["url"] = url_for(
                "notes_page", view="records", folder=selected_folder or None,
                note=note["id"],
            )
        filtered_notes = [
            note for note in notes
            if not selected_folder or note["folder"] == selected_folder
        ]
        selected_note = next(
            (
                note for note in notes
                if str(note["id"]) == str(request.args.get("note", ""))
            ),
            None,
        )
        note_form = selected_note or {
            "id": "", "folder": selected_folder or "Без папки", "title": "",
            "body": "", "visibility": "private", "shared_users": [],
        }
        context.update(
            notes=notes,
            filtered_notes=filtered_notes,
            selected_folder=selected_folder,
            selected_note=selected_note,
            note_form=note_form,
            note_shared_ids={item["id"] for item in note_form["shared_users"]},
            note_folders=[
                {"name": name, "count": count,
                 "url": url_for("notes_page", view="records", folder=name)}
                for name, count in sorted(folder_counts.items())
            ],
        )
    else:
        decks = list_dictionary_decks(user_id)
        requested_deck = str(request.args.get("deck", "")).strip()
        selected_deck = next(
            (deck for deck in decks if str(deck["id"]) == requested_deck),
            decks[0] if decks else None,
        )
        for deck in decks:
            deck["url"] = url_for("notes_page", view="dictionary", deck=deck["id"])
        cards = (
            list_dictionary_cards(user_id, selected_deck["id"])
            if selected_deck else []
        )
        due_cards = (
            list_dictionary_cards(user_id, selected_deck["id"], due_only=True)
            if selected_deck else []
        )
        context.update(
            decks=decks,
            deck_total=len(decks),
            due_total=sum(deck["due_count"] for deck in decks),
            selected_deck=selected_deck,
            cards=cards,
            quiz_card=due_cards[0] if due_cards else None,
            ratings=(("again", "Снова"), ("hard", "Трудно"),
                     ("good", "Хорошо"), ("easy", "Легко")),
        )
    return render_template_string(NOTES_HTML, **context)


@app.route("/bookmarks", methods=["GET", "POST"])
@app.route("/collections", methods=["GET", "POST"])
def bookmarks_page():
    """Показывает рабочие подборки, общий доступ, ссылки и заметки."""
    user = current_user()
    user_id = user["id"]
    favorite_folder = ensure_favorites_folder(user_id)
    selected_folder = str(
        request.args.get("folder", favorite_folder["id"])
    ).strip() or str(favorite_folder["id"])
    sort_mode = str(request.args.get("sort", "newest")).strip().casefold()
    if sort_mode not in COLLECTION_SORTS:
        sort_mode = "newest"
    folders = list_bookmark_folders(user_id)
    folder_by_id = {str(folder["id"]): folder for folder in folders}
    shared_folders = list_shared_collections(user_id)
    shared_by_id = {str(folder["id"]): folder for folder in shared_folders}
    if selected_folder not in {"all", "unfiled", *folder_by_id, *shared_by_id}:
        abort(404)

    if request.method == "POST":
        if not csrf_is_valid():
            abort(400)
        action = str(request.form.get("action", "")).strip()
        try:
            if action == "create_folder":
                created = create_bookmark_folder(user_id, request.form.get("name"))
                message = f"Подборка «{created['name']}» создана"
                selected_folder = str(created["id"])
            elif action == "update_collection":
                current = load_collection(user_id, request.form.get("folder_id"))
                if current is None or not current["can_edit"]:
                    raise ValueError("Подборка не найдена")
                updated = update_collection(
                    user_id,
                    request.form.get("folder_id"),
                    request.form.get("name"),
                    current["description"],
                    current["visibility"],
                    [item["id"] for item in current["shared_users"]],
                )
                message = f"Название изменено на «{updated['name']}»"
                selected_folder = str(updated["id"])
            elif action == "share_collection":
                current = load_collection(user_id, request.form.get("folder_id"))
                if current is None or not current["can_edit"]:
                    raise ValueError("Подборка не найдена")
                update_collection(
                    user_id, current["id"], current["name"],
                    request.form.get("description"),
                    request.form.get("visibility"),
                    request.form.getlist("shared_user_ids"),
                )
                message = "Доступ к подборке обновлён"
                selected_folder = str(current["id"])
            elif action == "delete_folder":
                delete_bookmark_folder(user_id, request.form.get("folder_id"))
                message = "Подборка удалена, её новости перенесены в «Без подборки»"
                selected_folder = str(favorite_folder["id"])
            elif action == "add_external":
                save_external_bookmark(
                    user_id, request.form.get("folder_id"), request.form.get("url"),
                    request.form.get("title"), request.form.get("note"),
                )
                message = "Внешняя ссылка добавлена"
                selected_folder = str(request.form.get("folder_id"))
            elif action == "add_note":
                save_collection_note(
                    user_id, request.form.get("folder_id"),
                    request.form.get("title"), request.form.get("body"),
                    request.form.get("url"), request.form.get("source"),
                    request.form.get("publication_date"),
                    request.form.get("comment"),
                )
                message = "Статья добавлена"
                selected_folder = str(request.form.get("folder_id"))
            elif action == "update_note":
                update_collection_note(
                    user_id, request.form.get("folder_id"),
                    request.form.get("note_id"), request.form.get("title"),
                    request.form.get("body"), request.form.get("url"),
                    request.form.get("source"), request.form.get("publication_date"),
                    request.form.get("comment"),
                )
                message = "Изменения сохранены"
                selected_folder = str(request.form.get("folder_id"))
            elif action == "delete_note":
                delete_collection_note(
                    user_id, request.form.get("folder_id"), request.form.get("note_id"),
                )
                message = "Статья удалена"
                selected_folder = str(request.form.get("folder_id"))
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
                    sort=sort_mode,
                    error=str(operation_error),
                )
            )
        return redirect(url_for(
            "bookmarks_page", folder=selected_folder, sort=sort_mode, message=message
        ))

    search_query = str(request.args.get("q", "")).strip()[:200]
    all_bookmarks = list_bookmarks(user_id)
    selected_folder_data = None
    notes = []
    read_note_ids = set()
    if selected_folder in folder_by_id or selected_folder in shared_by_id:
        selected_folder_data = load_collection(user_id, selected_folder)
        bookmarks = list_collection_bookmarks(user_id, selected_folder)
        notes = list_collection_notes(user_id, selected_folder)
        read_note_ids = list_collection_note_read_ids(user_id, selected_folder)
    else:
        bookmarks = list_bookmarks(user_id, selected_folder)
    bookmarks = [
        item for item in bookmarks
        if _matches_collection_search(
            item,
            search_query,
            ("title", "source", "note", "date", "url", "folder_name"),
        )
    ]
    prepared_notes = []
    for item in notes:
        if not _matches_collection_search(
            item,
            search_query,
            ("title", "source", "body", "comment", "publication_date", "url"),
        ):
            continue
        prepared = _prepare_collection_note(item)
        prepared["is_read"] = int(item["id"]) in read_note_ids
        prepared_notes.append(prepared)
    notes = prepared_notes
    materials = _collection_materials(bookmarks, notes, sort_mode)
    notes = [item for item in materials if item["kind"] == "note"]
    bookmarks = [item for item in materials if item["kind"] == "bookmark"]
    if selected_folder_data:
        selected_title = selected_folder_data["name"]
    elif selected_folder == "unfiled":
        selected_title = "Без папки"
    else:
        selected_title = "Все сохранённые"
    active_users = [
        account for account in list_users()
        if account["is_active"] and account["id"] != user_id
    ]
    return render_template_string(
        BOOKMARKS_HTML,
        current_user=user,
        csrf_token=csrf_token(),
        folders=folders,
        shared_folders=shared_folders,
        bookmarks=bookmarks,
        notes=notes,
        materials=materials,
        selected_folder=selected_folder,
        selected_folder_data=selected_folder_data,
        selected_title=selected_title,
        search_query=search_query,
        sort_mode=sort_mode,
        sort_options=COLLECTION_SORTS,
        total_count=len(all_bookmarks),
        unfiled_count=sum(item["folder_id"] is None for item in all_bookmarks),
        available_users=active_users,
        selected_shared_ids={
            account["id"] for account in (
                selected_folder_data["shared_users"] if selected_folder_data else []
            )
        },
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
    mode="all",
    source_filters=None,
    source_group=GOVERNMENT_GROUP,
):
    user = current_user()
    if user["id"]:
        user_saved_urls = bookmarked_urls(user["id"])
        user_bookmark_count = count_bookmarks(user["id"])
    else:
        user_saved_urls = []
        user_bookmark_count = 0
    status = load_json("parser_status.json", {})
    total, found_count = news_group_counts(source_group)
    counts = news_source_counts(source_group)
    sources = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    requested_sources = (
        list(source_filters)
        if source_filters is not None
        else request.args.getlist("source")
    )
    available_names = set(counts)
    source_filters = []
    for source in requested_sources:
        source = str(source or "").strip()
        if source in available_names and source not in source_filters:
            source_filters.append(source)
    if user["id"]:
        sources = apply_source_order(
            sources,
            load_source_order(user["id"], source_group),
        )
    if source_group == AGENCIES_GROUP:
        yahoo_sources = [
            (
                name,
                count,
                name.split("·", 1)[-1].strip() or name,
            )
            for name, count in sources
            if is_yahoo_source(name)
        ]
        sidebar_sources = [
            (name, count)
            for name, count in sources
            if not is_yahoo_source(name)
        ]
    else:
        yahoo_sources = []
        sidebar_sources = sources
    yahoo_active = any(is_yahoo_source(source) for source in source_filters)
    yahoo_expanded = yahoo_active

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
        group_eyebrow = (
            "РИА Новости · ТАСС · Интерфакс · Yahoo! JAPAN · "
            "Yonhap · Киодо"
        )
        group_home = "/agencies"
        group_found = "/agencies/found"
    elif source_group == NEWSPAPERS_GROUP:
        group_title = "Свежие номера газет"
        group_eyebrow = "Коммерсантъ · Известия · РГ · Ведомости · Красная звезда · КП"
        group_home = "/newspapers"
        group_found = "/newspapers/found"
    else:
        group_title = "Новости госструктур"
        group_eyebrow = "Агрегатор официальных источников"
        group_home = "/"
        group_found = "/found"

    filter_home = group_found if mode == "found" else group_home
    requested_keyword = " ".join(request.args.get("keyword", "").split())
    keyword_filter = (
        requested_keyword[:80]
        if mode == "found"
        else ""
    )
    shared_query_parameters = [
        (key, value)
        for key, values in request.args.lists()
        if key not in {"page", "source", "keyword"}
        for value in values
    ]
    persistent_query_parameters = list(shared_query_parameters)
    if keyword_filter:
        persistent_query_parameters.append(("keyword", keyword_filter))
    clear_query = urlencode(persistent_query_parameters, doseq=True)
    clear_sources_url = filter_home + (f"?{clear_query}" if clear_query else "")
    source_query = urlencode([("source", source) for source in source_filters])
    group_home_url = group_home + (f"?{source_query}" if source_query else "")
    found_query_parameters = [
        *(('source', source) for source in source_filters),
        *((('keyword', keyword_filter),) if keyword_filter else ()),
    ]
    found_query = urlencode(found_query_parameters, doseq=True)
    group_found_url = group_found + (f"?{found_query}" if found_query else "")
    if mode == "found":
        feed_title = (
            f"Совпадения: {keyword_filter}"
            if keyword_filter
            else "Совпадения"
        )
    elif len(source_filters) == 1:
        feed_title = f"Источник: {source_filters[0]}"
    elif source_filters:
        feed_title = f"Выбрано источников: {len(source_filters)}"
    else:
        feed_title = "Последние публикации"

    search_query = request.args.get("q", "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    page_offset = (page - 1) * NEWS_PER_PAGE
    page_news, page_total = list_news_page(
        source_group,
        found_only=mode == "found",
        sources=source_filters,
        search_query=search_query,
        keyword=keyword_filter,
        limit=NEWS_PER_PAGE,
        offset=page_offset,
    )
    page_count = max(1, (page_total + NEWS_PER_PAGE - 1) // NEWS_PER_PAGE)
    if page > page_count:
        page = page_count
        page_offset = (page - 1) * NEWS_PER_PAGE
        page_news, page_total = list_news_page(
            source_group,
            found_only=mode == "found",
            sources=source_filters,
            search_query=search_query,
            keyword=keyword_filter,
            limit=NEWS_PER_PAGE,
            offset=page_offset,
        )
    page_start = page_offset + 1 if page_news else 0
    page_end = page_offset + len(page_news)
    page_label = (
        f"{page_start}–{page_end} из {page_total}"
        if page_total
        else "0 материалов"
    )

    def page_url(number):
        parameters = list(persistent_query_parameters)
        parameters.extend(("source", source) for source in source_filters)
        if number > 1:
            parameters.append(("page", number))
        query_string = urlencode(parameters, doseq=True)
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

    keyword_urls = {}
    for item in page_news:
        for keyword in item.get("keywords", []) or []:
            parameters = list(shared_query_parameters)
            parameters.extend(("source", source) for source in source_filters)
            parameters.append(("keyword", keyword))
            query_string = urlencode(parameters, doseq=True)
            keyword_urls[keyword] = group_found + f"?{query_string}"

    return render_template_string(
        HTML,
        news=page_news,
        total=total,
        found_count=found_count,
        sources=sources,
        sidebar_sources=sidebar_sources,
        yahoo_sources=yahoo_sources,
        yahoo_active=yahoo_active,
        yahoo_expanded=yahoo_expanded,
        keyword_filter=keyword_filter,
        keyword_urls=keyword_urls,
        news_index=[
            {
                "url": item.get("url", ""),
                "source": item.get("source", "Неизвестный источник"),
            }
            for item in page_news
            if item.get("url")
        ],
        source_filters=source_filters,
        feed_title=feed_title,
        mode=mode,
        source_group=source_group,
        group_title=group_title,
        group_eyebrow=group_eyebrow,
        group_home=group_home,
        group_found=group_found,
        group_home_url=group_home_url,
        group_found_url=group_found_url,
        filter_home=filter_home,
        clear_sources_url=clear_sources_url,
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
        current_url=request.full_path.rstrip("?"),
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
        source_group=GOVERNMENT_GROUP,
    )


@app.route("/found")
def found_page():
    return render_news_page(
        mode="found",
        source_group=GOVERNMENT_GROUP,
    )


@app.route("/filter/<path:source>")
def filter_source(source):
    return render_news_page(
        source_filters=[source],
        source_group=get_source_group(source),
    )


@app.route("/agencies")
def agencies_page():
    return render_news_page(
        source_group=AGENCIES_GROUP,
    )


@app.route("/agencies/found")
def agencies_found_page():
    return render_news_page(
        mode="found",
        source_group=AGENCIES_GROUP,
    )


@app.route("/agencies/filter/<path:source>")
def agencies_filter_source(source):
    return render_news_page(
        source_filters=[source],
        source_group=AGENCIES_GROUP,
    )


@app.route("/newspapers")
def newspapers_page():
    return render_news_page(
        source_group=NEWSPAPERS_GROUP,
    )


@app.route("/newspapers/found")
def newspapers_found_page():
    return render_news_page(
        mode="found",
        source_group=NEWSPAPERS_GROUP,
    )


@app.route("/newspapers/filter/<path:source>")
def newspapers_filter_source(source):
    return render_news_page(
        source_filters=[source],
        source_group=NEWSPAPERS_GROUP,
    )


@app.route("/article", methods=["GET", "POST"])
def article_page():
    if request.method == "POST" and not csrf_is_valid():
        abort(400)
    url = request.values.get("url", "").strip()
    item = find_news_by_url(url)
    if item is None:
        # Совместимость со старыми тестовыми/JSON-наборами; рабочая SQLite-база
        # находит публикацию индексом и не загружает десятки тысяч записей.
        item = next(
            (
                news
                for news in load_json("all_news.json", [])
                if news.get("url") == url
            ),
            None,
        )
    if item is None:
        abort(404)
    force_refresh = request.method == "POST"
    cached = load_cached_article(url)
    if (
        is_yahoo_source(item.get("source", ""))
        and yahoo_article_is_polluted(cached)
    ):
        # Версия 2026.08.17.6 могла сохранить вместе со статьёй рейтинг Yahoo.
        # Такой кэш не показываем и заменяем чистым текстом при этом открытии.
        cached = None
    embedded_paragraphs = [
        " ".join(str(paragraph).split())
        for paragraph in item.get("article_paragraphs", [])
        if " ".join(str(paragraph).split())
    ]
    if embedded_paragraphs:
        # Некоторые официальные API/ленты сразу содержат полный текст.
        # Он надёжнее повторного разбора декоративной HTML-страницы.
        article = {
            "title": item.get("title", ""),
            "paragraphs": embedded_paragraphs,
            "error": "",
        }
    elif cached is not None and not force_refresh:
        article = cached
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
            str(item.get("source", "")).startswith("Yahoo! JAPAN ·")
            and item.get("summary")
            and not article.get("paragraphs")
        ):
            # Полный текст Yahoo загружается только при открытии карточки.
            # Если защита сайта его не отдала, сохраняем официальный RSS-анонс.
            article = {
                "title": item.get("title", ""),
                "paragraphs": [item["summary"]],
                "error": "",
            }
        elif (
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
    embedded_text_changed = (
        bool(embedded_paragraphs)
        and cached is not None
        and cached.get("paragraphs") != article.get("paragraphs")
    )
    if cached is None or force_refresh or embedded_text_changed:
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
    """Переключает сердечко и складывает выбранную новость в «Моё избранное»."""
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
        favorite_folder = ensure_favorites_folder(user_id)
        legacy_urls = payload.get("urls")
        if isinstance(legacy_urls, list):
            # Старый интерфейс хранил сердечки только в localStorage.
            # Один ограниченный пакет переносит их в текущий аккаунт.
            for legacy_url in legacy_urls[:500]:
                item = find_news_by_url(str(legacy_url).strip())
                if item is not None:
                    save_bookmark(user_id, item, favorite_folder["id"])
        else:
            item = find_news_by_url(url)
            if item is None:
                return jsonify(error="Новость не найдена"), 404
            save_bookmark(user_id, item, favorite_folder["id"])
    return jsonify(
        urls=bookmarked_urls(user_id),
        count=count_bookmarks(user_id),
    )


@app.get("/api/news-index")
def news_index_api():
    """Подгружает лёгкий индекс непрочитанного после показа самой страницы."""
    source_group = str(request.args.get("group", "")).strip().casefold()
    if source_group not in {
        GOVERNMENT_GROUP,
        AGENCIES_GROUP,
        NEWSPAPERS_GROUP,
    }:
        return jsonify(error="Неизвестный раздел источников"), 400
    return jsonify(items=list_news_index(source_group, UNREAD_INDEX_LIMIT))


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

    counts = news_source_counts(source_group)
    available = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    final_order = [name for name, _ in apply_source_order(available, requested)]
    try:
        saved = save_source_order(user["id"], source_group, final_order)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(sources=saved)


@app.post("/api/collection-order")
def collection_order_api():
    """Сохраняет порядок личных подборок после перетаскивания мышкой."""
    user = current_user()
    if not csrf_is_valid():
        return jsonify(error="Сессия устарела. Обновите страницу."), 400
    payload = request.get_json(silent=True) or {}
    requested = payload.get("folder_ids")
    if not isinstance(requested, list):
        return jsonify(error="Некорректный порядок подборок"), 400
    try:
        folders = save_bookmark_folder_order(user["id"], requested)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(folder_ids=[folder["id"] for folder in folders])


@app.post("/api/collection-note-read")
def collection_note_read_api():
    """Сохраняет личную отметку чтения статьи в доступной подборке."""
    user = current_user()
    if not csrf_is_valid():
        return jsonify(error="Сессия устарела. Обновите страницу."), 400
    payload = request.get_json(silent=True) or {}
    is_read = payload.get("is_read")
    if not isinstance(is_read, bool):
        return jsonify(error="Некорректная отметка чтения"), 400
    try:
        saved = set_collection_note_read(
            user["id"], payload.get("folder_id"), payload.get("note_id"), is_read,
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(is_read=saved)


if __name__ == "__main__":
    host = "127.0.0.1"
    try:
        port = int(environment_value("MONITOR_PORT", "5000"))
    except ValueError:
        port = 5000
    print(f"🌐 http://{host}:{port}")
    if _enabled_setting("FLASK_DEBUG"):
        app.run(debug=True, host=host, port=port)
    else:
        from waitress import serve

        options = {
            "host": host,
            "port": port,
            "threads": 4,
            "ident": "NewsMonitor",
            "expose_tracebacks": False,
            "clear_untrusted_proxy_headers": True,
            "max_request_body_size": 1_000_000,
            "max_request_header_size": 32_768,
            "channel_timeout": 60,
        }
        if _enabled_setting("MONITOR_TRUST_PROXY"):
            options.update(
                trusted_proxy="127.0.0.1",
                trusted_proxy_count=1,
                trusted_proxy_headers={
                    "x-forwarded-for",
                    "x-forwarded-host",
                    "x-forwarded-port",
                    "x-forwarded-proto",
                },
            )
        serve(app, **options)
