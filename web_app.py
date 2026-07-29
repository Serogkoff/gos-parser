import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template_string, request
from utils.article_reader import extract_article
from utils.keywords import (
    add_keyword,
    load_keywords,
    rebuild_found_news,
    remove_keyword,
)
from utils.news import deduplicate_news, sort_news_by_publication


app = Flask(__name__)
PROJECT_DIR = Path(__file__).resolve().parent


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Монитор — новости ведомств</title>
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
            display:flex;align-items:center;justify-content:space-between
        }
        .brand{font-size:30px;font-weight:780;letter-spacing:-.05em}
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
        .health{
            min-height:46px;display:flex;align-items:center;gap:12px;padding:0 18px;
            color:var(--green);border:1px solid rgba(62,118,85,.48);
            border-radius:6px;background:rgba(255,252,246,.55);font-size:15px;font-weight:550
        }
        .health.warning{color:#9b691e;border-color:rgba(227,153,42,.55)}
        .health-dot{width:10px;height:10px;border-radius:50%;background:currentColor;box-shadow:0 0 0 5px rgba(62,118,85,.09)}
        .intro{padding-top:38px;border-bottom:1px solid var(--line)}
        .eyebrow{margin:0 0 10px;color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
        h1{margin:0;font-size:clamp(38px,4vw,58px);line-height:1;letter-spacing:-.055em;font-weight:720}
        .tabs{display:flex;gap:28px;margin-top:28px}
        .tab{position:relative;padding:0 2px 16px;color:var(--muted);font-size:17px;font-weight:610}
        .tab span{margin-left:6px;font-variant-numeric:tabular-nums}
        .tab:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:3px;background:var(--coral);transform:scaleX(0);transition:transform .18s}
        .tab.active{color:var(--ink)}.tab.active:after{transform:scaleX(1)}
        .toolbar{display:grid;grid-template-columns:minmax(300px,1.6fr) minmax(210px,.8fr) auto auto auto;gap:14px;padding:22px 0}
        .search,.source-select,.tool-button{
            height:52px;border:1px solid #c9c1b5;border-radius:6px;
            background:rgba(255,252,246,.58)
        }
        .search,.source-select{display:flex;align-items:center;gap:12px;padding:0 16px}
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
        .source-list{padding-top:10px}
        .source-row{
            width:100%;min-height:40px;padding:0 18px;display:grid;grid-template-columns:20px minmax(0,1fr) auto auto;
            align-items:center;gap:9px;border:0;color:#4f4a43;background:transparent;text-align:left;font-size:13px
        }
        .source-row:hover{background:#fff8f2}
        .check{width:16px;height:16px;display:grid;place-items:center;color:#fff;border:1px solid #bdb5a9;border-radius:3px;font-size:11px}
        .source-row.active .check{border-color:var(--coral);background:var(--coral)}
        .source-row b{min-width:28px;padding:3px 5px;color:#827b71;border:1px solid var(--line);border-radius:5px;background:#f8f4ed;text-align:center;font-size:10px;font-weight:500}
        .unread-count{min-width:28px;color:var(--green);text-align:right;font-size:11px;font-weight:700}
        .unread-count:empty{display:none}
        .unread-label{margin-left:auto;padding:3px 6px;color:var(--green);border:1px solid rgba(62,118,85,.35);border-radius:4px;background:rgba(62,118,85,.08);font-size:10px;text-transform:uppercase;letter-spacing:.04em}
        .coverage{padding-top:18px}.coverage>h2,.coverage dl{padding:0 20px}
        .coverage dl{margin:14px 0 16px}.coverage dl div{min-height:31px;display:flex;align-items:center;justify-content:space-between}
        .coverage dt,.coverage dd{margin:0;color:#686158;font-size:12px}.coverage dt{display:flex;align-items:center;gap:8px}.coverage dd{color:var(--ink)}
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
            .toolbar{grid-template-columns:1fr 1fr}.content-grid{grid-template-columns:1fr}
            .sidebar{grid-template-columns:1fr 1fr;grid-row:1}
        }
        @media(max-width:680px){
            .shell{width:min(100% - 28px,1500px)}.topbar{min-height:72px}
            .topbar{align-items:flex-start;padding:17px 0}.topbar-tools{align-items:flex-end;flex-direction:column-reverse;gap:10px}.clock-copy{display:none}
            .health{min-height:38px;padding:0 12px;font-size:11px}
            .toolbar,.sidebar{grid-template-columns:1fr}.news-card{padding:20px 48px 20px 18px}
            .news-card.match{padding-left:13px}.feed-heading{padding:0 18px}.news-card h3{font-size:21px}
            .meta{align-items:flex-start;flex-direction:column;gap:4px}.meta i{display:none}
        }
    </style>
</head>
<body>
<main class="shell">
    <header class="topbar">
        <a class="brand" href="/">Монитор</a>
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
            <div class="health {{'warning' if health_ok < health_total else ''}}">
                <span class="health-dot"></span>
                {{health_ok}} из {{health_total}} источников работают
            </div>
        </div>
    </header>

    <section class="intro">
        <p class="eyebrow">Агрегатор официальных источников</p>
        <h1>Новости ведомств</h1>
        <nav class="tabs">
            <a class="tab {{'active' if mode == 'all' else ''}}" href="/">Все <span>{{total}}</span></a>
            <a class="tab {{'active' if mode == 'found' else ''}}" href="/found">Совпадения <span>{{found_count}}</span></a>
        </nav>
    </section>

    <section class="toolbar">
        <label class="search">
            <span class="search-icon">⌕</span>
            <input id="news-search" placeholder="Поиск по заголовкам" autocomplete="off">
        </label>
        <label class="source-select">
            <span>▱</span>
            <select onchange="goToSource(this.value)">
                <option value="">Все источники</option>
                {% for src, count in sources %}
                <option value="{{src}}" {{'selected' if src == source_filter else ''}}>{{src}} — {{count}}</option>
                {% endfor %}
            </select>
        </label>
        <button class="tool-button" id="toggle-sidebar" type="button">☷ Фильтры</button>
        <button class="tool-button" id="keywords-open" type="button">✣ Ключевые слова</button>
        <button class="tool-button" id="saved-only" type="button">
            ♡ Сохранённые <span class="saved-count hidden" id="saved-count">0</span>
        </button>
    </section>

    <div class="content-grid">
        <section class="feed">
            <header class="feed-heading">
                <h2>{{'Совпадения' if mode == 'found' else ('Источник: ' + source_filter if source_filter else 'Последние публикации')}}</h2>
                <span id="visible-count">{{news|length}} материалов</span>
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
                        <time>
                            {% if item.date %}{{item.date}}
                            {% elif item.parsed_date %}Получено {{item.parsed_date}}
                            {% endif %}
                        </time>
                        <span class="unread-label hidden">Новая</span>
                    </div>
                    {% if item.source == 'МИД РФ' %}
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
        </section>

        <aside class="sidebar" id="sidebar">
            <section class="panel">
                <header class="panel-title">
                    <h2>Источники</h2>
                    <div class="panel-title-actions">
                        <button class="mark-all-read" id="mark-all-read" type="button">Прочитать всё</button>
                        <button class="collapse-button" id="collapse-sources" type="button" aria-label="Свернуть список">−</button>
                    </div>
                </header>
                <div class="source-list" id="source-list">
                    <a class="source-row {{'active' if not source_filter else ''}}" href="/">
                        <span class="check">{{'✓' if not source_filter else ''}}</span>
                        <span>Все источники</span>
                        <b>{{total}}</b>
                        <span class="unread-count" data-unread-source="__all__"></span>
                    </a>
                    {% for src, count in sources %}
                    <a class="source-row {{'active' if src == source_filter else ''}}" href="/filter/{{src|urlencode}}">
                        <span class="check">{{'✓' if src == source_filter else ''}}</span>
                        <span>{{src}}</span>
                        <b>{{count}}</b>
                        <span class="unread-count" data-unread-source="{{src}}"></span>
                    </a>
                    {% endfor %}
                </div>
            </section>

            <section class="panel coverage">
                <h2>Сводка покрытия</h2>
                <dl>
                    <div><dt>Источников всего</dt><dd>{{health_total}}</dd></div>
                    <div><dt><span class="dot green"></span>Работают</dt><dd class="green-text">{{health_ok}}</dd></div>
                    <div><dt><span class="dot amber"></span>Пустая выдача</dt><dd>{{health_empty}}</dd></div>
                    <div><dt><span class="dot coral"></span>Ошибки парсинга</dt><dd>{{health_errors}}</dd></div>
                </dl>
                <footer><span>Обновлено {{status_time or '—'}}</span><span>↻</span></footer>
            </section>
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
    const savedButton = document.getElementById('saved-only');
    const savedCount = document.getElementById('saved-count');
    const newsIndex = {{news_index|tojson}};
    let savedOnly = false;
    let saved = new Set(JSON.parse(localStorage.getItem('monitor-saved') || '[]'));
    const unreadStorageKey = 'monitor-unread-v1';
    let unreadState;

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
        newsIndex.forEach(item => {
            if(unread.has(item.url)){
                counts[item.source] = (counts[item.source] || 0) + 1;
            }
        });
        document.querySelectorAll('[data-unread-source]').forEach(badge => {
            const source = badge.dataset.unreadSource;
            const count = source === '__all__' ? unread.size : (counts[source] || 0);
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
    function applyFilters(){
        const query = search.value.trim().toLowerCase();
        let count = 0;
        cards.forEach(card => {
            const matchesText = !query || card.dataset.search.includes(query);
            const matchesSaved = !savedOnly || saved.has(card.dataset.id);
            const visible = matchesText && matchesSaved;
            card.classList.toggle('hidden', !visible);
            if(visible) count++;
        });
        visibleCount.textContent = count + ' материалов';
        emptyState.classList.toggle('hidden', count !== 0);
    }
    document.querySelectorAll('[data-save]').forEach(button => {
        button.addEventListener('click', () => {
            const id = button.dataset.save;
            saved.has(id) ? saved.delete(id) : saved.add(id);
            localStorage.setItem('monitor-saved', JSON.stringify([...saved]));
            refreshSavedIcons(); applyFilters();
        });
    });
    document.querySelectorAll('[data-read-url]').forEach(link => {
        link.addEventListener('click', () => markRead(link.dataset.readUrl));
    });
    document.getElementById('mark-all-read').addEventListener('click', () => {
        unread.clear();
        saveUnread();
        refreshUnread();
    });
    search.addEventListener('input', applyFilters);
    savedButton.addEventListener('click', () => {
        savedOnly = !savedOnly;
        savedButton.classList.toggle('active', savedOnly);
        applyFilters();
    });
    document.getElementById('toggle-sidebar').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('hidden');
    });
    document.getElementById('collapse-sources').addEventListener('click', event => {
        const list = document.getElementById('source-list');
        list.classList.toggle('hidden');
        event.currentTarget.textContent = list.classList.contains('hidden') ? '+' : '−';
    });
    function goToSource(source){
        window.location.href = source ? '/filter/' + encodeURIComponent(source) : '/';
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
            method, headers:{'Content-Type':'application/json'}, body:JSON.stringify({keyword})
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
        .original{display:inline-flex;margin-top:26px;padding:12px 16px;border:1px solid var(--coral);border-radius:6px;color:var(--coral);text-decoration:none;font:600 14px Inter,Arial,sans-serif}
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
        <a class="original" href="{{item.url}}" target="_blank" rel="noopener noreferrer">Открыть оригинал ↗</a>
    </article>
</main></body></html>
"""


def load_json(filename, default):
    path = PROJECT_DIR / filename
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if filename in {"all_news.json", "found_news.json"} and isinstance(data, list):
            return deduplicate_news(data)
        return data
    except (OSError, json.JSONDecodeError):
        return default


def render_news_page(news, mode="all", source_filter=""):
    all_news = load_json("all_news.json", [])
    found_news = load_json("found_news.json", [])
    status = load_json("parser_status.json", {})

    counts = Counter(item.get("source", "Неизвестный источник") for item in all_news)
    sources = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    summary = status.get("summary", {})
    total_sources = summary.get("total_sources", len(sources))
    ok_sources = summary.get("ok", total_sources)

    return render_template_string(
        HTML,
        news=sort_news_by_publication(news),
        total=len(all_news),
        found_count=len(found_news),
        sources=sources,
        news_index=[
            {
                "url": item.get("url", ""),
                "source": item.get("source", "Неизвестный источник"),
            }
            for item in all_news
            if item.get("url")
        ],
        source_filter=source_filter,
        mode=mode,
        health_total=total_sources,
        health_ok=ok_sources,
        health_empty=summary.get("empty", 0),
        health_errors=summary.get("errors", 0),
        status_time=status.get("generated_at", ""),
    )


@app.template_filter("urlencode")
def urlencode_filter(value):
    return quote(str(value), safe="")


@app.route("/")
def index():
    return render_news_page(load_json("all_news.json", []))


@app.route("/found")
def found_page():
    return render_news_page(load_json("found_news.json", []), mode="found")


@app.route("/filter/<path:source>")
def filter_source(source):
    all_news = load_json("all_news.json", [])
    news = [item for item in all_news if item.get("source") == source]
    return render_news_page(news, source_filter=source)


@app.route("/article")
def article_page():
    url = request.args.get("url", "").strip()
    item = next(
        (news for news in load_json("all_news.json", []) if news.get("url") == url),
        None,
    )
    if item is None:
        abort(404)
    article = extract_article(url, item.get("title", ""))
    back_url = request.referrer if request.referrer and request.host in request.referrer else "/"
    return render_template_string(
        ARTICLE_HTML, article=article, item=item, back_url=back_url
    )


@app.route("/api/keywords", methods=["GET", "POST", "DELETE"])
def keywords_api():
    if request.method == "GET":
        return jsonify(keywords=load_keywords())

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


if __name__ == "__main__":
    print("🌐 http://127.0.0.1:5000")
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug, port=5000)
