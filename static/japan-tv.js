(() => {
    const STORAGE_KEY = 'monitor-japan-tv';
    const root = document.documentElement;
    let originals = new WeakMap();
    let translatedValues = new WeakMap();
    let observer = null;

    const exact = new Map(Object.entries({
        'Монитор':'速報モニター','Госструктуры':'官公庁','Информагентства':'通信社',
        'Газеты':'新聞・メディア','Подборки':'保存済みコレクション','Москва':'モスクワ時間','Токио':'東京時間',
        'Новости госструктур':'ロシア公式ニュース','Новости информагентств':'情報メディア速報',
        'Свежие номера газет':'新聞・メディア最新号','Агрегатор официальных источников':'情報は力だ！逃すな最新ニュース！',
        'Администратор':'管理者','Пользователь':'ユーザー','Все':'すべて',
        'Совпадения':'キーワード魔法陣','Последние публикации':'★ 最新ニュース速報 ★',
        'Источники':'情報ソース★パワーランキング','Все источники':'👑 全ソース（ALL）','Изменить':'並べ替え',
        'Готово':'完了','Прочитать всё':'すべて既読','Сводка покрытия':'監視状況',
        'Источников всего':'配信元 合計','Работают':'稼働中','Пустая выдача':'記事なし',
        'Ошибки парсинга':'取得エラー','Требуют внимания':'要確認','временно':'一時停止',
        'ошибка':'エラー','недоступен':'接続不可','Ничего не найдено':'該当なし',
        'Измени запрос или отключи фильтр。':'検索条件を変更してください。',
        'Измени запрос или отключи фильтр.':'検索条件を変更してください。',
        'Ключевые слова':'キーワード','Добавить':'追加','Все ключевые слова':'すべてのキーワード',
        'Новая':'新着','Совпадение с ключевыми словами':'キーワード一致',
        'Сбросить':'解除','Мой аккаунт':'マイアカウント','Пользователи':'ユーザー管理',
        'Система':'システム','Инциденты':'障害情報','Надёжность':'信頼性',
        'Настройки аккаунта':'アカウント設定','Сменить пароль':'パスワード変更',
        'Текущий пароль':'現在のパスワード','Новый пароль':'新しいパスワード',
        'Повтори новый пароль':'新しいパスワード（確認）','Сохранить новый пароль':'保存',
        'Новый пользователь':'新規ユーザー','Логин':'ログイン名','Роль':'権限',
        'Временный пароль':'仮パスワード','Повтори пароль':'パスワード（確認）',
        'Создать аккаунт':'アカウント作成','Активен':'有効','Отключён':'無効',
        'Сменить':'変更','Удалить пользователя':'ユーザー削除','Отключить вход':'ログイン停止',
        'Включить вход':'ログイン許可','Вернуться к Монитору':'モニターに戻る',
        'Вернуться к ленте':'一覧に戻る','Открыть оригинал':'元記事を開く',
        'Обновить текст':'本文を更新','Подборки и заметки':'特集ファイルとメモ',
        'Моё избранное':'お気に入り','Новая папка':'新規フォルダー','Создать':'作成',
        'Сортировка':'並び順','Сначала новые':'新しい順','Сначала старые':'古い順',
        'По заголовку':'見出し順','По источнику':'配信元順','Скачать Word':'Word出力',
        'Удалить':'削除','Редактировать':'編集','Сохранить':'保存','Отмена':'キャンセル',
        'Вход':'ログイン','Личный кабинет':'アカウント','Пароль':'パスワード',
        'Войти':'ログイン','Первый запуск':'初回セットアップ','Настройка владельца':'管理者設定',
        'Создать администратора':'管理者を作成','Показать пароль':'パスワードを表示',
        'Скрыть пароль':'パスワードを隠す','На паузе':'停止中','Ждут внимания':'要確認',
        'Всего источников':'配信元 合計','Автоматическая диагностика':'自動診断',
        'Запустить':'実行','Пауза':'停止','Включить':'有効化','Отключить':'無効化',
        'Ручная проверка':'手動チェック','Резервные копии':'バックアップ',
        'Обновлено':'更新','Закрыть':'閉じる'
    }));

    const protectedSelector = [
        '.news-card h3','article h1','.body','.bookmark h3','.note-card h3',
        '.note-text','.note-text-part','.comment','.chips','.identity strong'
    ].join(',');

    function translateString(value){
        const leading = value.match(/^\s*/)[0];
        const trailing = value.match(/\s*$/)[0];
        const plain = value.trim();
        if(!plain) return value;
        let result = exact.get(plain);
        if(!result){
            result = plain
                .replace(/^(\d+) из (\d+) источников работают$/, '稼働中 $1 / $2')
                .replace(/^Выбрано: (\d+)$/, '選択: $1')
                .replace(/^Выбрано источников: (\d+)$/, '配信元を $1 件選択')
                .replace(/^Источник: (.+)$/, '配信元: $1')
                .replace(/^Совпадения: (.+)$/, 'キーワード一致: $1')
                .replace(/^Получено (.+)$/, '受信 $1')
                .replace(/^Обновлено (.+)$/, '更新 $1')
                .replace(/^Страница (\d+) из (\d+)(.*)$/, '第$1 / $2ページ$3')
                .replace(/^Последний вход: (.+)$/, '最終ログイン: $1')
                .replace(/^Создан (.+)$/, '作成日: $1')
                .replace(/^Сохранено локально (.+)$/, 'ローカル保存: $1');
        }
        return leading + result + trailing;
    }

    function shouldKeep(node){
        const parent = node.parentElement;
        return !parent || Boolean(parent.closest(protectedSelector));
    }

    function translateNode(node){
        if(shouldKeep(node)) return;
        const current = node.nodeValue;
        if(translatedValues.get(node) === current) return;
        originals.set(node, current);
        const translated = translateString(current);
        translatedValues.set(node, translated);
        if(translated !== current) node.nodeValue = translated;
    }

    function translateSubtree(target=document.body){
        if(!target) return;
        if(target.nodeType === Node.TEXT_NODE){
            translateNode(target);
            return;
        }
        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
        while(walker.nextNode()) translateNode(walker.currentNode);
        document.querySelectorAll('input[placeholder]').forEach(input => {
            if(!input.dataset.jptvPlaceholder) input.dataset.jptvPlaceholder = input.placeholder;
            const placeholder = input.placeholder;
            if(placeholder.includes('Поиск по заголовкам')) input.placeholder = '見出しを検索・Enter';
            else if(placeholder.startsWith('Например:')) input.placeholder = '例：沿海地方';
        });
        document.querySelectorAll('[aria-label]').forEach(element => {
            if(!element.dataset.jptvAria) element.dataset.jptvAria = element.getAttribute('aria-label');
            element.setAttribute('aria-label', translateString(element.getAttribute('aria-label')));
        });
        const brand = document.querySelector('.brand-text');
        if(brand) brand.textContent = '速報モニター';
    }

    function restore(){
        if(observer) observer.disconnect();
        document.querySelectorAll('*').forEach(element => {
            [...element.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).forEach(node => {
                if(originals.has(node)) node.nodeValue = originals.get(node);
            });
            if(element.dataset.jptvPlaceholder !== undefined){
                element.placeholder = element.dataset.jptvPlaceholder;
                delete element.dataset.jptvPlaceholder;
            }
            if(element.dataset.jptvAria !== undefined){
                element.setAttribute('aria-label', element.dataset.jptvAria);
                delete element.dataset.jptvAria;
            }
        });
        originals = new WeakMap();
        translatedValues = new WeakMap();
    }

    function observe(){
        observer = new MutationObserver(changes => {
            changes.forEach(change => {
                if(change.type === 'characterData') translateNode(change.target);
                change.addedNodes.forEach(node => translateSubtree(node));
            });
        });
        observer.observe(document.body, {subtree:true,childList:true,characterData:true});
    }

    function setMode(enabled){
        if(enabled){
            root.classList.add('japan-tv','jptv-entering');
            try{localStorage.setItem(STORAGE_KEY,'1')}catch(error){}
            translateSubtree();
            observe();
            setTimeout(() => root.classList.remove('jptv-entering'), 500);
        }else{
            root.classList.remove('japan-tv','jptv-entering');
            try{localStorage.removeItem(STORAGE_KEY)}catch(error){}
            restore();
        }
    }

    window.toggleJapanTVMode = () => setMode(!root.classList.contains('japan-tv'));

    const switchButton = document.createElement('button');
    switchButton.type = 'button';
    switchButton.className = 'jptv-mode-switch';
    switchButton.textContent = '通常版に戻る';
    switchButton.setAttribute('aria-label','Вернуть обычный дизайн');
    switchButton.addEventListener('click', () => setMode(false));
    document.body.appendChild(switchButton);

    if(root.classList.contains('japan-tv')) setMode(true);
})();
