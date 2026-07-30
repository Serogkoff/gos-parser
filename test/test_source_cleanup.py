import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.mintrud import _is_news_article_url
from utils.article_reader import (
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
    def test_recognizes_unicode_and_punycode_mvd_hosts(self):
        self.assertTrue(
            _is_mvd_url("https://мвд.рф/news/item/12345")
        )
        self.assertTrue(
            _is_mvd_url(
                "https://xn--b1aew.xn--p1ai/news/item/12345"
            )
        )
        self.assertFalse(_is_mvd_url("https://example.com/news/item/12345"))

    def test_mvd_removes_menu_before_and_service_text_after_article(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="og:title"
                          content="МВД сообщило о результатах операции">
                </head>
                <body>
                    <main>
                        <h1>МВД сообщило о результатах операции</h1>
                        <div class="content">
                            <p>График приема граждан руководящим составом
                            МВД России</p>
                            <p>МВД России Министр Структура Министерства
                            Руководство Общественный совет История
                            Противодействие коррупции</p>
                            <p>Сотрудники полиции завершили операцию и
                            пресекли деятельность организованной группы.</p>
                            <p>По материалам проверки возбуждено уголовное
                            дело, расследование которого продолжается.</p>
                            <p>Онлайн-сервисы ВСЕ СЕРВИСЫ Прием обращений
                            граждан и организаций Ваш участковый Отдел
                            полиции Внимание розыск</p>
                            <p>Официальный интернет-сайт МВД России.
                            При использовании материалов сайта ссылка
                            обязательна.</p>
                        </div>
                    </main>
                </body>
            </html>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "https://мвд.рф/news/item/12345",
                "МВД сообщило о результатах операции",
            )

        self.assertFalse(article["error"])
        self.assertEqual(
            article["paragraphs"],
            [
                "Сотрудники полиции завершили операцию и пресекли "
                "деятельность организованной группы.",
                "По материалам проверки возбуждено уголовное дело, "
                "расследование которого продолжается.",
            ],
        )

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
