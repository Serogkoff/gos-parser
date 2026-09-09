"""Отдельные эмблемы источников для редакционной ленты."""


DEFENSE_SOURCE = "Минобороны РФ"

# Все изображения имеют одинаковый холст 180 x 180 и прозрачный фон.
# Трутнев намеренно использует эмблему Правительства РФ, а обе подписи
# Сахалина — один общий файл.
SOURCE_EMBLEMS = {
    "Президент России": "president.png",
    "Правительство РФ": "government.png",
    "Трутнев": "government.png",
    "МИД РФ": "mid.png",
    "МВД РФ": "mvd.png",
    "МЧС": "mchs.png",
    DEFENSE_SOURCE: "minoborony.png",
    "СК РФ": "sk.png",
    "Минюст": "minyust.png",
    "Минпромторг": "minpromtorg.png",
    "Минэкономразвития": "mineconomrazvitiya.png",
    "Минфин": "minfin.png",
    "Минстрой": "minstroi.png",
    "Минтранс": "mintrans.png",
    "Минвостокразвития": "minvostokrazvitiya.png",
    "Минэнерго": "minenergo.png",
    "Минцифры": "mincifri.png",
    "Минсельхоз": "minselhoz.png",
    "Минприроды": "minprirodi.png",
    "Минкульт": "mincult.png",
    "Минздрав": "minzdrav.png",
    "Минспорт": "minsport.png",
    "Минтруд": "mintrud.png",
    "Минпросвещения": "minprosvesheniya.png",
    "Минобрнауки": "minobrnauki.png",
    "Развитие Курил": "kurily.png",
    "Владивосток": "vladivostok.png",
    "Сахалин": "sakhalin.png",
    "Сахалинская обл.": "sakhalin.png",
}

AGENCY_EMBLEMS = {
    "РИА Новости": "ria.png",
    "ТАСС": "tass.png",
    "Интерфакс": "interfax.png",
    "Yonhap": "yonhap.png",
    "Киодо (共同通信)": "kyodo.png",
}

NEWSPAPER_EMBLEMS = {
    "Независимая газета": "ng.png",
    "Коммерсантъ": "kommersant.png",
    "Известия": "izvestia.png",
    "Российская газета": "rg.png",
    "Ведомости": "vedomosti.png",
    "Красная звезда": "redstar.png",
    "Комсомольская правда": "kp.png",
}


def source_emblem(source):
    """Возвращает эмблему источника, включая все подразделы Yahoo."""
    source = str(source or "")
    if source.casefold().startswith("Yahoo! JAPAN".casefold()):
        return "yahoo.png"
    return (
        SOURCE_EMBLEMS.get(source)
        or AGENCY_EMBLEMS.get(source)
        or NEWSPAPER_EMBLEMS.get(source)
    )
