"""Группы источников для расписания парсера и веб-интерфейса."""


GOVERNMENT_GROUP = "government"
AGENCIES_GROUP = "agencies"

GOVERNMENT_SOURCES = frozenset({
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
})

AGENCY_SOURCES = frozenset({
    "РИА Новости",
    "ТАСС",
    "Интерфакс",
    "Yonhap",
    "Киодо (共同通信)",
})


def source_group(source):
    """Возвращает группу источника; старые записи считаются госорганами."""
    if source in AGENCY_SOURCES:
        return AGENCIES_GROUP
    return GOVERNMENT_GROUP


def filter_news_by_group(items, group):
    """Оставляет в ленте только источники выбранного раздела."""
    return [
        item
        for item in items
        if source_group(item.get("source", "")) == group
    ]
