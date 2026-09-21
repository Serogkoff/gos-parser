(function(){
'use strict';

let clockTimer = null;
let navigationRequest = null;
let pageGeneration = 0;
let pendingSearchTimer = null;
const preparedFeedEmblems = new Map();

function prepareFeedEmblem(source){
    if(!source) return Promise.resolve();
    const normalizedSource = new URL(source, window.location.origin).href;
    if(preparedFeedEmblems.has(normalizedSource)){
        return preparedFeedEmblems.get(normalizedSource);
    }

    const request = new Promise(resolve => {
        const image = new Image();
        let finished = false;
        const finish = async () => {
            if(finished) return;
            finished = true;
            image.onload = null;
            image.onerror = null;
            if(image.naturalWidth && typeof image.decode === 'function'){
                try{ await image.decode(); }catch(error){}
            }
            resolve();
        };
        image.onload = finish;
        image.onerror = finish;
        image.decoding = 'sync';
        image.src = normalizedSource;
        if(image.complete) finish();
    });
    preparedFeedEmblems.set(normalizedSource, request);
    return request;
}

async function prepareVisibleFeedEmblems(shell){
    const limit = window.matchMedia('(max-width:920px)').matches ? 6 : 10;
    const sources = [...new Set(
        [...shell.querySelectorAll('.source-emblem-main')]
            .slice(0, limit)
            .map(image => image.getAttribute('src'))
            .filter(Boolean)
    )];
    await Promise.all(sources.map(prepareFeedEmblem));
}

function initializeNewsPage(){
const generation = ++pageGeneration;
if(pendingSearchTimer) window.clearTimeout(pendingSearchTimer);

const pageConfigElement = document.getElementById('news-page-config');
const pageConfig = JSON.parse(pageConfigElement.textContent);
const csrfToken = pageConfig.csrfToken;
const cards = [...document.querySelectorAll('.news-card')];
    const search = document.getElementById('news-search');
    const savedCount = document.getElementById('saved-count');
    const brandHome = document.getElementById('brand-home');
    const sourceFilterHome = pageConfig.filterHome;
    const keywordFilterHome = pageConfig.keywordFilterHome;
    const selectedKeyword = pageConfig.selectedKeyword;
    const selectedSources = new Set(pageConfig.sourceFilters);
    const currentSourceGroup = pageConfig.sourceGroup;
    const currentMode = pageConfig.mode;
    let saved = new Set(pageConfig.savedUrls);
    const legacySavedStorageKey = 'monitor-saved';
    const legacyUnreadStorageKey = 'monitor-unread-v1';
    if(brandHome.dataset.feedBrandReady !== 'true'){
    brandHome.dataset.feedBrandReady = 'true';
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
                navigateToFeed(brandHome.href);
            }
            brandClicks = 0;
        }, 650);
    });
    }

    let unread = new Set(pageConfig.unreadUrls);
    let unreadCounts = pageConfig.unreadCounts;
    let groupUnreadCount = pageConfig.unreadTotal;
    let yahooUnreadCount = pageConfig.yahooUnreadCount;
    const mutedSources = new Set(pageConfig.mutedSources);

    function replaceUnread(items){
        unread = new Set();
        unreadCounts = {};
        groupUnreadCount = 0;
        yahooUnreadCount = 0;
        items.forEach(item => {
            if(!item || !item.url || unread.has(item.url)) return;
            unread.add(item.url);
            groupUnreadCount++;
            unreadCounts[item.source] = (unreadCounts[item.source] || 0) + 1;
            if(item.source.startsWith('Yahoo! JAPAN')) yahooUnreadCount++;
        });
    }

    async function initializeUnread(){
        let legacyUnread = null;
        try{
            const legacyState = JSON.parse(
                localStorage.getItem(legacyUnreadStorageKey) || 'null'
            );
            if(legacyState && Array.isArray(legacyState.unread)){
                legacyUnread = legacyState.unread;
            }
        }catch(error){
            legacyUnread = null;
        }

        let migrated = false;
        if(legacyUnread !== null){
            try{
                const migration = await fetch('/api/news-read/migrate', {
                    method:'POST',
                    headers:{
                        'Content-Type':'application/json',
                        'X-CSRF-Token': csrfToken
                    },
                    credentials:'same-origin',
                    body:JSON.stringify({unread_urls:legacyUnread})
                });
                if(migration.ok){
                    localStorage.removeItem(legacyUnreadStorageKey);
                    migrated = true;
                }
            }catch(error){
                // Старые отметки останутся в браузере до успешного переноса.
            }
        }
        if(migrated){
            try{
                const response = await fetch(
                    '/api/news-index?group=' + encodeURIComponent(currentSourceGroup)
                    + '&mode=' + encodeURIComponent(currentMode),
                    {credentials:'same-origin'}
                );
                if(response.ok){
                    const data = await response.json();
                    if(Array.isArray(data.items)) replaceUnread(data.items);
                }
            }catch(error){
                // Серверные отметки уже показаны; перенос обновится при следующем входе.
            }
        }
        refreshUnread();
    }

    function refreshUnread(){
        if(generation !== pageGeneration) return;
        document.querySelectorAll('[data-unread-source]').forEach(badge => {
            const source = badge.dataset.unreadSource;
            const count = source === '__all__'
                ? groupUnreadCount
                : (source === '__yahoo__' ? yahooUnreadCount : (unreadCounts[source] || 0));
            badge.textContent = count ? '+' + count : '';
        });
        cards.forEach(card => {
            const label = card.querySelector('.unread-label');
            if(label) label.classList.toggle('hidden', !unread.has(card.dataset.id));
        });
    }

    function adjustUnreadCount(url, change){
        const card = cards.find(item => item.dataset.id === url);
        if(!card) return;
        const source = card.dataset.source;
        unreadCounts[source] = Math.max(0, (unreadCounts[source] || 0) + change);
        groupUnreadCount = Math.max(0, groupUnreadCount + change);
        if(source.startsWith('Yahoo! JAPAN')){
            yahooUnreadCount = Math.max(0, yahooUnreadCount + change);
        }
    }

    async function markRead(url){
        if(!unread.delete(url)) return;
        adjustUnreadCount(url, -1);
        refreshUnread();
        try{
            const response = await fetch('/api/news-read', {
                method:'POST',
                headers:{
                    'Content-Type':'application/json',
                    'X-CSRF-Token': csrfToken
                },
                credentials:'same-origin',
                keepalive:true,
                body:JSON.stringify({url:url})
            });
            if(!response.ok) throw new Error('Не удалось сохранить отметку');
        }catch(error){
            unread.add(url);
            adjustUnreadCount(url, 1);
            refreshUnread();
        }
    }

    function refreshSavedIcons(){
        if(generation !== pageGeneration) return;
        document.querySelectorAll('[data-save]').forEach(button => {
            const active = saved.has(button.dataset.save);
            button.classList.toggle('active', active);
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
                    'X-CSRF-Token': csrfToken
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
                        'X-CSRF-Token': csrfToken
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
    document.querySelectorAll('[data-mark-read]').forEach(button => {
        button.addEventListener('click', () => markRead(button.dataset.markRead));
    });
    async function markAllRead(){
        const previousUnread = new Set(unread);
        const previousUnreadCounts = {...unreadCounts};
        const previousGroupUnreadCount = groupUnreadCount;
        const previousYahooUnreadCount = yahooUnreadCount;
        unread.clear();
        unreadCounts = {};
        groupUnreadCount = 0;
        yahooUnreadCount = 0;
        refreshUnread();
        try{
            const response = await fetch('/api/news-read', {
                method:'POST',
                headers:{
                    'Content-Type':'application/json',
                    'X-CSRF-Token': csrfToken
                },
                credentials:'same-origin',
                body:JSON.stringify({source_group:currentSourceGroup, all:true})
            });
            if(!response.ok) throw new Error('Не удалось сохранить отметки');
        }catch(error){
            unread = previousUnread;
            unreadCounts = previousUnreadCounts;
            groupUnreadCount = previousGroupUnreadCount;
            yahooUnreadCount = previousYahooUnreadCount;
            refreshUnread();
        }
    }
    document.querySelectorAll('[data-mark-all-read]').forEach(button => button.addEventListener('click', markAllRead));
    initializeUnread();
    const searchForm = search.closest('form');
    searchForm.addEventListener('submit', event => {
        event.preventDefault();
        const target = new URL(searchForm.action, window.location.origin);
        new FormData(searchForm).forEach((value, key) => {
            if(value !== '') target.searchParams.append(key, value);
        });
        navigateToFeed(target.href);
    });
    search.addEventListener('input', () => {
        window.clearTimeout(pendingSearchTimer);
        pendingSearchTimer = window.setTimeout(() => searchForm.requestSubmit(), 450);
    });
    const clearDates = searchForm.querySelector('[data-clear-dates]');
    clearDates.addEventListener('click', () => {
        searchForm.querySelectorAll('input[type="date"]').forEach(input => {
            input.value = '';
        });
        searchForm.requestSubmit();
    });
    const sourceList = document.getElementById('source-list');
    const yahooSourceToggle = document.getElementById('yahoo-source-toggle');
    if(yahooSourceToggle){
        yahooSourceToggle.addEventListener('click', () => {
            if(yahooSourceToggle.closest('.yahoo-source-header').classList.contains('source-muted')) return;
            const yahooSources = [...sourceList.querySelectorAll('.yahoo-source-row [data-source-filter]')]
                .filter(button => !button.closest('[data-source-row]').classList.contains('source-muted'))
                .map(button => button.dataset.sourceFilter);
            const allSelected = yahooSources.length > 0 && yahooSources.every(source => selectedSources.has(source));
            yahooSources.forEach(source => {
                allSelected ? selectedSources.delete(source) : selectedSources.add(source);
            });
            navigateToFeed(filteredSourceUrl([...selectedSources]));
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
        navigateToFeed(filteredSourceUrl([]));
    });
    document.querySelectorAll('[data-source-filter]').forEach(button => {
        button.addEventListener('click', () => {
            if(button.closest('[data-source-row]')?.classList.contains('source-muted')) return;
            const source = button.dataset.sourceFilter;
            selectedSources.has(source)
                ? selectedSources.delete(source)
                : selectedSources.add(source);
            navigateToFeed(filteredSourceUrl([...selectedSources]));
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
                'X-CSRF-Token': csrfToken
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
    async function saveSourceMutes(){
        const response = await fetch('/api/source-mutes', {
            method:'POST',
            headers:{
                'Content-Type':'application/json',
                'X-CSRF-Token': csrfToken
            },
            body:JSON.stringify({mode:currentMode,sources:[...mutedSources]})
        });
        if(!response.ok){
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || 'Не удалось сохранить скрытые источники');
        }
    }
    const sourceOrderToggle = document.getElementById('source-order-toggle');
    const mobileSourceOpen = document.querySelector('.mobile-source-open');
    const mobileSourceClose = document.querySelector('.mobile-source-close');
    const mobileSourceBackdrop = document.querySelector('.mobile-source-backdrop');
    let draggedSourceRow = null;
    let sourceOrderChanged = false;
    let sourceMutesChanged = false;
    const yahooMuteToggle = document.querySelector('[data-source-mute-yahoo]');
    function setSourceMuted(row, button, muted){
        const source = button.dataset.sourceMute;
        muted ? mutedSources.add(source) : mutedSources.delete(source);
        row.classList.toggle('source-muted', muted);
        row.querySelector('[data-source-filter]').setAttribute('aria-disabled', String(muted));
        button.setAttribute('aria-pressed', String(muted));
        const label = muted ? 'Показывать источник' : 'Скрыть источник';
        button.setAttribute('aria-label', label);
        button.setAttribute('title', label);
    }
    function refreshYahooMuteState(){
        if(!yahooMuteToggle) return;
        const names = [...sourceList.querySelectorAll('.yahoo-source-row [data-source-mute]')]
            .map(button => button.dataset.sourceMute);
        const allMuted = names.length > 0 && names.every(source => mutedSources.has(source));
        const someMuted = names.some(source => mutedSources.has(source));
        yahooMuteToggle.closest('.yahoo-source-header').classList.toggle('source-muted', allMuted);
        yahooMuteToggle.setAttribute('aria-pressed', allMuted ? 'true' : (someMuted ? 'mixed' : 'false'));
        const label = allMuted
            ? 'Показывать все источники Yahoo! JAPAN'
            : 'Скрыть все источники Yahoo! JAPAN';
        yahooMuteToggle.setAttribute('aria-label', label);
        yahooMuteToggle.setAttribute('title', label);
    }
    document.querySelectorAll('[data-source-mute]').forEach(button => {
        button.addEventListener('click', event => {
            event.stopPropagation();
            const row = button.closest('[data-source-row]');
            setSourceMuted(row, button, !mutedSources.has(button.dataset.sourceMute));
            refreshYahooMuteState();
            sourceMutesChanged = true;
        });
    });
    if(yahooMuteToggle){
        yahooMuteToggle.addEventListener('click', event => {
            event.stopPropagation();
            const buttons = [...sourceList.querySelectorAll('.yahoo-source-row [data-source-mute]')];
            const allMuted = buttons.length > 0 && buttons.every(
                button => mutedSources.has(button.dataset.sourceMute)
            );
            buttons.forEach(button => setSourceMuted(
                button.closest('[data-source-row]'), button, !allMuted
            ));
            refreshYahooMuteState();
            sourceMutesChanged = true;
        });
    }
    function setMobileSourcesOpen(open){
        document.getElementById('sidebar').classList.toggle('mobile-open', open);
        mobileSourceBackdrop.classList.toggle('mobile-open', open);
        mobileSourceOpen.setAttribute('aria-expanded', String(open));
        document.body.style.overflow = open ? 'hidden' : '';
    }
    async function closeMobileSources(){
        if(sourceMutesChanged){
            mobileSourceClose.disabled = true;
            try{
                await saveSourceMutes();
                navigateToFeed(window.location.href, {historyMode:'replace'});
                return;
            }catch(error){
                window.alert(error.message);
            }finally{
                mobileSourceClose.disabled = false;
            }
        }
        setMobileSourcesOpen(false);
    }
    mobileSourceOpen.addEventListener('click', () => {
        sourceMutesChanged = false;
        setMobileSourcesOpen(true);
    });
    mobileSourceClose.addEventListener('click', closeMobileSources);
    mobileSourceBackdrop.addEventListener('click', closeMobileSources);
    function setSourceOrderEditing(editing){
        sourceList.classList.toggle('order-editing', editing);
        if(editing && yahooSourceToggle){
            sourceList.classList.add('yahoo-expanded');
            yahooSourceToggle.setAttribute('aria-expanded', 'true');
        }
        sourceOrderToggle.setAttribute('aria-pressed', String(editing));
        const actionLabel = editing ? 'Сохранить порядок источников' : 'Изменить порядок источников';
        sourceOrderToggle.setAttribute('aria-label', actionLabel);
        sourceOrderToggle.setAttribute('title', actionLabel);
        sourceOrderToggle.querySelector('.visually-hidden').textContent = actionLabel;
        orderedSourceRows().forEach(row => row.draggable = editing);
    }
    sourceOrderToggle.addEventListener('click', async () => {
        const editing = sourceList.classList.contains('order-editing');
        if(!editing){
            sourceOrderChanged = false;
            sourceMutesChanged = false;
            setSourceOrderEditing(true);
            return;
        }
        sourceOrderToggle.disabled = true;
        try{
            if(sourceOrderChanged) await saveSourceOrder();
            if(sourceMutesChanged){
                await saveSourceMutes();
                navigateToFeed(window.location.href, {historyMode:'replace'});
                return;
            }
            setSourceOrderEditing(false);
        }catch(error){
            window.alert(error.message);
            navigateToFeed(window.location.href, {historyMode:'replace'});
        }finally{
            sourceOrderToggle.disabled = false;
        }
    });
    sourceList.addEventListener('dragstart', event => {
        if(event.target.closest('[data-source-mute]')){
            event.preventDefault();
            return;
        }
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
    const clockFormatters = new Map();
    document.querySelectorAll('[data-clock]').forEach(clock => {
        clockFormatters.set(clock.dataset.clock, {
            time:new Intl.DateTimeFormat('ru-RU', {
                timeZone:clock.dataset.clock, hour:'2-digit', minute:'2-digit',
                second:'2-digit', hourCycle:'h23'
            }),
            date:new Intl.DateTimeFormat('ru-RU', {
                timeZone:clock.dataset.clock, day:'2-digit', month:'2-digit', year:'numeric'
            })
        });
    });
    function updateClocks(){
        document.querySelectorAll('[data-clock]').forEach(clock => {
            const formatters = clockFormatters.get(clock.dataset.clock);
            const now = new Date();
            const zonedParts = Object.fromEntries(
                formatters.time.formatToParts(now).map(part => [part.type, part.value])
            );
            const hour = Number(zonedParts.hour), minute = Number(zonedParts.minute), second = Number(zonedParts.second);
            clock.style.setProperty('--hour', (hour % 12 * 30 + minute * .5) + 'deg');
            clock.style.setProperty('--minute', (minute * 6 + second * .1) + 'deg');
            clock.style.setProperty('--second', (second * 6) + 'deg');
            clock.querySelector('.clock-time').textContent = `${zonedParts.hour}:${zonedParts.minute}`;
            clock.querySelector('.clock-date').textContent = formatters.date.format(now);
        });
    }
    updateClocks();
    if(clockTimer) window.clearInterval(clockTimer);
    clockTimer = window.setInterval(updateClocks, 30000);

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
        reset.addEventListener('click', () => navigateToFeed(keywordUrl('')));
        const chips = words.map(word => {
            const chip = document.createElement('span'); chip.className = 'keyword-chip';
            const active = word.localeCompare(selectedKeyword, undefined, {sensitivity:'accent'}) === 0;
            if(active) chip.classList.add('active');
            const label = document.createElement('button');
            label.type = 'button'; label.className = 'keyword-filter'; label.textContent = word;
            label.setAttribute('aria-pressed', String(active));
            label.addEventListener('click', () => {
                navigateToFeed(keywordUrl(active ? '' : word));
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
                'X-CSRF-Token': csrfToken
            },
            body:JSON.stringify({keyword})
        });
        const data = await response.json();
        if(!response.ok){ keywordMessage.textContent = data.error || 'Не удалось сохранить'; return; }
        if(method === 'DELETE' && keyword.localeCompare(selectedKeyword, undefined, {sensitivity:'accent'}) === 0){
            navigateToFeed(keywordUrl(''));
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
    migrateLegacySaved();
}

function isFeedUrl(value){
    const url = new URL(value, window.location.origin);
    if(url.origin !== window.location.origin) return false;
    return /^(?:\/(?:all|found|agencies|newspapers)(?:\/found)?|\/)$/.test(url.pathname)
        || /^\/(?:all\/|agencies\/|newspapers\/)?filter\//.test(url.pathname);
}

async function navigateToFeed(value, options = {}){
    const target = new URL(value, window.location.origin);
    if(!isFeedUrl(target.href)){
        window.location.assign(target.href);
        return;
    }

    if(navigationRequest) navigationRequest.abort();
    const requestController = new AbortController();
    navigationRequest = requestController;
    const currentLayout = document.querySelector('.app-layout');
    currentLayout?.setAttribute('aria-busy', 'true');

    try{
        const response = await fetch(target.href, {
            credentials:'same-origin',
            headers:{'X-Requested-With':'feed-navigation'},
            signal:requestController.signal
        });
        if(!response.ok) throw new Error('Не удалось загрузить раздел');

        const nextDocument = new DOMParser().parseFromString(
            await response.text(),
            'text/html'
        );
        const nextLayout = nextDocument.querySelector('.app-layout');
        const currentShell = currentLayout?.querySelector('.shell');
        const nextShell = nextLayout?.querySelector('.shell');
        const currentMobileNav = currentLayout?.querySelector('.mobile-bottom-nav');
        const nextMobileNav = nextLayout?.querySelector('.mobile-bottom-nav');
        const nextModal = nextDocument.getElementById('keyword-modal');
        const nextConfig = nextDocument.getElementById('news-page-config');
        const currentModal = document.getElementById('keyword-modal');
        const currentConfig = document.getElementById('news-page-config');
        if(
            !nextLayout || !currentLayout || !currentShell || !nextShell ||
            !currentMobileNav || !nextMobileNav || !nextModal || !nextConfig ||
            !currentModal || !currentConfig
        ){
            throw new Error('Получена несовместимая страница');
        }

        await prepareVisibleFeedEmblems(nextShell);
        if(requestController.signal.aborted){
            throw new DOMException('Навигация отменена', 'AbortError');
        }

        const currentModeLinks = currentLayout.querySelectorAll('.rail-nav .rail-link:nth-child(-n+2)');
        const nextModeLinks = nextLayout.querySelectorAll('.rail-nav .rail-link:nth-child(-n+2)');
        currentModeLinks.forEach((link, index) => {
            const nextLink = nextModeLinks[index];
            if(!nextLink) return;
            link.className = nextLink.className;
            link.setAttribute('href', nextLink.getAttribute('href'));
        });
        currentShell.replaceWith(nextShell);
        currentMobileNav.replaceWith(nextMobileNav);
        currentModal.replaceWith(nextModal);
        currentConfig.textContent = nextConfig.textContent;
        document.body.className = nextDocument.body.className;
        document.title = nextDocument.title;

        if(options.historyMode === 'replace'){
            window.history.replaceState({feedNavigation:true}, '', target.href);
        }else if(options.historyMode !== 'none'){
            window.history.pushState({feedNavigation:true}, '', target.href);
        }
        initializeNewsPage();
    }catch(error){
        if(error.name === 'AbortError') return;
        window.location.assign(target.href);
    }finally{
        if(navigationRequest === requestController){
            navigationRequest = null;
            document.querySelector('.app-layout')?.removeAttribute('aria-busy');
        }
    }
}

document.addEventListener('click', event => {
    if(
        event.defaultPrevented || event.button !== 0 ||
        event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
    ) return;
    const link = event.target.closest('a[href]');
    if(!link || link.target || link.hasAttribute('download') || !isFeedUrl(link.href)) return;
    event.preventDefault();
    navigateToFeed(link.href);
});

window.addEventListener('popstate', () => {
    if(isFeedUrl(window.location.href)){
        navigateToFeed(window.location.href, {historyMode:'none'});
    }
});

initializeNewsPage();
})();
