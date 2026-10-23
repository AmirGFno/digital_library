"""
Database module for the Digital Library application.
Uses SQLite with proper connection handling and PRAGMA settings.
"""
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from contextlib import contextmanager

from config import DATABASE_PATH
from utils.logger import logger
from utils.helpers import sort_books_naturally


def normalize_path(filepath: str) -> str:
    """Return a canonical absolute path used for duplicate detection.

    Windows paths are case-insensitive, so they are lower-cased; on Linux and
    macOS the real case is preserved (macOS is case-insensitive too, but keeping
    the original path readable matters more than an edge case there).
    """
    try:
        resolved = os.path.abspath(os.path.expanduser(str(filepath)))
        resolved = os.path.normpath(resolved)
    except Exception:
        resolved = str(filepath)
    if os.name == "nt":
        resolved = resolved.lower()
    return resolved


class Database:
    """Database handler with connection pooling and safe operations."""
    
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            # Set PRAGMA settings
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def _extract_volume_number(self, volume: Optional[str]) -> Optional[int]:
        """Extract first number from volume string."""
        if not volume:
            return None
        numbers = re.findall(r'\d+', volume)
        return int(numbers[0]) if numbers else None
    
    def _init_database(self):
        """Initialize database schema with backward compatibility."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create series table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # First create basic books table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    series_id INTEGER,
                    volume TEXT,
                    filepath TEXT UNIQUE NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE SET NULL
                )
            """)
            
            # Create metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Get current columns
            cursor.execute("PRAGMA table_info(books)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            # Add new columns if they don't exist
            if 'volume_num' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE books ADD COLUMN volume_num INTEGER")
                    logger.info("Added volume_num column")
                    
                    # Update existing books with volume numbers
                    cursor.execute("SELECT id, volume FROM books WHERE volume IS NOT NULL")
                    books = cursor.fetchall()
                    
                    for book_id, volume in books:
                        volume_num = self._extract_volume_number(volume)
                        if volume_num is not None:
                            cursor.execute(
                                "UPDATE books SET volume_num = ? WHERE id = ?",
                                (volume_num, book_id)
                            )
                    
                    logger.info(f"Updated {len(books)} books with volume numbers")
                    
                except Exception as e:
                    logger.warning(f"Could not add volume_num: {e}")
            
            if 'custom_cover' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE books ADD COLUMN custom_cover TEXT")
                    logger.info("Added custom_cover column")
                except Exception as e:
                    logger.warning(f"Could not add custom_cover: {e}")

            # --- Schema v3: reading statistics and comic metadata ---------
            new_columns = {
                'favorite': 'INTEGER DEFAULT 0',
                'rating': 'INTEGER DEFAULT 0',
                'last_opened_at': 'TEXT',
                'open_count': 'INTEGER DEFAULT 0',
                'page_count': 'INTEGER',
                'file_size': 'INTEGER',
                'writer': 'TEXT',
                'publisher': 'TEXT',
                'year': 'INTEGER',
                'summary': 'TEXT',
                'genre': 'TEXT',
                'language': 'TEXT',
            }
            cursor.execute("PRAGMA table_info(books)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            for column, column_type in new_columns.items():
                if column in existing_columns:
                    continue
                try:
                    cursor.execute(f"ALTER TABLE books ADD COLUMN {column} {column_type}")
                    logger.info(f"Added {column} column")
                except Exception as e:
                    logger.warning(f"Could not add {column}: {e}")

            # --- Schema v4: duplicate detection -----------------------------
            cursor.execute("PRAGMA table_info(books)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            if 'file_hash' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE books ADD COLUMN file_hash TEXT")
                    logger.info("Added file_hash column")
                except Exception as e:
                    logger.warning(f"Could not add file_hash: {e}")

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_books_favorite ON books(favorite)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_books_last_opened ON books(last_opened_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_books_file_hash ON books(file_hash)"
            )
            
            # Create basic indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_series 
                ON books(series_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_filepath 
                ON books(filepath)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_is_read 
                ON books(is_read)
            """)
            
            # Create volume_num index only if column exists
            cursor.execute("PRAGMA table_info(books)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            if 'volume_num' in existing_columns:
                try:
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_books_volume_num 
                        ON books(volume_num)
                    """)
                except Exception as e:
                    logger.warning(f"Could not create volume_num index: {e}")
            
            # Set schema version
            cursor.execute("""
                INSERT OR REPLACE INTO metadata (key, value, updated_at)
                VALUES ('schema_version', '4.0', CURRENT_TIMESTAMP)
            """)
            
            logger.info("Database initialized successfully")
    
    # ==================== SERIES OPERATIONS ====================
    
    def create_series(self, name: str) -> Optional[int]:
        """Create a new series and return its ID."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO series (name) VALUES (?)",
                    (name,)
                )
                series_id = cursor.lastrowid
                logger.info(f"Created series: {name} (ID: {series_id})")
                return series_id
        except sqlite3.IntegrityError:
            logger.warning(f"Series already exists: {name}")
            return None
    
    def get_series(self, series_id: int) -> Optional[Dict]:
        """Get a series by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM series WHERE id = ?",
                (series_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_series(self) -> List[Dict]:
        """Get all series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM series ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def update_series(self, series_id: int, name: str) -> bool:
        """Update a series name."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE series SET name = ? WHERE id = ?",
                    (name, series_id)
                )
                return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            logger.warning(f"Cannot update series: name '{name}' already exists")
            return False
    
    def delete_series(self, series_id: int) -> bool:
        """Delete a series (books will have series_id set to NULL)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM series WHERE id = ?",
                (series_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted series ID: {series_id}")
            return deleted
    
    def get_series_by_name(self, name: str) -> Optional[Dict]:
        """Get a series by name."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM series WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_series_unread_count(self, series_id: int) -> int:
        """Get count of unread books in a series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM books WHERE series_id = ? AND is_read = 0",
                (series_id,)
            )
            return cursor.fetchone()[0]
    
    def get_all_series_with_counts(self) -> List[Dict]:
        """Get all series with book counts and unread counts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    s.*,
                    COUNT(b.id) as book_count,
                    SUM(CASE WHEN b.is_read = 0 THEN 1 ELSE 0 END) as unread_count
                FROM series s
                LEFT JOIN books b ON s.id = b.series_id
                GROUP BY s.id
                ORDER BY s.name
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== BOOK OPERATIONS ====================
    
    @staticmethod
    def _file_size(filepath: str) -> Optional[int]:
        try:
            return Path(filepath).stat().st_size
        except OSError:
            return None

    def add_book(self, filepath: str, title: Optional[str] = None,
                 series_id: Optional[int] = None, volume: Optional[str] = None,
                 metadata: Optional[Dict] = None,
                 file_hash: Optional[str] = None) -> Optional[int]:
        """Add a new book and return its ID.

        ``metadata`` may contain ComicInfo.xml values such as writer,
        publisher, year, summary, page_count and genre.
        """
        try:
            metadata = metadata or {}
            volume = volume if volume is not None else metadata.get('volume')
            title = title or metadata.get('title')
            volume_num = self._extract_volume_number(volume)

            record = {
                'title': title,
                'series_id': series_id,
                'volume': str(volume) if volume is not None else None,
                'volume_num': volume_num,
                'filepath': str(filepath),
                'file_size': self._file_size(filepath),
                'file_hash': file_hash or compute_file_hash(filepath),
            }
            for key in ('writer', 'publisher', 'year', 'summary', 'page_count', 'genre', 'language'):
                value = metadata.get(key)
                if value not in (None, ''):
                    record[key] = value

            columns = ', '.join(record.keys())
            placeholders = ', '.join('?' for _ in record)
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"INSERT INTO books ({columns}) VALUES ({placeholders})",
                    list(record.values())
                )
                book_id = cursor.lastrowid
                logger.info(f"Added book: {filepath} (ID: {book_id})")
                return book_id
        except sqlite3.IntegrityError:
            logger.warning(f"Book already exists: {filepath}")
            return None
    
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get a book by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.id = ?
            """, (book_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_book_by_filepath(self, filepath: str) -> Optional[Dict]:
        """Get a book by filepath."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.filepath = ?
            """, (filepath,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_books(self, series_id: Optional[int] = None) -> List[Dict]:
        """Get all books, optionally filtered by series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if series_id is not None:
                cursor.execute("""
                    SELECT b.*, s.name as series_name
                    FROM books b
                    LEFT JOIN series s ON b.series_id = s.id
                    WHERE b.series_id = ?
                """, (series_id,))
            else:
                cursor.execute("""
                    SELECT b.*, s.name as series_name
                    FROM books b
                    LEFT JOIN series s ON b.series_id = s.id
                """)
            
            books = [dict(row) for row in cursor.fetchall()]
            return sort_books_naturally(books)

    def get_books_without_series(self) -> List[Dict]:
        """Get all books that don't belong to any series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, NULL as series_name
                FROM books b
                WHERE b.series_id IS NULL
            """)
            
            books = [dict(row) for row in cursor.fetchall()]
            return sort_books_naturally(books)
    
    def update_book(self, book_id: int, **kwargs) -> bool:
        """Update book fields (metadata, reading state, favorite, rating...)."""
        allowed_fields = {
            'title', 'series_id', 'volume', 'is_read', 'custom_cover',
            'favorite', 'rating', 'last_opened_at', 'open_count', 'page_count',
            'file_size', 'writer', 'publisher', 'year', 'summary', 'genre',
            'language',
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return False
        
        # If volume is updated, recalculate volume_num
        if 'volume' in updates:
            volume = updates['volume']
            updates['volume_num'] = self._extract_volume_number(volume)
        
        updates['updated_at'] = datetime.now().isoformat()
        
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [book_id]
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE books SET {set_clause} WHERE id = ?",
                values
            )
            return cursor.rowcount > 0
    
    def toggle_book_read(self, book_id: int) -> Optional[bool]:
        """Toggle the read status of a book. Returns new status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_read FROM books WHERE id = ?",
                (book_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            new_status = 0 if row['is_read'] else 1
            cursor.execute("""
                UPDATE books 
                SET is_read = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_status, book_id))
            
            logger.info(f"Book {book_id} marked as {'read' if new_status else 'unread'}")
            return bool(new_status)
    
    def delete_book(self, book_id: int) -> bool:
        """Delete a book from the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM books WHERE id = ?",
                (book_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted book ID: {book_id}")
            return deleted
    
    # Custom cover operations
    def set_custom_cover(self, book_id: int, cover_path: str) -> bool:
        """Set a custom cover image for a book."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE books SET custom_cover = ? WHERE id = ?",
                (cover_path, book_id)
            )
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Set custom cover for book {book_id}: {cover_path}")
            return updated
    
    def get_custom_cover(self, book_id: int) -> Optional[str]:
        """Get custom cover path for a book."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT custom_cover FROM books WHERE id = ?",
                (book_id,)
            )
            row = cursor.fetchone()
            return row['custom_cover'] if row and row['custom_cover'] else None
    
    def remove_custom_cover(self, book_id: int) -> bool:
        """Remove custom cover from a book."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE books SET custom_cover = NULL WHERE id = ?",
                (book_id,)
            )
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Removed custom cover from book {book_id}")
            return updated
    
    # Other operations
    def get_recent_books(self, limit: int = 20) -> List[Dict]:
        """Get the most recently added books (newest first)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                ORDER BY datetime(b.created_at) DESC, b.id DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_recently_read_books(self, limit: int = 20) -> List[Dict]:
        """Books that were opened recently (newest first)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.last_opened_at IS NOT NULL
                ORDER BY datetime(b.last_opened_at) DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def mark_book_opened(self, book_id: int, mark_read: bool = False) -> bool:
        """Record that a book was opened and optionally mark it as read."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE books
                SET open_count = COALESCE(open_count, 0) + 1,
                    last_opened_at = CURRENT_TIMESTAMP,
                    is_read = CASE WHEN ? THEN 1 ELSE is_read END
                WHERE id = ?
            """, (1 if mark_read else 0, book_id))
            return cursor.rowcount > 0

    def toggle_favorite(self, book_id: int) -> Optional[bool]:
        """Toggle the favorite flag and return the new state."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT favorite FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            if not row:
                return None
            new_state = 0 if row['favorite'] else 1
            cursor.execute(
                "UPDATE books SET favorite = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_state, book_id)
            )
            return bool(new_state)

    def set_rating(self, book_id: int, rating: int) -> bool:
        """Set a 0-5 star rating for a book."""
        rating = max(0, min(5, int(rating)))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE books SET rating = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (rating, book_id)
            )
            return cursor.rowcount > 0

    def get_favorite_books(self) -> List[Dict]:
        """Get all books marked as favorites."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.favorite = 1
            """)
            return sort_books_naturally([dict(row) for row in cursor.fetchall()])

    def get_unread_books(self) -> List[Dict]:
        """Get all unread books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.is_read = 0
            """)
            
            books = [dict(row) for row in cursor.fetchall()]
            return sort_books_naturally(books)
    
    def get_total_unread_count(self) -> int:
        """Get total count of unread books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM books WHERE is_read = 0")
            return cursor.fetchone()[0]
    
    def get_total_book_count(self) -> int:
        """Get total count of books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM books")
            return cursor.fetchone()[0]
    
    def search_books(self, query: str) -> List[Dict]:
        """Search books by title, series, writer, publisher, volume or path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            search_term = f"%{query}%"
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.title LIKE ?
                   OR b.filepath LIKE ?
                   OR b.writer LIKE ?
                   OR b.publisher LIKE ?
                   OR b.volume LIKE ?
                   OR s.name LIKE ?
            """, (search_term,) * 6)
            return sort_books_naturally([dict(row) for row in cursor.fetchall()])

    def bulk_add_books(self, books: List[Dict]) -> Tuple[int, int]:
        """Bulk add books.

        Each dict must contain ``filepath`` and may contain title, series_id,
        volume and ComicInfo metadata fields. Returns (success, skipped).
        """
        success = 0
        skipped = 0
        fields = (
            'title', 'series_id', 'volume', 'volume_num', 'filepath', 'file_size',
            'writer', 'publisher', 'year', 'summary', 'page_count', 'genre', 'language',
        )

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for book in books:
                try:
                    record = {
                        'title': book.get('title'),
                        'series_id': book.get('series_id'),
                        'volume': book.get('volume'),
                        'volume_num': self._extract_volume_number(book.get('volume')),
                        'filepath': book['filepath'],
                        'file_size': self._file_size(book['filepath']),
                    }
                    for key in ('writer', 'publisher', 'year', 'summary', 'page_count', 'genre', 'language'):
                        value = book.get(key)
                        if value not in (None, ''):
                            record[key] = value

                    columns = ', '.join(column for column in fields if column in record)
                    placeholders = ', '.join('?' for column in fields if column in record)
                    values = [record[column] for column in fields if column in record]
                    cursor.execute(
                        f"INSERT INTO books ({columns}) VALUES ({placeholders})",
                        values
                    )
                    success += 1
                except sqlite3.IntegrityError:
                    skipped += 1
                except Exception as exc:
                    logger.error(f"Failed to import {book.get('filepath')}: {exc}")
                    skipped += 1

        logger.info(f"Bulk import: {success} added, {skipped} skipped")
        return success, skipped

    def get_statistics(self) -> Dict:
        """Library statistics used by the dashboard/status bar."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(is_read), 0) AS read_count,
                    COALESCE(SUM(favorite), 0) AS favorites,
                    COALESCE(SUM(file_size), 0) AS total_size,
                    COALESCE(SUM(page_count), 0) AS total_pages
                FROM books
            """)
            row = dict(cursor.fetchone())
            cursor.execute("SELECT COUNT(*) AS count FROM series")
            row['series_count'] = cursor.fetchone()['count']
            cursor.execute(
                "SELECT COUNT(*) AS count FROM books WHERE last_opened_at IS NOT NULL"
            )
            row['started_count'] = cursor.fetchone()['count']
            row['unread_count'] = row['total'] - row['read_count']
            cursor.execute("SELECT LOWER(filepath) AS path FROM books")
            formats: Dict[str, int] = {}
            for item in cursor.fetchall():
                path = item['path']
                if path.endswith(('.cbz', '.cbr', '.cb7', '.cbt')):
                    key = 'comic'
                elif path.endswith('.pdf'):
                    key = 'pdf'
                elif path.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff')):
                    key = 'image'
                elif path.endswith(('.zip', '.rar', '.7z', '.tar', '.tgz')):
                    key = 'archive'
                else:
                    key = 'other'
                formats[key] = formats.get(key, 0) + 1
            row['formats'] = formats
            return row
    
    def book_exists(self, filepath: str) -> bool:
        """Check if a book with the same path already exists (case-insensitive)."""
        return self.find_duplicate(filepath) is not None

    def find_duplicate(self, filepath: str,
                       file_hash: Optional[str] = None) -> Optional[Dict]:
        """Return the existing book matching *filepath* or *file_hash*.

        Two books are the same when their normalised path matches, or when the
        content fingerprint matches (the file was renamed or moved). This is what
        keeps repeated folder imports from adding the same comic twice.
        """
        target = normalize_path(filepath)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books")
            for row in cursor.fetchall():
                book = dict(row)
                if normalize_path(book.get("filepath", "")) == target:
                    return book
            if file_hash:
                cursor.execute(
                    "SELECT * FROM books WHERE file_hash = ? LIMIT 1", (file_hash,)
                )
                row = cursor.fetchone()
                if row:
                    return dict(row)
        return None

    def get_library_index(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Return (normalised path -> id, file hash -> id) for the whole library.

        Building the index once makes importing a large folder linear instead of
        comparing every file with every book.
        """
        paths: Dict[str, int] = {}
        hashes: Dict[str, int] = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, filepath, file_hash FROM books")
            for row in cursor.fetchall():
                paths[normalize_path(row["filepath"])] = row["id"]
                if row["file_hash"]:
                    hashes[row["file_hash"]] = row["id"]
        return paths, hashes

    def get_series_volume_numbers(self, series_id: Optional[int]) -> set:
        """Volume numbers already used inside a series (for the numbering plan)."""
        if series_id is None:
            return set()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT volume_num FROM books WHERE series_id = ? "
                "AND volume_num IS NOT NULL",
                (series_id,),
            )
            return {int(row[0]) for row in cursor.fetchall() if row[0] is not None}

    def get_series_by_name_ci(self, name: str) -> Optional[Dict]:
        """Find a series by name, ignoring case and surrounding spaces."""
        if not name:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM series WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))",
                (name,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_all_volume_numbers(self) -> int:
        """
        Update volume_num for all books based on their volume field.
        Returns number of books updated.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all books with volume
            cursor.execute("SELECT id, volume FROM books WHERE volume IS NOT NULL")
            books = cursor.fetchall()
            
            updated_count = 0
            
            for book_id, volume in books:
                volume_num = self._extract_volume_number(volume)
                if volume_num is not None:
                    cursor.execute(
                        "UPDATE books SET volume_num = ? WHERE id = ?",
                        (volume_num, book_id)
                    )
                    updated_count += 1
            
            logger.info(f"Updated volume numbers for {updated_count} books")
            return updated_count


def compute_file_hash(filepath: str, chunk_size: int = 65536) -> Optional[str]:
    """Cheap content fingerprint: size + head and tail hashes.

    Reading 128 KB per file keeps folder scans fast even for large libraries,
    while still detecting the same comic saved under a different name.
    """
    import hashlib

    path = Path(filepath)
    try:
        size = path.stat().st_size
        digest = hashlib.sha1()
        with open(path, "rb") as handle:
            digest.update(handle.read(chunk_size))
            if size > chunk_size * 2:
                handle.seek(-chunk_size, os.SEEK_END)
                digest.update(handle.read(chunk_size))
        return f"{size}:{digest.hexdigest()}"
    except OSError:
        return None


# Global database instance
db = Database()