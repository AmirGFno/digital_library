"""Name cleaning and volume extraction tests."""
import pytest

from utils.text_cleaner import (
    clean_file_stem,
    clean_name,
    clean_series_name,
    extract_volume_number,
    looks_like_volume_series,
    normalize_digits,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Batman 001 (2016) [دانلود از سایت example.com]", "Batman 001 (2016)"),
        ("Spider-Man_Vol_1_#05_[www.ircomics.com]", "Spider-Man Vol 1 #05"),
        ("کمیک بتمن جلد 3 @my_channel", "کمیک بتمن جلد 3"),
        ("Saga 010 (2014) (Digital)", "Saga 010 (2014)"),
        ("Invincible 12 [t.me/comics_channel]", "Invincible 12"),
        ("Watchmen (1986) [HD]", "Watchmen (1986)"),
        ("Daredevil 005 [کانال تلگرام comics]", "Daredevil 005"),
        ("Hellboy 003 - Downloaded from example.net", "Hellboy 003"),
        ("Berserk v41 (2021) [joinchat]", "Berserk v41 (2021)"),
    ],
)
def test_clean_name_removes_advertisements(raw, expected):
    assert clean_name(raw) == expected


def test_clean_name_keeps_useful_brackets():
    assert clean_name("Batman (2016) [Vol 1] #3") == "Batman (2016) [Vol 1] #3"


def test_clean_name_returns_original_when_everything_is_an_ad():
    assert clean_name("@channel") == "@channel"


def test_clean_name_handles_empty_input():
    assert clean_name("") == ""


def test_clean_series_name_from_folder():
    assert clean_series_name("Batman - Complete [www.site.com]") == "Batman - Complete"


def test_normalize_persian_digits():
    assert normalize_digits("جلد ۱۲") == "جلد 12"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Batman 001 (2016)", 1),
        ("Saga Vol. 10", 10),
        ("کمیک بتمن جلد ۳", 3),
        ("Invincible #12", 12),
        ("chapter 7 - the end", 7),
        ("Batman 001-003", 1),
        ("Watchmen (1986)", None),
        ("Comic 1080p", None),
        ("Some Comic Name", None),
        ("جلد ۰۵", 5),
    ],
)
def test_extract_volume_number(name, expected):
    assert extract_volume_number(name) == expected


def test_looks_like_volume_series():
    assert looks_like_volume_series(["Batman 001", "Batman 002", "Batman 003"])
    assert not looks_like_volume_series(["Intro", "Notes", "Bonus"])


@pytest.mark.parametrize(
    "filename, expected",
    [
        # Real names taken from downloaded comics.
        ("Batman 001 [t.me-ComicChannel] (www.comicsite.com).cbz", "Batman 001"),
        ("Batman 001 [t.me ComicChannel] (www.comicsite.com).cbz", "Batman 001"),
        ("Berserk v41 (2021) [دانلود از کانال کمیک] [www.example.ir].cbz", "Berserk v41 (2021)"),
        ("One Piece 1050 - (تبلیغ: کانال تلگرام @onepiece_fa).cbz", "One Piece 1050"),
        ("Deadpool 001 (2008) [دانلود رایگان از سایت دانلودکمیک].cbz", "Deadpool 001 (2008)"),
        ("Batman 001 دانلود از کانال کمیک.cbz", "Batman 001"),
        ("Saga 012 [telegram-@saga_fa].cbz", "Saga 012"),
        ("One Piece 1050 [example.com].cbz", "One Piece 1050"),
        ("Naruto 700 [MangaSite.ir] [join us on telegram].cbz", "Naruto 700"),
        ("Saga 012 @ComicWorld Telegram @ComicWorld.cbz", "Saga 012"),
        # Names that must survive untouched (no ad text).
        ("Spider-Man 005 (Marvel) (2019).cbz", "Spider-Man 005 (Marvel) (2019)"),
        ("Spawn 300 [فارسی].cbz", "Spawn 300 [فارسی]"),
        ("Watchmen (1986) #01.cbr", "Watchmen (1986) #01"),
    ],
)
def test_clean_file_stem_real_world_names(filename, expected):
    assert clean_file_stem(filename) == expected


def test_dotted_folder_name_does_not_lose_its_title():
    assert clean_series_name("Batman [www.site.com]") == "Batman"
    assert clean_series_name("Saga - تیم ترجمه") == "Saga - تیم ترجمه"


def test_no_dangling_brackets_after_cleaning():
    result = clean_name("Berserk v41 (2021) [دانلود از کانال کمیک] [www.example.ir]")
    assert "[" not in result and "]" not in result
