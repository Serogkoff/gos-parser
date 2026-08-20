"""Группы источников для расписания парсера и веб-интерфейса."""


GOVERNMENT_GROUP = "government"
AGENCIES_GROUP = "agencies"
NEWSPAPERS_GROUP = "newspapers"
YAHOO_SOURCE_PREFIX = "Yahoo! JAPAN"

GOVERNMENT_SOURCES = frozenset({
    "Президент России",
    "МИД РФ",
    "Правительство РФ",
    "Трутнев",
    "Минпромторг",
    "Минприроды",
    "МВД РФ",
    "МЧС",
    "Минкульт",
    "Минздрав",
    "Минтранс",
    "Минэкономразвития",
    "Минфин",
    "Минстрой",
    "Минвостокразвития",
    "Минюст",
    "СК РФ",
    "Развитие Курил",
    "Минспорт",
    "Минтруд",
    "Минпросвещения",
    "Минсельхоз",
    "Минобрнауки",
    "Владивосток",
    "Минэнерго",
    "Минцифры",
    "Сахалин",
    "Сахалинская обл.",
    "Минобороны РФ",
})

AGENCY_SOURCES = frozenset({
    "РИА Новости",
    "ТАСС",
    "Интерфакс",
    "Yonhap",
    "Киодо (共同通信)",
    "Yahoo! JAPAN · トップ",
    "Yahoo! JAPAN · 国内",
    "Yahoo! JAPAN · 国際",
    "Yahoo! JAPAN · 経済",
    "Yahoo! JAPAN · IT",
    "Yahoo! JAPAN · ライフ",
    "Yahoo! JAPAN · 地域",
    "Yahoo! JAPAN · エンタメ",
    "Yahoo! JAPAN · 時事通信",
    "Yahoo! JAPAN · AP通信",
    "Yahoo! JAPAN · CNN",
    "Yahoo! JAPAN · 帝国データバンク",
})

NEWSPAPER_SOURCES = frozenset({
    "Независимая газета",
    "Коммерсантъ",
    "Известия",
    "Российская газета",
    "Ведомости",
    "Красная звезда",
    "Комсомольская правда",
})


def source_group(source):
    """Возвращает группу источника; старые записи считаются госорганами."""
    if source in AGENCY_SOURCES or is_yahoo_source(source):
        return AGENCIES_GROUP
    if source in NEWSPAPER_SOURCES:
        return NEWSPAPERS_GROUP
    return GOVERNMENT_GROUP


def is_yahoo_source(source):
    """Узнаёт все нынешние и будущие подразделы Yahoo! JAPAN."""
    return str(source or "").casefold().startswith(
        YAHOO_SOURCE_PREFIX.casefold()
    )


def filter_news_by_group(items, group):
    """Оставляет в ленте только источники выбранного раздела."""
    return [
        item
        for item in items
        if source_group(item.get("source", "")) == group
    ]
