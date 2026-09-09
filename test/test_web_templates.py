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
            'class="panel-action-icon order-arrows"',
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
            '>Выйти</button>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        rail = template[
            template.index('<aside class="left-rail"'):
            template.index('</aside>', template.index('<aside class="left-rail"'))
        ]
        self.assertNotIn('<span>Настройки</span>', rail)

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
            '>Выйти</button>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)

        self.assertNotIn("Ключевые факты", template)
        self.assertNotIn("<span>Настройки</span>", template)

    def test_collections_template_uses_editorial_application_layout(self):
        template_path = Path(web_app.app.template_folder) / "bookmarks.html"
        template = template_path.read_text(encoding="utf-8")

        for marker in (
            'class="app-layout"',
            'class="left-rail"',
            'class="rail-link active" href="/collections"',
            'class="topbar"',
            'class="site-sections"',
            'class="clocks"',
            'class="collections-viewport"',
            'grid-template-columns:minmax(0,1fr) 250px',
            '.feed::-webkit-scrollbar,.panel::-webkit-scrollbar{display:none}',
            'class="rail-logout"',
            '>Выйти</button>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)


if __name__ == "__main__":
    unittest.main()
