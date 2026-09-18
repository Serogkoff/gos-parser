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
            'grid-row:3;height:53px;gap:18px',
            '.site-section{padding-bottom:17px;font-size:16px}',
            'document.querySelectorAll(\'[data-mark-all-read]\')',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        rail = template[
            template.index('<aside class="left-rail"'):
            template.index('</aside>', template.index('<aside class="left-rail"'))
        ]
        self.assertNotIn('<span>Настройки</span>', rail)
        self.assertNotIn('class="profile-arrow"', rail)
        self.assertNotIn('id="collapse-sources"', template)
        self.assertNotIn('class="mobile-search-jump"', template)
        self.assertIn('.rail-icon{margin-left:4px}', template)
        self.assertIn('align-self:start;transform:translateY(-5px)', template)

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
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        self.assertNotIn("Ключевые факты", template)
        self.assertNotIn("<span>Настройки</span>", template)
        self.assertNotIn('class="article-tools"', template)
        self.assertNotIn('class="article-search"', template)
        self.assertNotIn('class="filter-link"', template)
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
            'class="icon-button danger"',
            'class="icon-button add-action"',
            "confirm('Вы уверены, что хотите удалить подборку?')",
            'class="rail-logout"',
            'aria-label="Выйти" title="Выйти"',
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
        self.assertIn(".collection-detail-actions{position:absolute;top:28px", template)
        self.assertIn(".collection-detail-actions .icon-button{color:var(--coral);border-color:var(--coral)}", template)
        self.assertNotIn("Вложенных папок пока нет", template)
        self.assertIn(".left-rail::-webkit-scrollbar{display:none}", template)
        self.assertIn('class="search-icon"', template)
        self.assertIn('placeholder="Поиск"', template)
        self.assertNotIn("Рабочая подборка со статьями", template)
        self.assertNotIn("<label>Сортировка", template)


if __name__ == "__main__":
    unittest.main()
