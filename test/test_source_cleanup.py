import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.mintrud import _is_news_article_url
from utils.article_reader import (
    _clean_mvd_paragraphs,
    _clean_mnr_paragraphs,
    _is_mvd_url,
    _paragraphs,
    extract_article,
)


class MintrudUrlTests(unittest.TestCase):
    def test_accepts_news_materials_with_numeric_id(self):
        self.assertTrue(
            _is_news_article_url(
                "https://mintrud.gov.ru/employment/employment/816"
            )
        )
        self.assertTrue(
            _is_news_article_url("https://mintrud.gov.ru/employment/72")
        )

    def test_rejects_events_and_service_pages(self):
        self.assertFalse(
            _is_news_article_url("https://mintrud.gov.ru/events/1451")
        )
        self.assertFalse(
            _is_news_article_url(
                "https://mintrud.gov.ru/news/news/list?page=2&per-page=10"
            )
        )


class ArticleCleanupTests(unittest.TestCase):
    def test_mvd_keeps_feed_title_and_trims_header_and_footer(self):
        soup = BeautifulSoup(
            """
            <main>
                <h1>МИНИСТЕРСТВО ВНУТРЕННИХ ДЕЛ РОССИЙСКОЙ ФЕДЕРАЦИИ</h1>
                <p>График приема граждан руководящим составом МВД России</p>
                <p>О рассмотрении обращений граждан и организаций</p>
                <p>Поступление на службу в органы внутренних дел
                Российской Федерации</p>
                <p>МВД России Министр Структура Министерства Руководство
                Общественный совет История Противодействие коррупции</p>
                <p>Деятельность Служба Статистика и аналитика Мониторинг
                общественного мнения Результаты деятельности</p>
                <p>Для граждан Прием обращений граждан и организаций
                График приема граждан руководящим составом МВД России</p>
                <p>Онлайн-сервисы ВСЕ СЕРВИСЫ Прием обращений граждан и
                организаций Ваш участковый Отдел полиции</p>
                <p>Сотрудники Управления уголовного розыска установили
                личность и задержали курьера мошенников.</p>
                <p>В отношении подозреваемого возбуждено уголовное дело
                по признакам мошенничества.</p>
                <p>Сайты подразделений центрального аппарата МВД России</p>
                <p>Список лиц, которым запрещено посещение мест проведения
                официальных спортивных соревнований</p>
                <p>Все материалы сайта Министерства внутренних дел
                Российской Федерации могут быть воспроизведены.</p>
            </main>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "https://мвд.рф/news/item/12345",
                "Полицейские задержали курьера мошенников",
            )

        self.assertEqual(
            article["title"],
            "Полицейские задержали курьера мошенников",
        )
        self.assertEqual(
            article["paragraphs"],
            [
                "Сотрудники Управления уголовного розыска установили "
                "личность и задержали курьера мошенников.",
                "В отношении подозреваемого возбуждено уголовное дело "
                "по признакам мошенничества.",
            ],
        )

    def test_mvd_cleanup_does_not_remove_article_words_after_start(self):
        paragraphs = [
            "Основной текст публикации уже начался и содержит важные сведения.",
            "О рассмотрении обращений граждан и организаций рассказали "
            "в следующем содержательном абзаце публикации.",
        ]
        self.assertEqual(_clean_mvd_paragraphs(paragraphs), paragraphs)

    def test_recognizes_mvd_unicode_and_punycode_hosts(self):
        self.assertTrue(_is_mvd_url("https://мвд.рф/news/item/12345"))
        self.assertTrue(
            _is_mvd_url("https://xn--b1aew.xn--p1ai/news/item/12345")
        )
        self.assertFalse(_is_mvd_url("https://example.com/news/item/12345"))

    def test_uses_fallback_title_for_generic_page_heading(self):
        soup = BeautifulSoup(
            """
            <main>
                <h1>Новости</h1>
                <p>Юрий Трутнев провёл совещание по вопросам развития
                Дальнего Востока и реализации новых проектов.</p>
            </main>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "http://government.ru/news/59382/",
                "Юрий Трутнев провёл совещание",
            )

        self.assertEqual(
            article["title"],
            "Юрий Трутнев провёл совещание",
        )

    def test_removes_minfin_license_footer(self):
        soup = BeautifulSoup(
            """
            <main>
                <p>Основной текст публикации Министерства финансов Российской Федерации.</p>
                <p>Все материалы сайта доступны по лицензии: Creative Commons
                «Attribution» 4.0 Всемирная.</p>
            </main>
            """,
            "html.parser",
        )
        self.assertEqual(
            _paragraphs(soup),
            [
                "Основной текст публикации Министерства финансов "
                "Российской Федерации."
            ],
        )

    def test_mnr_does_not_return_news_list_heading(self):
        soup = BeautifulSoup(
            """
            <article>
                <p>Новости и пресс-релизы соседних подразделений министерства.</p>
                <p>Шесть российских объектов представили на международной
                сессии ЮНЕСКО в ходе рабочего заседания.</p>
            </article>
            """,
            "html.parser",
        )
        self.assertEqual(
            _clean_mnr_paragraphs(soup, "Заголовок"),
            [
                "Шесть российских объектов представили на международной "
                "сессии ЮНЕСКО в ходе рабочего заседания."
            ],
        )

    def test_verified_source_extracts_only_article_body(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="og:title"
                          content="Минстрой сообщил о новом проекте">
                </head>
                <body>
                    <h1>Минстрой сообщил о новом проекте</h1>
                    <div class="news-detail">
                        <p>Министерство представило новый проект развития
                        городской инфраструктуры в российских регионах.</p>
                    </div>
                </body>
            </html>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "https://minstroyrf.gov.ru/press/novyy-proekt/",
                "Минстрой сообщил о новом проекте",
            )

        self.assertEqual(len(article["paragraphs"]), 1)
        self.assertIn("городской инфраструктуры", article["paragraphs"][0])

    def test_verified_source_rejects_general_news_page(self):
        soup = BeautifulSoup(
            """
            <main>
                <h1>Публикации пресс-центра</h1>
                <p>О министерстве Положение Руководство Департаменты
                Государственные закупки и государственные услуги.</p>
            </main>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "https://minstroyrf.gov.ru/press/novyy-proekt/",
                "Минстрой сообщил о новом проекте",
            )

        self.assertEqual(article["paragraphs"], [])
        self.assertIn("общий раздел", article["error"])

    def test_mintrans_reads_article_body_from_json_ld(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="og:title"
                          content="Электронный документооборот в логистике">
                    <script type="application/ld+json">
                    {
                        "@type": "NewsArticle",
                        "headline": "Электронный документооборот в логистике",
                        "articleBody": "Минтранс России рассказал о переходе на электронные перевозочные документы.\\nУчастники рынка обсудили подготовку информационных систем."
                    }
                    </script>
                </head>
                <body>
                    <h1>Электронный документооборот в логистике</h1>
                </body>
            </html>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "https://mintrans.gov.ru/press-center/news/12851",
                "Электронный документооборот в логистике",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertIn("Минтранс России", article["paragraphs"][0])

    def test_minselKhoz_reads_text_from_div_blocks(self):
        soup = BeautifulSoup(
            """
            <main>
                <div class="publication">
                    <h1>Объём реализации молока вырос на 3,2%</h1>
                    <div class="publication-body">
                        <div>По оперативным данным Минсельхоза России,
                        объём реализации молока продолжил расти.</div>
                        <div>Положительная динамика отмечена в нескольких
                        российских регионах и сельхозорганизациях.</div>
                    </div>
                </div>
            </main>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                (
                    "https://mcx.gov.ru/press-service/news/"
                    "obyem-realizatsii-moloka-vyros/"
                ),
                "Объём реализации молока вырос на 3,2%",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertIn("Минсельхоза России", article["paragraphs"][0])


if __name__ == "__main__":
    unittest.main()
