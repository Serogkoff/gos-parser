import unittest
from pathlib import Path

import web_app


class WebTemplateTests(unittest.TestCase):
    def test_all_page_templates_are_available(self):
        template_names = (
            "admin_incidents.html",
            "admin_reliability.html",
            "admin_sources.html",
            "admin_system.html",
            "article.html",
            "auth.html",
            "bookmarks.html",
            "news.html",
            "notes.html",
            "settings.html",
        )

        for template_name in template_names:
            with self.subTest(template=template_name):
                template = web_app.app.jinja_env.get_template(template_name)
                self.assertEqual(template.name, template_name)

    def test_news_template_keeps_editorial_desktop_layout(self):
        template_path = Path(web_app.app.template_folder) / "news.html"
        template = template_path.read_text(encoding="utf-8")
        stylesheet = (
            Path(web_app.app.static_folder) / "news.css"
        ).read_text(encoding="utf-8")
        javascript = (
            Path(web_app.app.static_folder) / "news.js"
        ).read_text(encoding="utf-8")
        page_source = template + stylesheet + javascript

        self.assertIn(
            "filename='news.css'",
            template,
        )
        self.assertIn("feed_asset_version|urlencode", template)
        self.assertIn("filename='news.js'", template)
        self.assertIn('id="news-page-config" type="application/json"', template)
        self.assertNotIn("<style>", template)
        self.assertNotIn("const cards =", template)

        for marker in (
            "async function navigateToFeed(value, options = {})",
            "headers:{'X-Requested-With':'feed-navigation'}",
            "currentShell.replaceWith(nextShell)",
            "currentMobileNav.replaceWith(nextMobileNav)",
            "window.history.pushState({feedNavigation:true}",
            "window.addEventListener('popstate'",
            "if(navigationRequest) navigationRequest.abort()",
            "async function prepareVisibleFeedEmblems(shell)",
            "await prepareVisibleFeedEmblems(nextShell)",
            ".slice(0, limit)",
            "image.decoding = 'sync'",
            "initializeNewsPage();",
        ):
            with self.subTest(partial_navigation_marker=marker):
                self.assertIn(marker, javascript)

        self.assertNotIn("document.startViewTransition", javascript)
        self.assertNotIn("applyFilters()", javascript)

        for marker in (
            'class="app-layout"',
            'class="left-rail"',
            'class="content-grid"',
            'class="clock-date"',
            'class="source-mark"',
            'class="source-emblem source-emblem-main',
            'class="source-emblem source-emblem-compact',
            "filename='source-logos/' ~ emblem",
            'class="news-summary"',
            'Найдено {{page_total_display}} материалов',
            '<svg viewBox="0 0 20 24" aria-hidden="true">',
            '-webkit-line-clamp:3',
            'overflow-x:hidden',
            'class="panel-action-icon order-settings"',
            'M14.7 6.3a4 4 0 0 0-5 5',
            'aria-label="Прочитать все новости"',
            '@media(min-width:921px)',
            'grid-template-rows:88px minmax(0,1fr)',
            'grid-template-columns:minmax(0,1fr) 250px',
            'grid-column:1;grid-row:2;height:44px',
            '.search{width:135px;max-width:135px;flex:0 0 135px',
            'position:absolute;z-index:10;top:102px;right:0',
            '.sidebar{min-width:0;margin-top:56px',
            '.content-grid{grid-template-columns:minmax(0,1fr) 250px}',
            'overscroll-behavior:contain',
            'scrollbar-width:none',
            '.feed::-webkit-scrollbar,.sidebar::-webkit-scrollbar{display:none}',
            '.panel-title-actions{top:calc(50% + 12px)}',
            '.news-card{border-bottom:0}',
            '.source-row{border-bottom:0}',
            '.rail-bottom{margin-top:auto;padding-bottom:24px',
            '<circle cx="10.5" cy="10.5" r="6.5"/>',
            'M3.5 7.5h6l2-2h3l2 2h4',
            'class="rail-logout"',
            'aria-label="Выйти" title="Выйти"',
            'class="rail-profile-link"',
            'class="search-tools"',
            'class="mobile-bottom-nav"',
            'aria-label="Мобильное меню"',
            'grid-template-columns:repeat(5,minmax(0,1fr))',
            'class="mobile-source-open"',
            'aria-label="Управление источниками"',
            '.news-card h3{font-size:15px',
            '.panel-title-actions{position:absolute;right:0;top:50%;width:70px;display:grid;grid-template-columns:32px 32px;gap:6px;transform:translateY(-50%)}',
            'min-height:52px;padding:0 0 0 8px',
            'grid-row:3;height:53px;gap:12px',
            '.site-section{padding:0 1px 17px;font-size:15px}',
            'position:fixed;z-index:50;right:0;bottom:0;left:0',
            'height:calc(68px + env(safe-area-inset-bottom))',
            'transform:translate3d(0,0,0)',
            '-webkit-backface-visibility:hidden;backface-visibility:hidden',
            'document.querySelectorAll(\'[data-mark-all-read]\')',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, page_source)

        rail = template[
            template.index('<aside class="left-rail"'):
            template.index('</aside>', template.index('<aside class="left-rail"'))
        ]
        self.assertNotIn('<span>Настройки</span>', rail)
        self.assertNotIn('class="profile-arrow"', rail)
        self.assertNotIn('id="collapse-sources"', template)
        self.assertNotIn('class="mobile-search-jump"', template)
        self.assertIn('.rail-icon{margin-left:4px}', stylesheet)
        self.assertIn('align-self:start;transform:translateY(-5px)', stylesheet)

    def test_auth_template_uses_blurred_static_product_preview(self):
        template_path = Path(web_app.app.template_folder) / "auth.html"
        template = template_path.read_text(encoding="utf-8")

        for marker in (
            'class="preview" aria-hidden="true"',
            "filter:blur(9px)",
            'class="card" aria-labelledby="auth-title"',
            'name="remember" value="1"',
            "Включён Caps Lock",
            "Доступ только для зарегистрированных пользователей",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        self.assertNotIn("load_all_news", template)
        self.assertNotIn("Забыли пароль", template)

    def test_notes_template_uses_versioned_cached_styles(self):
        template_path = Path(web_app.app.template_folder) / "notes.html"
        template = template_path.read_text(encoding="utf-8")
        stylesheet = Path(web_app.app.static_folder) / "notes.css"

        self.assertTrue(stylesheet.is_file())
        self.assertIn("filename='notes.css'", template)
        self.assertIn("asset_version|urlencode", template)
        self.assertNotIn("<style>", template)

    def test_system_template_keeps_storage_controls_explicit(self):
        template_path = Path(web_app.app.template_folder) / "admin_system.html"
        template = template_path.read_text(encoding="utf-8")

        for marker in (
            "контрольного порога",
            "не больше {{backup_retention}} копий всего",
            'name="action" value="purge_news_archive"',
            "ОЧИСТИТЬ АРХИВ",
            "за последние {{news_retention_days}} дней",
            "Пользователи, избранное, подборки, заметки",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

    def test_article_template_matches_editorial_feed_design(self):
        template_path = Path(web_app.app.template_folder) / "article.html"
        template = template_path.read_text(encoding="utf-8")

        for marker in (
            'class="app-layout"',
            'class="left-rail"',
            'class="topbar"',
            'class="article-card"',
            'class="source-emblem"',
            'class="original"',
            '>Открыть оригинал</a>',
            'id="article-back"',
            '>Назад</a>',
            'class="article-viewport"',
            'article-viewport::-webkit-scrollbar{display:none}',
            'class="rail-logout"',
            'aria-label="Выйти" title="Выйти"',
            'class="mobile-brand" href="/all">Монитор</a>',
            'class="mobile-bottom-nav"',
            'aria-label="Мобильное меню"',
            'grid-template-columns:repeat(5,minmax(0,1fr))',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        self.assertNotIn("Ключевые факты", template)
        self.assertNotIn("<span>Настройки</span>", template)
        self.assertNotIn('class="article-tools"', template)
        self.assertNotIn('class="article-search"', template)
        self.assertNotIn('class="filter-link"', template)
        self.assertNotIn("Обновить текст", template)
        self.assertNotIn('class="refresh"', template)
        self.assertIn('color:var(--coral);border:1px solid var(--coral)', template)

    def test_collections_template_uses_editorial_application_layout(self):
        template_path = Path(web_app.app.template_folder) / "bookmarks.html"
        template = template_path.read_text(encoding="utf-8")

        for marker in (
            'class="app-layout"',
            'class="left-rail"',
            'class="rail-link active" href="/collections"',
            'class="collections-topbar"',
            'class="collections-title">Подборки',
            'class="clocks"',
            'class="collections-viewport"',
            'class="collection-toolbar"',
            'class="folder-browser"',
            'class="folder-card-grid"',
            'data-create-collection-open',
            'data-manage-collection-open',
            'data-manage-collection-panel',
            'data-composer-open',
            'class="meta material-meta"',
            'class="material-source"',
            'class="primary bookmark-save"',
            '>Открыть оригинал</a>',
            'class="icon-button danger"',
            'class="icon-button add-action"',
            "confirm('Вы уверены, что хотите удалить подборку?')",
            'class="rail-logout"',
            'aria-label="Выйти" title="Выйти"',
            'class="mobile-brand" href="/all">Монитор</a>',
            'class="mobile-bottom-nav"',
            'aria-label="Мобильное меню"',
            '.folder-card-grid{grid-template-columns:repeat(2,minmax(0,1fr))',
            '.folder-card{min-height:88px',
            'display:flex!important',
            'grid-template-columns:repeat(5,minmax(0,1fr))',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        self.assertNotIn('class="site-sections"', template)
        self.assertNotIn('<div class="collection-tree">', template)
        self.assertNotIn('aria-label="Сортировка"', template)
        self.assertNotIn("Мои подборки", template)
        self.assertNotIn('name="comment"', template)
        self.assertNotIn('class="panel"', template)
        self.assertIn(".collections-title{margin:0;padding:0 0 22px 2px", template)
        self.assertIn(".collections-title{font-size:20px}", template)
        self.assertIn(".collections-title:after", template)
        self.assertNotIn("folder.bookmark_count + folder.note_count", template)
        self.assertIn("visible_folders", template)
        self.assertIn(".folder-card-grid{display:grid", template)
        self.assertIn(".collection-toolbar{width:min(100%,600px)", template)
        self.assertIn("grid-template-rows:48px 48px", template)
        self.assertIn(".collection-head{border-bottom:0}", template)
        self.assertIn(".folder-card{border:0;background:transparent}", template)
        self.assertIn("@media(min-width:761px){.collection-toolbar{grid-template-columns:minmax(260px,1fr) auto", template)
        self.assertIn(".collection-toolbar .search{grid-column:1;grid-row:1}", template)
        self.assertIn('aria-label="Папки подборок"', template)
        self.assertNotIn('id="folder-browser-title">Папки</h3>', template)
        self.assertIn(".collection-detail-actions{position:absolute;top:28px", template)
        self.assertIn(".collection-detail-actions .icon-button{color:var(--coral);border-color:var(--coral)}", template)
        self.assertNotIn("Вложенных папок пока нет", template)
        self.assertIn(".left-rail::-webkit-scrollbar{display:none}", template)
        self.assertIn('class="search-icon"', template)
        self.assertIn('placeholder="Поиск"', template)
        self.assertNotIn("Рабочая подборка со статьями", template)
        self.assertNotIn("<label>Сортировка", template)
        self.assertNotIn('<span class="badge">Статья</span>', template)
        self.assertNotIn(
            '<div class="article-section-head"><strong>Статьи</strong></div>',
            template,
        )
        self.assertIn(".material-meta{min-height:42px", template)
        self.assertIn(".edit .bookmark-save{min-height:36px", template)


if __name__ == "__main__":
    unittest.main()
