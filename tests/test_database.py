"""Database layer tests (no GUI, no real library needed)."""
from pathlib import Path


def make_file(tmp_path: Path, name: str = "comic.cbz", size: int = 2048) -> str:
    path = tmp_path / name
    path.write_bytes(b"0" * size)
    return str(path)


def test_add_and_get_book(temp_db, tmp_path):
    filepath = make_file(tmp_path)
    book_id = temp_db.add_book(filepath, title="Saga #1")
    assert book_id

    book = temp_db.get_book(book_id)
    assert book["title"] == "Saga #1"
    assert book["file_size"] == 2048
    assert temp_db.get_total_book_count() == 1


def test_duplicate_file_is_rejected(temp_db, tmp_path):
    filepath = make_file(tmp_path)
    assert temp_db.add_book(filepath) is not None
    assert temp_db.add_book(filepath) is None
    assert temp_db.get_total_book_count() == 1


def test_volume_number_extraction(temp_db, tmp_path):
    assert temp_db.add_book(make_file(tmp_path, "v10.cbz"), volume="Vol. 10") is not None
    book = temp_db.get_all_books()[0]
    assert book["volume_num"] == 10


def test_comic_metadata_is_stored(temp_db, tmp_path):
    book_id = temp_db.add_book(
        make_file(tmp_path),
        metadata={
            "title": "The Black Mirror",
            "volume": "2",
            "writer": "Scott Snyder",
            "publisher": "DC Comics",
            "year": 2011,
            "summary": "A dark story",
            "page_count": 120,
        },
    )
    book = temp_db.get_book(book_id)
    assert book["writer"] == "Scott Snyder"
    assert book["publisher"] == "DC Comics"
    assert book["year"] == 2011
    assert book["page_count"] == 120


def test_favorite_rating_and_history(temp_db, tmp_path):
    book_id = temp_db.add_book(make_file(tmp_path))

    assert temp_db.toggle_favorite(book_id) is True
    assert temp_db.get_book(book_id)["favorite"] == 1
    assert len(temp_db.get_favorite_books()) == 1
    assert temp_db.toggle_favorite(book_id) is False

    assert temp_db.set_rating(book_id, 9) is True
    assert temp_db.get_book(book_id)["rating"] == 5

    assert temp_db.mark_book_opened(book_id, mark_read=True) is True
    book = temp_db.get_book(book_id)
    assert book["open_count"] == 1
    assert book["last_opened_at"]
    assert book["is_read"] == 1


def test_search_covers_metadata(temp_db, tmp_path):
    temp_db.add_book(
        make_file(tmp_path, "a.cbz"),
        title="Batman",
        metadata={"writer": "Tom King", "publisher": "DC"},
    )
    temp_db.add_book(make_file(tmp_path, "b.pdf"), title="Spider-Man")
    assert len(temp_db.search_books("Tom King")) == 1
    assert len(temp_db.search_books("Spider")) == 1


def test_bulk_add_and_statistics(temp_db, tmp_path):
    books = [
        {"filepath": make_file(tmp_path, "one.cbz", 1000)},
        {"filepath": make_file(tmp_path, "two.pdf", 3000)},
        {"filepath": make_file(tmp_path, "one.cbz", 1000)},  # duplicate
    ]
    added, skipped = temp_db.bulk_add_books(books)
    assert (added, skipped) == (2, 1)

    stats = temp_db.get_statistics()
    assert stats["total"] == 2
    assert stats["total_size"] == 4000
    assert stats["formats"]["comic"] == 1
    assert stats["formats"]["pdf"] == 1


def test_series_crud_and_filtering(temp_db, tmp_path):
    series_id = temp_db.create_series("Moon Knight")
    assert series_id
    temp_db.add_book(make_file(tmp_path, "mk1.cbz"), series_id=series_id, volume="1")
    temp_db.add_book(make_file(tmp_path, "mk2.cbz"), series_id=series_id, volume="2")

    books = temp_db.get_all_books(series_id=series_id)
    assert [book["volume_num"] for book in books] == [1, 2]
    assert temp_db.get_series_unread_count(series_id) == 2

    assert temp_db.update_series(series_id, "Moon Knight (2021)")
    assert temp_db.get_series(series_id)["name"] == "Moon Knight (2021)"

    assert temp_db.delete_series(series_id)
    assert len(temp_db.get_books_without_series()) == 2


def test_update_book_fields(temp_db, tmp_path):
    book_id = temp_db.add_book(make_file(tmp_path))
    assert temp_db.update_book(book_id, title="New", writer="W", year=2020)
    book = temp_db.get_book(book_id)
    assert (book["title"], book["writer"], book["year"]) == ("New", "W", 2020)


def test_recent_books_order(temp_db, tmp_path):
    first = temp_db.add_book(make_file(tmp_path, "first.cbz"), title="First")
    second = temp_db.add_book(make_file(tmp_path, "second.cbz"), title="Second")
    recent = temp_db.get_recent_books(limit=5)
    assert [book["id"] for book in recent][:2] == [second, first]
